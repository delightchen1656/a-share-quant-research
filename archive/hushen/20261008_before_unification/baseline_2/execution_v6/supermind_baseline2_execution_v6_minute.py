# -*- coding: utf-8 -*-
"""Independent alpha, SuperMind stock MINUTE execution; daily signals. Generated as two standalone files.
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
VERSION = '2026-10-08-baseline2-execution-v6'
EXEC_END = 1000
REPRICE_MINUTES = 5
MAX_ATTEMPTS = 6
MAX_CHASE = 0.01
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
    score = (-.35 * ranked['cap'] - .20 * ranked['vol'] +
             .25 * ranked['overnight'] - .20 * ranked['intraday'])
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


def _limit_price(b, buy, anchor=None):
    # b.close is the completed minute close, never the day's future close.
    ref = float(b.close)
    anchor = ref if anchor is None else anchor
    if buy:
        cap = min(float(b.high_limit), anchor * (1 + MAX_CHASE))
        limit = min(math.ceil(ref * (1 + SLIP_ONE_SIDE) * 100 - 1e-8) / 100,
                    math.floor(cap * 100 + 1e-8) / 100)
    else:
        floor = max(float(b.low_limit), anchor * (1 - MAX_CHASE))
        limit = max(math.floor(ref * (1 - SLIP_ONE_SIDE) * 100 + 1e-8) / 100,
                    math.ceil(floor * 100 - 1e-8) / 100)
    return limit


def _submit(context, symbol, quantity, limit):
    if not mainboard(symbol) or not np.isfinite(limit) or limit <= 0:
        raise ValueError('Invalid mainboard order')
    g.alpha_managed.add(symbol)
    g.alpha_submitting = symbol
    try:
        result = order(symbol, int(quantity), price=limit)
    finally:
        g.alpha_submitting = None
    if result is not None:
        oid = str(getattr(result, 'order_id', result))
        g.alpha_order_ids.add(oid)
        # A returned ID may precede all callbacks. Block another order until
        # get_orders supplies terminal confirmation, even if a cancel is sent.
        if oid not in g.exec_orders:
            g.exec_orders[oid] = PendingReceipt(oid, symbol, quantity, limit, get_datetime())
        log.info('SUBMIT V6 %s qty=%s limit=%.2f id=%s' % (symbol, quantity, limit, oid))
    else:
        log.info('NO_ORDER V6 %s qty=%s; no assumed fill' % (symbol, quantity))
    return result


def _init(context):
    frequency = str(context.run_info.frequency).lower()
    if frequency not in ('1m', 'minute', 'minutely'):
        raise ValueError('V6 requires MINUTE / 1m frequency, initial cash 100000')
    set_benchmark('000905.SH')
    set_commission(PerShare(type='stock', cost=COMMISSION_RATE, min_trade_cost=MIN_COMMISSION))
    # Price tolerance is in the order limit. Do not add accounting slippage
    # above a buy limit / below a sell limit a second time.
    set_slippage(PriceSlippage(0.0))
    set_volume_limit(daily=0.25, minute=0.25)
    g.alpha_raw = {}
    g.alpha_members = {}
    g.alpha_targets = {}
    g.alpha_close_shares = {}
    g.alpha_last_data = None
    g.alpha_first = True
    g.alpha_ready = False
    g.alpha_managed = set()
    g.alpha_order_ids = set()
    g.alpha_submitting = None
    g.exec_day = None
    g.exec_last_bar = None
    g.exec_orders = {}
    g.exec_seen_orders = set()
    g.exec_seen_trades = set()
    g.exec_filled = {}
    g.exec_audit = []
    _assert_isolated(context)
    log.info('V6 MINUTE execution 09:31-10:00; factors unchanged; platform taxes require receipt audit')


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
    return (b is not None and not b.is_paused and np.isfinite(b.close) and b.close > 0 and
            np.isfinite(b.high_limit) and np.isfinite(b.low_limit) and
            0 < b.low_limit <= b.close <= b.high_limit)


def _buy_cost(q, limit):
    value = q * limit
    return value + max(MIN_COMMISSION, value * COMMISSION_RATE) + value * .00002


def _handle_bar(context, bar_dict):
    _assert_isolated(context)
    now = pd.Timestamp(get_datetime())
    stamp = now.strftime('%Y-%m-%d %H:%M')
    if stamp == g.exec_last_bar:
        return
    g.exec_last_bar = stamp
    hhmm = now.hour * 100 + now.minute
    if hhmm < 931 or hhmm > 1457:
        return
    if not g.alpha_ready:
        raise RuntimeError('Previous-day signals not ready')
    day = _date(now)
    live = _refresh_orders()
    if g.exec_day != day:
        # Never replace yesterday's targets while an old order is unresolved.
        if live:
            for odr in live:
                cancel_order(str(odr.order_id))
            return
        if hhmm >= EXEC_END:
            return
        _prepare_execution_day(context, bar_dict, day)
    for s in _positions(context):
        b = _bar(bar_dict, s)
        if g.alpha_info.get(s, {}).get('previous_st', False) or (b is not None and b.is_st):
            g.alpha_targets[s] = 0
    blocked = set()
    for odr in live:
        blocked.add(odr.symbol)
        age = (now - pd.Timestamp(odr.created)).total_seconds() / 60
        last_cancel = g.exec_cancel_at.get(str(odr.order_id))
        if (hhmm >= EXEC_END or age >= REPRICE_MINUTES) and (
                last_cancel is None or (now - last_cancel).total_seconds() >= 300):
            cancel_order(str(odr.order_id))
            g.exec_cancel_at[str(odr.order_id)] = now
            log.info('CANCEL_REQUEST %s id=%s; wait for terminal receipt' % (odr.symbol, odr.order_id))
    if hhmm >= EXEC_END:
        return
    positions = _positions(context)
    keys = sorted(g.alpha_targets, key=lambda s: (
        g.alpha_targets[s] - (positions[s].amount if s in positions else 0) >= 0, s))
    cash_budget = _cash(context)
    for s in keys:
        if s in blocked or g.exec_attempts.get(s, 0) >= MAX_ATTEMPTS:
            continue
        previous = g.exec_last_submit.get(s)
        if previous is not None and (now - previous).total_seconds() < REPRICE_MINUTES * 60:
            continue
        pos = _positions(context).get(s)
        current = int(pos.amount) if pos is not None else 0
        delta = g.alpha_targets[s] - current
        b = _bar(bar_dict, s)
        if not delta or not _valid_bar(b):
            continue
        # Reject stale or future minute bars; do not trade on an old opening quote.
        age_seconds = (now - pd.Timestamp(b.datetime)).total_seconds()
        if age_seconds < 0 or age_seconds > 90:
            log.info('SKIP stale quote %s bar=%s strategy=%s' % (s, b.datetime, now))
            continue
        if delta > 0 and (b.is_st or b.close >= b.high_limit - 1e-8):
            continue
        if delta < 0 and b.close <= b.low_limit + 1e-8:
            continue
        volume = g.alpha_info.get(s, {}).get('volume20', np.nan)
        if not np.isfinite(volume) or volume <= 0:
            continue
        g.exec_anchor.setdefault(s, float(b.close))
        limit = _limit_price(b, delta > 0, g.exec_anchor[s])
        # Do not leave an unmarketable limit after the 1% chase boundary is crossed.
        if (delta > 0 and limit < b.close) or (delta < 0 and limit > b.close):
            continue
        used = sum(max(0, g.exec_filled.get(k, 0) - g.exec_day_fill_base.get(k, 0))
                   for k, o in g.exec_orders.items() if o.symbol == s)
        cap = max(0, int(volume * PARTICIPATION / 100) * 100 - used)
        quantity = min(abs(delta), cap, MAX_ORDER_SHARES)
        if delta < 0:
            quantity = min(quantity, int(pos.available_amount))
            if quantity != current:
                quantity = int(quantity // 100) * 100
        else:
            quantity = int(quantity // 100) * 100
            available = min(cash_budget, _cash(context))
            while quantity > 0 and _buy_cost(quantity, limit) > available:
                quantity -= 100
        if quantity <= 0:
            continue
        before = _cash(context)
        g.exec_attempts[s] = g.exec_attempts.get(s, 0) + 1
        g.exec_last_submit[s] = now
        log.info('QUOTE %s time=%s last=%.2f anchor=%.2f limit=%.2f delta=%s cash=%.2f' %
                 (s, b.datetime, b.close, g.exec_anchor[s], limit, delta, before))
        result = _submit(context, s, int(quantity if delta > 0 else -quantity), limit)
        if delta > 0 and result is not None:
            cash_budget -= _buy_cost(quantity, limit)
        elif delta < 0:
            cash_budget += max(0., _cash(context) - before)
    # Unfinished targets are retained for next session and replaced on rebalance.


def _after_trading(context):
    g.alpha_close_shares = {s: int(p.amount) for s, p in _positions(context).items()}
    residual = {s: q - g.alpha_close_shares.get(s, 0)
                for s, q in g.alpha_targets.items() if q != g.alpha_close_shares.get(s, 0)}
    log.info('END V6 remaining=%s; targets retained until next rebalance; fee/limit alerts=%s' %
             (residual, len(g.exec_audit)))


def on_order(context, odr):
    _remember_order(odr)
    if str(odr.order_id) not in g.alpha_order_ids:
        return
    key = (str(odr.order_id), _status(odr), int(odr.filled_amount))
    if key not in g.exec_seen_orders:
        g.exec_seen_orders.add(key)
        log.info('ORDER %s' % odr)


def on_trade(context, trade):
    oid = str(trade.order_id)
    symbol = trade.order_book_id
    if oid not in g.alpha_order_ids and symbol != g.alpha_submitting:
        return
    g.alpha_order_ids.add(oid)
    key = str(trade.exec_id)
    if key in g.exec_seen_trades:
        return
    g.exec_seen_trades.add(key)
    log.info('FILL %s' % trade)
    # Audit only: never alter the platform's cash, holdings or performance curve.
    value = abs(float(trade.last_quantity) * float(trade.last_price))
    sell = str(trade.side).split('.')[-1].upper() == 'SELL'
    rate = (.001 if _date(get_datetime()) < '2023-08-28' else .0005) if sell else 0.
    expected = round(value * rate, 2)
    if abs(float(trade.tax) - expected) > .02:
        message = 'FEE_MISMATCH id=%s platform_tax=%.4f expected_stamp=%.2f' % (oid, trade.tax, expected)
        g.exec_audit.append(message)
        log.warn(message)
    odr = g.exec_orders.get(oid)
    if odr is not None and ((not sell and trade.last_price > odr.limit_price + 1e-7) or
                            (sell and trade.last_price < odr.limit_price - 1e-7)):
        message = 'LIMIT_BREACH id=%s price=%s limit=%s' % (oid, trade.last_price, odr.limit_price)
        g.exec_audit.append(message)
        log.warn(message)


def _run_stage(stage, func, *args):
    started = pd.Timestamp.utcnow()
    verbose = VERBOSE or stage in ('init', 'before_trading')
    if verbose:
        log.info('ALPHA START %s version=%s wall_utc=%s strategy_time=%s' %
                 (stage, VERSION, started, get_datetime()))
    try:
        result = func(*args)
    except Exception as exc:
        log.info('ALPHA FAILED stage=%s error=%s' % (stage, str(exc)))
        raise
    if verbose:
        log.info('ALPHA DONE %s elapsed_seconds=%.3f wall_utc=%s' %
                 (stage, (pd.Timestamp.utcnow() - started).total_seconds(), pd.Timestamp.utcnow()))
    return result


def init(context):
    return _run_stage('init', _init, context)


def before_trading(context):
    return _run_stage('before_trading', _before_trading, context)


def handle_bar(context, bar_dict):
    return _run_stage('handle_bar', _handle_bar, context, bar_dict)


def after_trading(context):
    return _run_stage('after_trading', _after_trading, context)


def _status(order):
    return str(order.status).split('.')[-1].upper()

def _terminal(order):
    return _status(order) in ('FILLED', 'REJECTED', 'CANCELLED', 'CANCELED', 'EXPIRED_ABSENT')

def _remember_order(odr):
    oid = str(odr.order_id)
    if oid not in g.alpha_order_ids and odr.symbol != g.alpha_submitting:
        return
    g.alpha_order_ids.add(oid)
    old = g.exec_orders.get(oid)
    # Ignore out-of-order snapshots that would regress a terminal status or fills.
    if old is not None and (_terminal(old) and not _terminal(odr) or
                            old.filled_amount > odr.filled_amount):
        return
    g.exec_orders[oid] = odr
    g.exec_filled[oid] = max(g.exec_filled.get(oid, 0), int(odr.filled_amount))

def _refresh_orders():
    # Query the account's authoritative day orders, not callback timing alone.
    for odr in get_orders() or []:
        _remember_order(odr)
    actual_open = get_open_orders() or []
    foreign = [o for o in actual_open if str(o.order_id) not in g.alpha_order_ids]
    if foreign:
        raise RuntimeError('Dedicated account has unmanaged active orders; refusing to overlap')
    for odr in actual_open:
        _remember_order(odr)
    open_ids = {str(o.order_id) for o in actual_open}
    for oid, odr in g.exec_orders.items():
        if not _terminal(odr) and _date(odr.created) < _date(get_datetime()) and oid not in open_ids:
            # Day orders cannot survive overnight. Do not invent fills: only
            # mark local tracking closed after authoritative open-order query;
            # tomorrow's delta still comes from actual portfolio holdings.
            g.exec_orders[oid] = PendingReceipt(oid, odr.symbol, odr.amount, odr.limit_price, odr.created)
            g.exec_orders[oid].status = 'EXPIRED_ABSENT'
            log.info('RECONCILE previous-day order absent from active query id=%s; use actual holdings' % oid)
    return [o for o in g.exec_orders.values() if not _terminal(o)]

class PendingReceipt:
    def __init__(self, oid, symbol, qty, price, created):
        self.order_id, self.symbol, self.created = oid, symbol, created
        self.amount, self.filled_amount = abs(qty), 0
        self.limit_price, self.status = price, 'PENDING_NEW'

def _prepare_execution_day(context, bar_dict, day):
    g.exec_day = day
    g.exec_anchor, g.exec_attempts, g.exec_last_submit = {}, {}, {}
    g.exec_cancel_at = {}
    g.exec_start_qty = {s: int(p.amount) for s, p in _positions(context).items()}
    g.exec_day_fill_base = dict(g.exec_filled)
    # Old completed receipts are not needed for today's order reconciliation.
    g.exec_orders = {k: o for k, o in g.exec_orders.items() if not _terminal(o)}
    g.exec_seen_orders, g.exec_seen_trades = set(), set()
    positions = _positions(context)
    if g.alpha_first or (g.alpha_index - 1) % INTERVAL == 0:
        nav = _cash(context) + float(context.portfolio.stock_account.frozen_cash)
        for s, pos in positions.items():
            b = _bar(bar_dict, s)
            nav += pos.amount * (float(b.close) if _valid_bar(b) else float(pos.last_price))
        budget = nav * EXPOSURE / COUNT
        ranks = g.alpha_ranks
        keep = set(ranks[:int(COUNT * BUFFER)])
        def can_select(s):
            b = _bar(bar_dict, s)
            return (_valid_bar(b) and not b.is_st and b.close < b.high_limit - 1e-8 and
                    _buy_cost(100, _limit_price(b, True)) <= budget)
        selected = [s for s in ranks if s in positions and s in keep and can_select(s)][:COUNT]
        for s in ranks:
            if len(selected) == COUNT:
                break
            if s not in selected and can_select(s):
                selected.append(s)
        g.alpha_targets = {s: 0 for s in positions if s not in selected}
        for s in selected:
            g.alpha_targets[s] = int(budget / float(bar_dict[s].close) / 100) * 100
        g.alpha_first = False
        log.info('TARGET V6 signal=%s targets=%s' % (g.alpha_last_data, g.alpha_targets))
