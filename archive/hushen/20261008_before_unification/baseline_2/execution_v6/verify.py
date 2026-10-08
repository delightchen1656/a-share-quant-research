"""Execution regression fixtures: synthetic data, not return evidence."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pandas as pd
import local_backtest as lb

HERE = Path(__file__).resolve().parent
D = pd.Timestamp('2026-10-08')
S = '603325.SH'

def account(volume20=10000000):
    a = lb.Account(D, {}, {D: {}}, {})
    a.date, a.day = D, {}
    a.m.g.alpha_ready = True
    a.m.g.alpha_index = 100
    a.m.g.alpha_last_data = '2026-09-30'
    a.m.g.alpha_ranks = [S]
    a.m.g.alpha_info = {S: dict(volume20=volume20, previous_st=False)}
    return a

def bar(a, minute, price=10., volume=100000, low=None, high=None):
    a.now = D + pd.Timedelta(hours=9, minutes=minute)
    b = NS(datetime=a.now, open=price, close=price, low=price if low is None else low,
           high=price if high is None else high, volume=volume,
           high_limit=11., low_limit=9., is_st=False, is_paused=False)
    a.bars = {S: b}
    return a.bars

def tick(a, minute, price=10., volume=100000, **kw):
    bars = bar(a, minute, price, volume, **kw)
    a.match(bars)
    a.m._handle_bar(a.context, bars)

def main():
    checks = {}
    old = ast.parse((HERE/'source_v5.py').read_text(encoding='utf-8-sig'))
    new = ast.parse(lb.ENTRY.read_text(encoding='utf-8'))
    def functions(t):
        return {n.name: ast.dump(n, include_attributes=False) for n in t.body if isinstance(n, ast.FunctionDef)}
    of, nf = functions(old), functions(new)
    checks['unchanged_factors_history_and_calendar'] = all(of[k] == nf[k] for k in
        ['compute_signals', '_before_trading', '_fetch', 'mainboard'])
    a = account()
    try:
        a.m._init(NS(run_info=NS(frequency='1d')))
        checks['reject_daily_frequency'] = False
    except ValueError:
        checks['reject_daily_frequency'] = True
    a = account()
    tick(a, 31)
    checks['no_same_bar_fill'] = not a.trades and len(a.orders) == 1
    a.m._handle_bar(a.context, a.bars)
    checks['duplicate_bar_no_extra_order'] = len(a.orders) == 1
    tick(a, 32)
    checks['buy_obeys_limit_cash_and_lot'] = bool(a.trades and all(t['price'] <= 10.01 and t['qty'] % 100 == 0 for t in a.trades) and a.cash >= 0)
    checks['t_plus_one'] = a.positions[S].available_amount == 0
    trade = NS(order_id='1', order_book_id=S, exec_id='1', side='BUY', last_price=10., last_quantity=1900, tax=0.)
    a.m.on_trade(a.context, trade)
    checks['duplicate_trade_receipt_dedup'] = len(a.m.g.exec_seen_trades) == 1
    old_order = copy.copy(a.orders['1'])
    old_order.status, old_order.filled_amount = 'ACTIVE', 0
    a.m.on_order(a.context, old_order)
    checks['out_of_order_callback_no_regression'] = a.m.g.exec_orders['1'].status == 'FILLED'
    a = account()
    tick(a, 31)
    for minute in range(32, 37):
        tick(a, minute, 10.05)
    checks['cancel_request_not_immediate_replace'] = len(a.orders) == 1 and a.orders['1'].status == 'PENDING_CANCEL'
    # The original order partially fills while cancellation is pending.
    tick(a, 37, 10., volume=400)
    checks['cancel_fill_race_recomputes_remaining'] = (a.orders['1'].filled_amount == 100 and
        a.orders['1'].status == 'CANCELLED' and a.orders['2'].amount == a.m.g.alpha_targets[S] - 100)
    a = account(volume20=40000)  # 200 shares total daily participation allowance.
    tick(a, 31)
    tick(a, 32, volume=400)
    tick(a, 33, volume=400)
    tick(a, 36)
    checks['daily_volume_cap_survives_multiple_ticks'] = sum(t['qty'] for t in a.trades) == 200 and len(a.orders) == 1
    checks['partial_fills_min_commission_once_per_order'] = sum(t['commission'] for t in a.trades) == 5.
    a = account()
    tick(a, 31)
    for minute in range(32, 39):
        tick(a, minute, 10.20)
    checks['chase_boundary_stops_new_orders'] = len(a.orders) == 1
    a = account()
    bars = bar(a, 31)
    bars[S].datetime -= pd.Timedelta(minutes=2)
    a.m._handle_bar(a.context, bars)
    checks['stale_quote_no_order'] = not a.orders
    a = account()
    tick(a, 31)
    a.now = D + pd.Timedelta(hours=10)
    a.bars[S].datetime = a.now
    a.m._handle_bar(a.context, a.bars)
    checks['window_end_requests_cancel'] = a.orders['1'].status == 'PENDING_CANCEL' and len(a.orders) == 1
    a.now += pd.Timedelta(minutes=1)
    a.match({})
    a.m._handle_bar(a.context, a.bars)
    checks['no_orders_after_window'] = len(a.orders) == 1 and a.orders['1'].status == 'CANCELLED'
    a = account()
    tick(a, 31)
    bad = NS(order_id='1', order_book_id=S, exec_id='bad', side='BUY', last_price=10.02, last_quantity=100, tax=0.)
    a.m.on_trade(a.context, bad)
    bad = NS(order_id='1', order_book_id=S, exec_id='tax', side='SELL', last_price=10., last_quantity=100, tax=1.)
    a.m.on_trade(a.context, bad)
    checks['limit_and_fee_mismatch_alerts'] = any('LIMIT_BREACH' in s for s in a.audit) and any('FEE_MISMATCH' in s for s in a.audit)
    a = account()
    bars = bar(a, 31, price=2.71)
    bars[S].low_limit, bars[S].high_limit = 2., 3.
    checks['low_price_tolerance_not_rounded_away'] = a.m._limit_price(bars[S], True) == 2.72
    a = account()
    old_symbol = '603312.SH'
    a.cash = 0.
    a.holdings[old_symbol] = dict(qty=1000, last=10., lots=[dict(q=1000, buy=D-pd.Timedelta(days=10), release=D-pd.Timedelta(days=9), div=0.)])
    a.m.g.alpha_managed.add(old_symbol)
    a.m.g.alpha_info[old_symbol] = dict(volume20=10000000, previous_st=False)
    a.sync()
    def two_bars(minute):
        bars = bar(a, minute)
        bars[old_symbol] = copy.copy(bars[S])
        a.match(bars)
        a.m._handle_bar(a.context, bars)
    two_bars(31)
    checks['no_use_of_unfilled_sale_proceeds'] = len(a.orders) == 1 and a.orders['1'].symbol == old_symbol
    two_bars(32)
    checks['buy_after_confirmed_sale'] = len(a.orders) == 2 and a.orders['2'].symbol == S and a.orders['1'].status == 'FILLED'
    two_bars(33)
    checks['async_sell_buy_cash_conservation'] = (a.cash >= 0 and len(a.trades) == 2 and
        abs(a.cash - (1000*10 - a.trades[0]['commission'] - a.trades[0]['transfer'] - a.trades[0]['stamp']
                      - a.trades[1]['qty']*a.trades[1]['price'] - a.trades[1]['commission'] - a.trades[1]['transfer'])) < 1e-6)
    a = account()
    tick(a, 31)
    a.orders['1'].status = 'CANCELLED'  # Simulate a lost end-of-day callback.
    a.date = D + pd.Timedelta(days=1)
    a.now = a.date + pd.Timedelta(hours=9, minutes=31)
    checks['lost_expiry_callback_reconciles_next_day'] = not a.m._refresh_orders() and a.m.g.exec_orders['1'].status == 'EXPIRED_ABSENT'
    lb.dump(HERE/'validation.json', checks)
    for name, passed in checks.items():
        print('PASS' if passed else 'FAIL', name)
    assert all(checks.values()), checks
    print('PASS', len(checks))

if __name__ == '__main__':
    main()
