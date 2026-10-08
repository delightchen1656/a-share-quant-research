# Appended to the unchanged 3-1 feature and portable-model definitions.
STRATEGY_VERSION = '科创3-2：强势延持审计修正版'
SIGNAL_THRESHOLD = 0.63


def init(context):
    g.model = _load_model()
    g.model['threshold'] = SIGNAL_THRESHOLD
    g.model['fast_trees'] = [
        (np.asarray([n['f'] for n in t], dtype=np.int16),
         np.asarray([n['t'] for n in t]), np.asarray([n['m'] for n in t], dtype=bool),
         np.asarray([n['l'] for n in t], dtype=np.int16),
         np.asarray([n['r'] for n in t], dtype=np.int16),
         np.asarray([n['leaf'] for n in t], dtype=bool), np.asarray([n['v'] for n in t]))
        for t in g.model['trees']]
    g.stop_model = _load_stop_model()
    g.pending = []
    g.position_state = {}
    g.adjustment_anchor = {}
    g.order_intent = {}
    g.order_locks = {}
    g.early_events = {}
    g.submitting = False
    g.seen_fills = {}
    g.exit_prices = {}
    g.daily_buy_value = 0.0
    g.daily_sell_value = 0.0
    g.buy_done_date = None
    set_benchmark('000688.SH')
    set_slippage(PriceSlippage(COST_SCENARIOS[COST_SCENARIO]))
    set_commission(PerShare(type='stock', cost=0.0003, min_trade_cost=5.0))
    set_volume_limit(daily=0.25, minute=0.5)
    log.info('%s DAILY threshold=%.2f; historical results are development evidence' %
             (STRATEGY_VERSION, SIGNAL_THRESHOLD))


def _past(frame, today):
    if frame is None or frame.empty:
        return None
    x = frame.copy()
    x.index = pd.to_datetime(x.index)
    return x[x.index.normalize() < pd.Timestamp(today)].sort_index()


def _adjust_entry(symbol, frame):
    # Compare the SAME historical close before/after a corporate action.
    # Do not infer dividends from realized-profit changes in broker cost_basis.
    old = g.adjustment_anchor.get(symbol)
    state = g.position_state.get(symbol)
    if old is not None and state is not None:
        rows = frame[frame.index.normalize() == pd.Timestamp(old['date'])]
        if rows.empty:
            log.warn('ACTION_ANCHOR_MISSING %s: exit signal skipped' % symbol)
            return False
        factor = float(rows['close'].iloc[-1]) / old['close']
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError('Invalid adjustment factor for ' + symbol)
        state['entry'] *= factor
        if abs(factor - 1.0) > 1e-8:
            log.info('CORPORATE_ACTION %s factor=%.10f entry=%.6f' %
                     (symbol, factor, state['entry']))
    g.adjustment_anchor[symbol] = {
        'date': str(frame.index[-1].date()), 'close': float(frame['close'].iloc[-1])}
    return True


def before_trading(context):
    today = get_datetime().date()
    g.order_locks = {}
    g.order_intent = {}
    g.early_events = {}
    g.seen_fills = {}
    g.daily_buy_value = g.daily_sell_value = 0.0
    g.pending = []
    g.exit_prices = {}
    g.buy_done_date = None
    benchmark = history(['000688.SH'], ['close'], 5, '1d', False, 'pre', True, False)
    b = _past(benchmark.get('000688.SH'), today)
    if b is None or b.empty:
        raise ValueError('Missing previous trading date; no frozen-universe fallback')
    g.signal_date = b.index[-1].date()
    securities = get_all_securities('stock', g.signal_date.strftime('%Y%m%d'))
    universe = set(s for s in securities.index if s.startswith('688') and s.endswith('.SH'))
    if not universe:
        raise ValueError('Historical STAR universe unavailable')
    # Holdings stay in risk management even if removed from the eligible universe.
    symbols = sorted(universe | set(context.portfolio.positions.keys()))
    fields = ['open', 'high', 'low', 'close', 'volume', 'turnover',
              'turnover_rate', 'quote_rate', 'is_st']
    rows = []
    for begin in range(0, len(symbols), 300):
        batch = symbols[begin:begin + 300]
        data = history(batch, fields, 121, '1d', False, 'pre', True, False)
        for symbol in batch:
            frame = _past(data.get(symbol), today)
            if frame is None or frame.empty:
                log.warn('MISSING_HISTORY %s holding retained' % symbol)
                continue
            adjusted = _adjust_entry(symbol, frame)
            if frame.index[-1].date() != g.signal_date:
                continue
            if adjusted:
                g.exit_prices[symbol] = float(frame['close'].iloc[-1])
            if symbol not in universe:
                continue
            values = _last_features(frame)
            if values is not None:
                rows.append((symbol, values))
    if rows:
        values = [r[1] for r in rows]
        p = _batch_probabilities(g.model, values)
        stop = _batch_probabilities(g.stop_model, values)
        scores = [(rows[i][0], float(p[i]), float(p[i] - .22 * stop[i]))
                  for i in range(len(rows)) if p[i] >= SIGNAL_THRESHOLD and stop[i] <= .50]
        scores.sort(key=lambda r: (-r[2], r[0]))
        g.pending = [(r[0], r[1]) for r in scores[:g.model['top_per_day']]]
    log.info('SIGNAL_AUDIT asof=%s callback=%s universe=%d scored=%d pending=%s' %
             (str(g.signal_date), str(get_datetime()), len(universe), len(rows), str(g.pending)))


