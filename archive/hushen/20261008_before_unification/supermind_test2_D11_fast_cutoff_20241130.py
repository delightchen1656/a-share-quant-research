# -*- coding: utf-8 -*-
# D11提速截止版：每日频率，初始资金100000元。
# 本轮拟合和验证只使用2024-11-30之前的观测及标签，权重在运行中不再训练。
# 推断仍使用每个交易日之前已知行情；不能把训练截止理解为冻结未来交易特征。
# 保留调仓日全市场排名、非调仓日持仓/目标处理的提速逻辑。
# 原版平台收益不属于此版本；尚无新版平台回测。
# 继承的D11框架曾接触后续历史，本轮截断不消除既有选优影响。
"""Independent alpha, SuperMind stock DAILY strategy. Generated as two standalone files.
Platform execution/dividend/tax accounting differs from the local research ledger.
No local files, precomputed future rankings, broker connections, or old strategy imports.
"""
from mindgo_api import *
import math
import numpy as np
import pandas as pd

MODEL = 'D11'  # replaced by build.py
SMOOTH = 20 if MODEL == 'E10' else 5
MIN_SMOOTH = 15 if MODEL == 'E10' else 3
INTERVAL = 10 if MODEL == 'E10' else 20
BUFFER = 3.0 if MODEL == 'E10' else 1.5
DRIFT = MODEL == 'E10'
COUNT = 5
EXPOSURE = 0.98
SLIP_ONE_SIDE = 0.001
PARTICIPATION = 0.005
COMMISSION_RATE = 0.0003  # User-confirmed assumption; not a verified account contract.
MIN_COMMISSION = 5.0
MAX_ORDER_SHARES = 1000000
HISTORY_ROWS = 320
BATCH_SIZE = 150
VERSION = '2026-10-04-D11-fast-cutoff20241130'
TRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'
CAP_WEIGHT = 0.3
VOL_WEIGHT = 0.25
OVERNIGHT_WEIGHT = 0.25
INTRADAY_WEIGHT = 0.2
VERBOSE = False
FIELDS = ['open', 'close', 'prev_close', 'volume', 'turnover',
          'turnover_rate', 'is_paused', 'is_st']


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
    score = (-CAP_WEIGHT * ranked['cap'] - VOL_WEIGHT * ranked['vol'] +
             OVERNIGHT_WEIGHT * ranked['overnight'] - INTRADAY_WEIGHT * ranked['intraday'])
    smooth = score.rolling(SMOOTH, min_periods=MIN_SMOOTH).mean().astype(np.float32)
    last = smooth.iloc[-1].where(eligible.iloc[-1]).dropna()
    # mergesort preserves lexical symbol order on ties.
    ranking = last.sort_values(ascending=False, kind='mergesort').index.tolist()[:100]
    return ranking, info


def _date(value):
    return pd.Timestamp(value).strftime('%Y-%m-%d')


def _cash(context):
    return float(context.portfolio.stock_account.available_cash)


def _positions(context):
    positions = context.portfolio.positions
    return {s: positions[s] for s in list(positions.keys()) if positions[s].amount > 0}


def _assert_isolated(context):
    foreign = set(_positions(context)) - g.alpha_managed
    if foreign:
        raise RuntimeError('Dedicated empty-start strategy account required; unmanaged holdings: %s' % sorted(foreign))


def _limit_price(b, buy):
    if buy:
        value = min(float(b.high_limit), float(b.open) * (1 + SLIP_ONE_SIDE))
        return math.floor(value * 100 + 1e-8) / 100
    value = max(float(b.low_limit), float(b.open) * (1 - SLIP_ONE_SIDE))
    return math.ceil(value * 100 - 1e-8) / 100


def _submit(context, symbol, quantity, limit):
    if not mainboard(symbol) or not np.isfinite(limit) or limit <= 0:
        raise ValueError('Invalid mainboard order')
    # Register before order(): platform callbacks may be synchronous in backtests.
    g.alpha_managed.add(symbol)
    g.alpha_submitting = symbol
    try:
        result = order(symbol, int(quantity), price=limit)
    finally:
        g.alpha_submitting = None
    if result is not None:
        oid = str(result)
        g.alpha_order_ids.add(oid)
        log.info('SUBMIT %s %s qty=%s limit=%.2f; acceptance is not a fill' % (MODEL, symbol, quantity, limit))
    else:
        log.info('NO_ORDER %s %s qty=%s; target retained' % (MODEL, symbol, quantity))
    return result


