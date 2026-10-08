STRATEGY_VERSION = '科创3旧模型动态仓位50万_执行修复V1'

def init(context):
    _legacy_init(context)
    g.day = None
    g.prepared = False
    g.session_blocked = False
    g.submitting = False
    g.early = []
    g.records = {}
    g.exit_pass = None
    log.info('VERSION=%s INITIAL_CAPITAL_SETTING=500000 dynamic=10%%..20%% NO_RETRAIN' % STRATEGY_VERSION)
    if len(context.portfolio.positions):
        g.session_blocked = True
        log.warn('RESTART_WITH_HOLDINGS: original entry state unavailable; stop new orders, require reconciliation')

def before_trading(context):
    today = get_datetime().date()
    if g.day == today:
        log.warn('DUPLICATE_PREPARATION ignored date=%s' % str(today))
        return
    g.day = today
    g.prepared = False
    g.daily_buy_value = 0.0
    g.daily_sell_value = 0.0
    _poll_orders(context)
    if g.session_blocked or g.order_intent:
        g.session_blocked = True
        log.warn('UNRESOLVED_ORDERS: preparation/orders blocked; ids=%s' % str(list(g.order_intent.keys())))
        return
    try:
        _legacy_before_trading(context)
        g.prepared = True
        log.info('SIGNAL_READY date=%s version=%s' % (str(today), STRATEGY_VERSION))
    except Exception as exc:
        g.session_blocked = True
        log.warn('PREPARATION_FAILED %s' % str(exc))

def handle_bar(context, bar_dict):
    today = get_datetime().date()
    if g.session_blocked or not g.prepared or g.day != today:
        log.warn('EXECUTION_BLOCKED: not prepared or account/order state uncertain')
        return
    if g.exit_pass == today:
        log.warn('DUPLICATE_DAILY_EXECUTION ignored')
        return
    # Set BEFORE executing to protect reentrant callbacks and exceptions.
    g.exit_pass = today
    g.cash_budget = float(context.portfolio.stock_account.available_cash)
    try:
        _legacy_handle_bar(context, bar_dict)
    except Exception as exc:
        g.session_blocked = True
        log.warn('EXECUTION_EXCEPTION: stop new orders %s' % str(exc))

def _safe_place(symbol, target, action, probability=0.0, reserve=0.0):
    if g.session_blocked or symbol in g.order_locks:
        return None
    if action == 'BUY':
        if reserve <= 0 or reserve > g.cash_budget:
            log.warn('LOCAL_CASH_GUARD symbol=%s reserve=%.2f' % (symbol,reserve))
            return None
        g.cash_budget -= reserve
    g.order_locks[symbol] = 'SUBMITTING'
    g.submitting = True
    g.early = []
    try:
        oid = order_target_percent(symbol, target) if action == 'BUY' else order_target(symbol, int(target))
    except Exception as exc:
        # The server may have accepted it before the transport exception.
        g.session_blocked = True
        g.submitting = False
        log.warn('SUBMISSION_UNCERTAIN %s %s; keep lock, reconcile platform orders' % (symbol, str(exc)))
        return None
    g.submitting = False
    if oid is None:
        g.order_locks.pop(symbol, None)
        if action == 'BUY' and not g.early:g.cash_budget += reserve
        if g.early:
            g.session_blocked = True
            log.warn('ORDER_ID_MISSING_WITH_CALLBACK: reconcile required')
        log.warn('ORDER_NOT_CREATED symbol=%s action=%s' % (symbol, action))
        return None
    if oid in g.records:
        g.session_blocked = True
        log.warn('REUSED_ORDER_ID %s' % str(oid))
        return None
    rec = {'symbol':symbol, 'action':action, 'probability':probability,
           'qty':0.0, 'notional':0.0, 'terminal':False, 'date':get_datetime().date()}
    g.records[oid] = rec
    g.order_locks[symbol] = oid
    g.order_intent[oid] = rec
    g.submitted_action[symbol] = {'action':action, 'date':get_datetime().date()}
    log.info('ORDER_SUBMIT id=%s symbol=%s action=%s target=%s' % (str(oid),symbol,action,str(target)))
    for event in g.early:
        _apply_event(event)
    g.early = []
    return oid

def _submit(symbol, target_amount, action):
    return _safe_place(symbol, target_amount, action)

