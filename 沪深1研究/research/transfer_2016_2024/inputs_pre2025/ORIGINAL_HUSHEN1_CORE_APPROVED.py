# Frozen original Hushen1 core reference. Read only; never import as platform module.
# Approved source excerpts contain strategy logic only; no performance or post-boundary market data.
import math
import numpy as np
import pandas as pd
MODEL = "D11"
SMOOTH = 5
MIN_SMOOTH = 3
INTERVAL = 20
BUFFER = 1.5
DRIFT = False
COUNT = 5
EXPOSURE = 0.98
SLIP_ONE_SIDE = 0.001
PARTICIPATION = 0.005
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
MAX_ORDER_SHARES = 1000000
FIELDS = ['open','close','prev_close','volume','turnover','turnover_rate','is_paused','is_st']

def mainboard(symbol):
    return ((symbol.endswith('.SH') and symbol[:3] in ('600', '601', '603', '605')) or
            (symbol.endswith('.SZ') and symbol[:3] in ('000', '001', '002', '003')))


def compute_signals(raw, members, dates):
    """Pure function. All raw rows must end on the signal date, never execution day.
    members maps each historical score date to THAT date's listed stock universe.
    """
    dates = pd.DatetimeIndex(dates)
    symbols = sorted(raw)
    matrices = {k: pd.DataFrame(np.nan, index=dates, columns=symbols, dtype=float)
                for k in ('cap', 'vol', 'overnight', 'intraday')}
    eligible = pd.DataFrame(False, index=dates, columns=symbols)
    info = {}
    for s in symbols:
        x = raw[s].copy()
        x.index = pd.DatetimeIndex(x.index).normalize()
        x = x.loc[~x.index.duplicated(keep='last')].sort_index()
        x = x.loc[(x.index <= dates[-1]) & (x['close'] > 0)]
        if x.empty:
            continue
        x = x[FIELDS].astype(float)
        r = (x.close / x.prev_close - 1).where((x.is_paused == 0) & (x.prev_close > 0), 0)
        vol = r.rolling(60).std()
        with np.errstate(divide='ignore', invalid='ignore'):
            overnight = np.log(x.open / x.prev_close).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(x.close / x.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        amount = x.turnover.rolling(20).mean()
        volume = x.volume.rolling(20).mean()
        cap = x.close * x.volume / (x.turnover_rate / 100).replace(0, np.nan)
        age = pd.Series(np.arange(len(x)) + 1, index=x.index)
        ok = ((age >= 252) & (amount >= 1e7) & (x.close >= 2) &
              (x.is_st == 0) & (x.is_paused == 0) & (vol > .001) & (vol < .09))
        # Match the independent engine's feature precision before ranking.
        for name, values in [('cap', cap), ('vol', vol), ('overnight', overnight), ('intraday', intraday)]:
            matrices[name][s] = values.astype(np.float32).reindex(dates)
        eligible[s] = ok.reindex(dates).fillna(False).astype(bool)
        if dates[-1] in x.index:
            info[s] = {'volume20': float(volume.loc[dates[-1]]),
                       'previous_st': bool(x.loc[dates[-1], 'is_st'])}
    for d in dates:
        allowed = members[d.strftime('%Y-%m-%d')]
        eligible.loc[d] &= pd.Series([s in allowed for s in symbols], index=symbols)
    ranked = {k: v.where(eligible).rank(axis=1, pct=True, method='average').astype(np.float32)
              for k, v in matrices.items()}
    score = (-.35 * ranked['cap'] - .20 * ranked['vol'] +
             .25 * ranked['overnight'] - .20 * ranked['intraday'])
    smooth = score.rolling(SMOOTH, min_periods=MIN_SMOOTH).mean().astype(np.float32)
    last = smooth.iloc[-1].where(eligible.iloc[-1]).dropna()
    # mergesort preserves lexical symbol order on ties.
    ranking = last.sort_values(ascending=False, kind='mergesort').index.tolist()[:100]
    return ranking, info

def _valid_bar(b):
    return (b is not None and not b.is_paused and np.isfinite(b.open) and b.open > 0 and
            np.isfinite(b.high_limit) and np.isfinite(b.low_limit) and
            0 < b.low_limit <= b.open <= b.high_limit)


def _buy_cost(q, op):
    value = q * (op * (1 + SLIP_ONE_SIDE) + .01)
    # Conservative cash buffer for transfer fee; platform books actual charges.
    return value + max(MIN_COMMISSION, value * COMMISSION_RATE) + value * .00002


def _handle_bar(context, bar_dict):
    _assert_isolated(context)
    day = _date(get_datetime())
    if g.alpha_executed == day:
        return
    if not g.alpha_ready:
        raise RuntimeError('before_trading did not prepare the previous-day signals')
    g.alpha_executed = day
    positions = _positions(context)
    # NAV at current OPEN, never today's close/high/low/volume.
    nav = _cash(context) + float(context.portfolio.stock_account.frozen_cash)
    for s, pos in positions.items():
        b = _bar(bar_dict, s)
        nav += pos.amount * (float(b.open) if _valid_bar(b) else float(pos.last_price))
    rebalance = g.alpha_first or (g.alpha_index - 1) % INTERVAL == 0
    if rebalance:
        budget = nav * EXPOSURE / COUNT
        ranks = g.alpha_ranks
        keep = set(ranks[:int(COUNT * BUFFER)])
        def can_select(s):
            b = _bar(bar_dict, s)
            return (_valid_bar(b) and not b.is_st and b.open < b.high_limit - 1e-8 and
                    _buy_cost(100, b.open) <= budget)
        selected = [s for s in ranks if s in positions and s in keep and can_select(s)][:COUNT]
        for s in ranks:
            if len(selected) >= COUNT:
                break
            if s not in selected and can_select(s):
                selected.append(s)
        targets = {s: 0 for s in positions if s not in selected}
        for s in selected:
            op = float(bar_dict[s].open)
            if DRIFT and s in positions:
                targets[s] = min(int(positions[s].amount), int(1.5 * budget / op / 100) * 100)
            else:
                targets[s] = int(budget / op / 100) * 100
        g.alpha_targets = targets
        g.alpha_first = False
        log.info('%s signal=%s rank=%s targets=%s' % (MODEL, g.alpha_last_data, ranks[:10], targets))
    for s in positions:
        if g.alpha_info.get(s, {}).get('previous_st', False):
            g.alpha_targets[s] = 0
    # Outstanding broker/platform orders remain authoritative, not assumed fills.
    active = {o.symbol for o in (get_open_orders() or [])}
    cash_budget = _cash(context)
    keys = sorted(g.alpha_targets, key=lambda s: (g.alpha_targets[s] - (positions[s].amount if s in positions else 0) >= 0, s))
    for s in keys:
        if s in active:
            continue
        positions = _positions(context)
        pos = positions.get(s)
        current = int(pos.amount) if pos is not None else 0
        delta = g.alpha_targets[s] - current
        b = _bar(bar_dict, s)
        if delta == 0 or not _valid_bar(b):
            continue
        volume = g.alpha_info.get(s, {}).get('volume20', np.nan)
        if not np.isfinite(volume):
            continue
        cap = int(volume * PARTICIPATION / 100) * 100
        quantity = min(abs(delta), cap, MAX_ORDER_SHARES)
        if delta < 0:
            if b.open <= b.low_limit + 1e-8:
                continue
            quantity = min(quantity, int(pos.available_amount))
            if quantity != current:
                quantity = int(quantity // 100) * 100
            if quantity > 0:
                before = _cash(context)
                _submit(context, s, -int(quantity), _limit_price(b, False))
                # Reuse only cash already credited by actual platform fills.
                cash_budget += max(0., _cash(context) - before)
        else:
            if b.is_st or b.open >= b.high_limit - 1e-8:
                continue
            quantity = int(quantity // 100) * 100
            available = min(cash_budget, _cash(context))
            while quantity > 0 and _buy_cost(quantity, b.open) > available:
                quantity -= 100
            if quantity > 0:
                result = _submit(context, s, int(quantity), _limit_price(b, True))
                if result is not None:
                    cash_budget -= _buy_cost(quantity, b.open)
    # Unfinished targets are retained for next session and replaced on rebalance.
