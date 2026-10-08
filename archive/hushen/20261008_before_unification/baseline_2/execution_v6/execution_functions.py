"""Build input, not a platform entry. Uses globals from the frozen v5 source."""

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


def _valid_bar(b):
    return (b is not None and not b.is_paused and np.isfinite(b.close) and b.close > 0 and
            np.isfinite(b.high_limit) and np.isfinite(b.low_limit) and
            0 < b.low_limit <= b.close <= b.high_limit)


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


def _buy_cost(q, limit):
    value = q * limit
    return value + max(MIN_COMMISSION, value * COMMISSION_RATE) + value * .00002


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


def _after_trading(context):
    g.alpha_close_shares = {s: int(p.amount) for s, p in _positions(context).items()}
    residual = {s: q - g.alpha_close_shares.get(s, 0)
                for s, q in g.alpha_targets.items() if q != g.alpha_close_shares.get(s, 0)}
    log.info('END V6 remaining=%s; targets retained until next rebalance; fee/limit alerts=%s' %
             (residual, len(g.exec_audit)))


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