def _place(symbol, action, target):
    if symbol in g.order_locks:
        return None
    g.order_locks[symbol] = 'SUBMITTING'
    g.submitting = True
    try:
        oid = order_target_percent(symbol, .10) if action == 'BUY' else order_target(symbol, int(target))
    except Exception:
        g.order_locks.pop(symbol, None)
        raise
    finally:
        g.submitting = False
    if oid is None:
        g.order_locks.pop(symbol, None)
        return None
    g.order_intent[oid] = {'symbol': symbol, 'action': action}
    g.order_locks[symbol] = oid
    # Snapshot callbacks that arrived inside the order API, then replay in order.
    for event in g.early_events.pop(oid, []):
        _process_order(event)
    return oid


def on_order(context, odr):
    event = {'id': odr.order_id, 'status': str(odr.status).upper(),
             'filled': float(odr.filled_amount), 'price': float(odr.avg_price)}
    if event['id'] not in g.order_intent:
        if g.submitting:
            g.early_events.setdefault(event['id'], []).append(event)
        return
    _process_order(event)


def _process_order(event):
    oid = event['id']
    intent = g.order_intent.get(oid)
    if intent is None:
        return
    symbol, action = intent['symbol'], intent['action']
    qty, price = event['filled'], event['price']
    old_qty, old_value = g.seen_fills.get(oid, (0.0, 0.0))
    if qty >= old_qty and qty > 0 and np.isfinite(price) and price > 0:
        # Cumulative average price can change: delta(value), not delta(qty)*new_avg.
        value = qty * price
        delta = value - old_value
        if action == 'BUY':
            g.daily_buy_value += delta
            g.position_state[symbol] = {'entry': price, 'half': False,
                                         'entry_date': get_datetime().date()}
        else:
            g.daily_sell_value += delta
            if action == 'TPHALF' and qty > old_qty and symbol in g.position_state:
                g.position_state[symbol]['half'] = True
        g.seen_fills[oid] = (qty, value)
    status = event['status']
    terminal = ('REJECT' in status or 'CANCEL' in status or
                ('FILLED' in status and 'PART' not in status))
    log.info('ORDER_AUDIT id=%s symbol=%s action=%s status=%s qty=%s avg=%s time=%s' %
             (str(oid), symbol, action, status, str(qty), str(price), str(get_datetime())))
    if terminal:
        g.order_intent.pop(oid, None)
        g.order_locks.pop(symbol, None)


def _exit_action(price, state, amount, today, position_days):
    entry = state['entry']
    if entry <= 0 or not np.isfinite(price):
        return None
    start = state['entry_date']
    age = (today - start).days if start is not None else int(position_days)
    gain = price / entry - 1
    if gain <= -.07:
        return 'STOP', 0
    if gain >= .34:
        return 'TPALL', 0
    # Hard expiry takes precedence over partial take-profit, including 200-399 shares.
    if age >= 60:
        return 'TIME60', 0
    if age >= 30 and gain < .10:
        return 'TIME30', 0
    target = int(amount / 2)
    if gain >= .24 and not state['half'] and target >= 200 and int(amount) - target >= 200:
        return 'TPHALF', target
    return None


def _open_tradable(symbol, bars):
    try:
        bar = bars[symbol]
    except KeyError:
        return False, False, False, np.nan
    price = float(bar.open)
    valid = not bool(bar.is_paused) and np.isfinite(price) and price > 0
    return valid, price >= float(bar.high_limit) - .001, price <= float(bar.low_limit) + .001, price


def handle_bar(context, bar_dict):
    today = get_datetime().date()
    if g.buy_done_date == today:
        return
    g.buy_done_date = today
    positions = context.portfolio.positions
    for symbol in list(g.position_state):
        if symbol not in positions or float(positions[symbol].amount) <= 0:
            g.position_state.pop(symbol, None)
    # Keep legacy buy-before-sell order for a controlled comparison.
    slots = max(0, g.model['max_positions'] - sum(float(p.amount) > 0 for p in positions.values()))
    for symbol, probability in g.pending:
        if slots <= 0:
            break
        if symbol in positions and float(positions[symbol].amount) > 0:
            continue
        valid, up, _, price = _open_tradable(symbol, bar_dict)
        if not valid or up or float(context.portfolio.stock_account.available_cash) < price * 200 * 1.005:
            continue
        if _place(symbol, 'BUY', None) is not None:
            slots -= 1
    for symbol in list(positions):
        pos = positions[symbol]
        if float(pos.amount) <= 0 or int(pos.position_days) <= 0:
            continue
        if symbol not in g.position_state:
            # Restart recovery cannot reconstruct original execution date from holding days.
            log.warn('RECOVERED_POSITION %s: entry date unknown; using platform holding days' % symbol)
            g.position_state[symbol] = {'entry': float(pos.cost_basis), 'half': False, 'entry_date': None}
        state = g.position_state[symbol]
        if state['entry_date'] == today or symbol not in g.exit_prices:
            continue
        valid, _, down, price = _open_tradable(symbol, bar_dict)
        if not valid or down:
            continue
        decision = _exit_action(g.exit_prices[symbol], state, pos.amount, today, pos.position_days)
        if decision is not None:
            log.info('EXIT_SIGNAL %s asof=%s signal_price=%.6f entry=%.6f open=%.6f action=%s' %
                     (symbol, str(g.signal_date), g.exit_prices[symbol], state['entry'], price, decision[0]))
            _place(symbol, decision[0], decision[1])


def after_trading(context):
    total = float(context.portfolio.stock_account.total_value)
    gross = g.daily_buy_value + g.daily_sell_value
    log.info('EXECUTION_AUDIT buy=%.2f sell=%.2f gross=%.2f nav=%.2f turnover=%.6f open_intents=%d' %
             (g.daily_buy_value, g.daily_sell_value, gross, total,
              gross / total if total > 0 else np.nan, len(g.order_intent)))