def _init(context):
    if MODEL not in ('E10', 'D11'):
        raise ValueError('Use a generated E10 or D11 standalone file')
    set_benchmark('000905.SH')
    set_commission(PerShare(type='stock', cost=COMMISSION_RATE, min_trade_cost=MIN_COMMISSION))
    # SuperMind specifies a TOTAL spread: .002 means +/- .001 per side.
    set_slippage(PriceSlippage(2 * SLIP_ONE_SIDE))
    # Explicit conservative matching limits; these are BACKTEST settings,
    # not an assertion that a real broker guarantees this volume or price.
    set_volume_limit(daily=0.25, minute=0.25)
    enable_open_bar()
    g.alpha_raw = {}
    g.alpha_members = {}
    g.alpha_targets = {}
    g.alpha_close_shares = {}
    g.alpha_last_data = None
    g.alpha_executed = None
    g.alpha_first = True
    g.alpha_ready = False
    g.alpha_managed = set()
    g.alpha_order_ids = set()
    g.alpha_submitting = None
    _assert_isolated(context)
    log.info('%s: 100000 CNY, DAILY/open bar; platform accounting, not local return reproduction' % MODEL)


def _fetch(symbols, end, start=None):
    result = {}
    for begin in range(0, len(symbols), BATCH_SIZE):
        group = symbols[begin:begin + BATCH_SIZE]
        if VERBOSE:
            log.info('ALPHA FETCH batch=%s/%s symbols=%s end=%s start=%s' %
                     (begin // BATCH_SIZE + 1, (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE,
                      len(group), end, start))
        # Same positional history API as the working strategies in this project.
        # Over-request short incremental windows, then explicitly trim by date.
        count = HISTORY_ROWS + 1 if start is None else min(HISTORY_ROWS + 1, max(4, (pd.Timestamp(end) - pd.Timestamp(start)).days + 2))
        data = history(group, FIELDS, count, '1d', False, None, True, False)
        if not isinstance(data, dict):
            raise TypeError('SuperMind history(list, ..., True, False) must return a dict')
        for s in group:
            if s not in data or data[s] is None or data[s].empty:
                raise ValueError('Historical data missing for %s; stop rather than silently change universe' % s)
            x = data[s].copy()
            if any(f not in x.columns for f in FIELDS):
                raise ValueError('Missing required quote fields for %s' % s)
            x.index = pd.DatetimeIndex(x.index).normalize()
            x = x.loc[x.index <= pd.Timestamp(end)].sort_index()
            if start is not None:
                x = x.loc[x.index >= pd.Timestamp(start)]
            if x.empty:
                raise ValueError('No completed historical bars for %s in requested window' % s)
            x = x.iloc[-HISTORY_ROWS:]
            result[s] = x
    return result