def on_order(context, odr):
    try:
        event = (odr.order_id, str(odr.status).upper().split('.')[-1], float(odr.filled_amount), float(odr.avg_price))
    except Exception as exc:
        g.session_blocked = True
        log.warn('ORDER_SCHEMA_ERROR %s' % str(exc))
        return
    if g.submitting:
        g.early.append(event)
        return
    _apply_event(event)

def _apply_event(event):
    oid, status, qty, price = event
    rec = g.records.get(oid)
    if rec is None:
        g.session_blocked = True
        log.warn('UNKNOWN_ORDER id=%s status=%s; account reconciliation required' % (str(oid),status))
        return
    if not np.isfinite(qty) or qty < 0 or (qty > 0 and (not np.isfinite(price) or price <= 0)):
        g.session_blocked = True
        log.warn('INVALID_FILL id=%s' % str(oid))
        return
    if qty < rec['qty']:
        log.warn('STALE_ORDER_EVENT ignored id=%s' % str(oid))
        return
    if rec['terminal']:
        if qty != rec['qty'] or (qty > 0 and abs(qty*price-rec['notional']) > .01):
            g.session_blocked = True
            log.warn('LATE_FILL_AFTER_TERMINAL: reconcile id=%s' % str(oid))
        return
    notional = qty*price if qty else 0.0
    delta = notional-rec['notional']
    if delta < -.01 or (qty == rec['qty'] and abs(delta) > .01):
        g.session_blocked = True
        log.warn('FILL_REVISION: reconcile id=%s' % str(oid))
        return
    if qty > rec['qty']:
        if rec['date'] != get_datetime().date():
            g.session_blocked = True
            log.warn('LATE_PRIOR_DAY_FILL id=%s delta=%.2f' % (str(oid),delta))
        elif rec['action'] == 'BUY':
            g.daily_buy_value += delta
        else:
            g.daily_sell_value += delta
        if rec['action'] == 'TPHALF' and rec['symbol'] in g.position_state:
            g.position_state[rec['symbol']]['half'] = True
    rec['qty'] = qty
    rec['notional'] = notional
    # Test terminal states before PART: PARTIALLY_CANCELLED is terminal.
    terminal = status in ('CANCELLED','CANCELED','PARTIALLY_CANCELLED','REJECTED','FILLED','ALLTRADED')
    recognized = terminal or status in ('PARTIALLY_FILLED','PARTIAL','NEW','PENDING','OPEN','ACTIVE','HELD','PENDING_NEW','PENDING_CANCEL')
    if not recognized:
        g.session_blocked = True
        log.warn('UNKNOWN_ORDER_STATUS %s id=%s' % (status,str(oid)))
    if terminal:
        rec['terminal'] = True
        g.order_intent.pop(oid,None)
        if g.order_locks.get(rec['symbol']) == oid:g.order_locks.pop(rec['symbol'],None)
    log.info('ORDER_EVENT id=%s symbol=%s status=%s cumulative_qty=%.0f cumulative_value=%.2f terminal=%s' %
             (str(oid),rec['symbol'],status,qty,notional,str(terminal)))

def _poll_orders(context):
    for oid in list(g.order_intent.keys()):
        try:
            odr = get_order(oid)
            if odr is None:
                log.warn('ORDER_QUERY_EMPTY id=%s' % str(oid))
            else:
                on_order(context, odr)
        except Exception as exc:
            log.warn('ORDER_QUERY_FAILED id=%s %s' % (str(oid),str(exc)))

def after_trading(context):
    _poll_orders(context)
    _reconcile_position_state(context)
    total = float(context.portfolio.stock_account.total_value)
    gross = g.daily_buy_value + g.daily_sell_value
    log.info('EXECUTION_AUDIT version=%s buy=%.2f sell=%.2f nav=%.2f cash=%.2f turnover=%.6f unresolved=%d blocked=%s' %
             (STRATEGY_VERSION,g.daily_buy_value,g.daily_sell_value,total,_available_cash(context),gross/total if total>0 else 0.,len(g.order_intent),str(g.session_blocked)))
    log.info('POSITION_AUDIT %s' % str([(symbol,float(pos.amount),float(pos.cost_basis),float(pos.last_price)) for symbol,pos in context.portfolio.positions.items()]))
    if g.order_intent:
        log.warn('UNRESOLVED_AT_CLOSE: do not equate audit totals with actual fills; export platform order/trade records')