def _before_trading(context):
    g.alpha_ready = False
    _assert_isolated(context)
    today = pd.Timestamp(get_datetime()).normalize()
    history_end = today - pd.Timedelta(days=1)
    calendar = pd.DatetimeIndex(get_trade_days(start_date='20180101', end_date=today.strftime('%Y%m%d'))).normalize()
    prior = calendar[calendar < today]
    if len(prior) < SMOOTH:
        raise ValueError('Use a backtest start in 2019 or later')
    signal_dates = prior[-SMOOTH:]
    signal_day = _date(signal_dates[-1])
    for d in signal_dates:
        key = _date(d)
        if key not in g.alpha_members:
            if VERBOSE:
                log.info('ALPHA UNIVERSE date=%s' % key)
            universe = get_all_securities('stock', date=d.strftime('%Y%m%d'))
            g.alpha_members[key] = set(s for s in universe.index if mainboard(s))
    wanted = set().union(*(g.alpha_members[_date(d)] for d in signal_dates))
    wanted.update(_positions(context))
    new = sorted(wanted - set(g.alpha_raw))
    # A recently delisted symbol remains in historical score universes. Keep
    # its cached past rows, but do not demand post-delisting incremental bars.
    # Current holdings still require data; missing held-security data is fatal.
    current_needed = g.alpha_members[signal_day] | set(_positions(context))
    old = sorted(current_needed & set(g.alpha_raw))
    if new:
        g.alpha_raw.update(_fetch(new, signal_day))
    if old and g.alpha_last_data != signal_day:
        start = _date(pd.Timestamp(g.alpha_last_data) + pd.Timedelta(days=1))
        for s, x in _fetch(old, signal_day, start=start).items():
            merged = pd.concat([g.alpha_raw[s], x])
            g.alpha_raw[s] = merged.loc[~merged.index.duplicated(keep='last')].sort_index().iloc[-HISTORY_ROWS:]
    g.alpha_raw = {s: x for s, x in g.alpha_raw.items() if s in wanted}
    g.alpha_members = {_date(d): g.alpha_members[_date(d)] for d in signal_dates}
    g.alpha_last_data = signal_day
    # Keep original daily universe/history cache exactly; only avoid rankings
    # which the execution function never uses on non-rebalance days.
    g.alpha_index = int(np.sum(calendar < today))
    rebalance = g.alpha_first or (g.alpha_index - 1) % INTERVAL == 0
    if rebalance:
        log.info('ALPHA SIGNAL begin symbols=%s dates=%s' % (len(g.alpha_raw), len(signal_dates)))
        g.alpha_ranks, g.alpha_info = compute_signals(g.alpha_raw, g.alpha_members, signal_dates)
        log.info('ALPHA SIGNAL ready ranking_count=%s' % len(g.alpha_ranks))
        if not g.alpha_ranks:
            raise ValueError('No eligible ranking; verify data coverage/field units')
    else:
        # Execution needs volume20 and previous_st only for held/target names.
        # Match compute_signals filtering, ordering and rolling arithmetic.
        info = {}
        needed = set(_positions(context)) | set(g.alpha_targets)
        for s in needed:
            if s not in g.alpha_raw:
                continue
            x = g.alpha_raw[s].copy()
            x.index = pd.DatetimeIndex(x.index).normalize()
            x = x.loc[~x.index.duplicated(keep='last')].sort_index()
            x = x.loc[(x.index <= signal_dates[-1]) & (x['close'] > 0)]
            if x.empty or signal_dates[-1] not in x.index:
                continue
            volume = x['volume'].astype(float).rolling(20).mean()
            info[s] = {'volume20': float(volume.loc[signal_dates[-1]]),
                       'previous_st': bool(float(x.loc[signal_dates[-1], 'is_st']))}
        g.alpha_info = info
    # Preserve target units across platform-credited bonus shares. Never add cash
    # or shares ourselves: SuperMind owns corporate action accounting.
    positions = _positions(context)
    for s, old_amount in g.alpha_close_shares.items():
        now = positions[s].amount if s in positions else 0
        if old_amount > 0 and now > 0 and now != old_amount and s in g.alpha_targets:
            g.alpha_targets[s] = int(math.floor(g.alpha_targets[s] * now / old_amount + 1e-8))
            log.info('Platform share change %s %s->%s; target adjusted' % (s, old_amount, now))
    g.alpha_index = int(np.sum(calendar < today))
    g.alpha_ready = True


def _bar(bar_dict, symbol):
    try:
        return bar_dict[symbol]
    except KeyError:
        return None


def _valid_bar(b):
    return (b is not None and not b.is_paused and np.isfinite(b.open) and b.open > 0 and
            np.isfinite(b.high_limit) and np.isfinite(b.low_limit) and
            0 < b.low_limit <= b.open <= b.high_limit)


def _buy_cost(q, op):
    value = q * op * (1 + SLIP_ONE_SIDE)
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


def _after_trading(context):
    # No post-close cancellation/query and no account-wide cancel-all. Next
    # session checks actual open orders before retrying. Platform expiry applies.
    g.alpha_close_shares = {s: int(p.amount) for s, p in _positions(context).items()}
    residual = {s: q - g.alpha_close_shares.get(s, 0)
                for s, q in g.alpha_targets.items() if q != g.alpha_close_shares.get(s, 0)}
    if VERBOSE or residual:
        log.info('END %s remaining share differences=%s' % (MODEL, residual))


def on_order(context, odr):
    oid = str(odr.order_id)
    symbol = odr.symbol
    if oid in g.alpha_order_ids or symbol == g.alpha_submitting:
        g.alpha_order_ids.add(oid)
        log.info('ORDER %s' % odr)


def on_trade(context, trade):
    if str(trade.order_id) in g.alpha_order_ids:
        # Platform receipt includes actual quantity, price, commission and tax.
        # No guessed account debit or fabricated FIFO tax adjustment.
        log.info('FILL %s' % trade)


def _run_stage(stage, func, *args):
    if VERBOSE or stage == 'init':
        log.info('ALPHA START %s model=%s version=%s' % (stage, MODEL, VERSION))
    try:
        result = func(*args)
    except Exception as exc:
        # Keep sandbox-compatible diagnostics; platform prints the raised stack.
        log.info('ALPHA FAILED stage=%s model=%s error=%s' % (stage, MODEL, str(exc)))
        raise
    if VERBOSE or stage == 'init':
        log.info('ALPHA DONE %s' % stage)
    return result


def init(context):
    return _run_stage('init', _init, context)


def before_trading(context):
    return _run_stage('before_trading', _before_trading, context)


def handle_bar(context, bar_dict):
    return _run_stage('handle_bar', _handle_bar, context, bar_dict)


def after_trading(context):
    return _run_stage('after_trading', _after_trading, context)
