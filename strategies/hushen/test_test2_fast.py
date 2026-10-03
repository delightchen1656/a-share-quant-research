"""Deterministic multi-session original/fast parity; no platform claims."""
from pathlib import Path
from types import SimpleNamespace as NS, ModuleType
import sys
import time
import json
import ast
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.modules['mindgo_api'] = ModuleType('mindgo_api')
calendar = pd.bdate_range('2018-01-01', periods=430)
symbols = ['600%03d.SH' % i for i in range(36)]
rng = np.random.RandomState(71)
quotes = {}
for i, s in enumerate(symbols):
    close = (5 + i / 3) * np.exp(np.cumsum(rng.normal(0.0003, .015, len(calendar))))
    prev = np.r_[close[0], close[:-1]]
    volume = rng.uniform(3e6, 8e6, len(calendar))
    quotes[s] = pd.DataFrame(dict(open=prev*np.exp(rng.normal(0, .007, len(calendar))),
        close=close, prev_close=prev, volume=volume, turnover=volume*close,
        turnover_rate=rng.uniform(.5, 3, len(calendar)), is_paused=0., is_st=0.), index=calendar)

def load(path):
    ns = {}
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), ns)
    ns['g'] = NS()
    ns['log'] = NS(info=lambda *a: None)
    for name in ('set_benchmark', 'set_commission', 'set_slippage', 'set_volume_limit', 'enable_open_bar'):
        ns[name] = lambda *a, **kw: None
    ns['PerShare'] = ns['PriceSlippage'] = lambda *a, **kw: None
    ns['get_open_orders'] = lambda: []
    account = NS(available_cash=100000., frozen_cash=0.)
    context = NS(portfolio=NS(positions={}, stock_account=account))
    ns['_init'](context)
    calls = []
    ns['_calls'] = calls
    def order(s, q, price):
        calls.append((s, q, price))
        # Leave some targets unfinished; execute at most 200 shares per call.
        q = int(np.sign(q) * min(abs(q), 200))
        p = context.portfolio.positions.get(s, NS(amount=0, available_amount=0, last_price=price))
        p.amount += q
        p.last_price = price
        account.available_cash -= q*price + max(5., abs(q*price)*.0003)
        if p.amount:
            context.portfolio.positions[s] = p
        else:
            context.portfolio.positions.pop(s, None)
        return len(calls)
    ns['order'] = order
    return ns, context

original = ROOT/'test2_reference/D11_v4_original.py'
fast = ROOT/'supermind_test2_D11_fast_daily.py'
# Critical execution and signal math must remain byte-for-byte AST equivalent.
def functions(path):
    return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
a, b = functions(original), functions(fast)
for name in ('compute_signals', '_handle_bar', '_submit', '_limit_price', '_buy_cost'):
    assert a[name] == b[name], name
states = [load(original), load(fast)]
elapsed = [0., 0.]
ranking_checks = 0
history_calls = [0, 0]
for t in range(330, 395):
    day = calendar[t]
    # Dynamic universe plus ST, suspension, and share-change cases.
    quotes[symbols[0]].loc[calendar[350]:, 'is_st'] = 1.
    quotes[symbols[1]].loc[calendar[353]:calendar[355], 'is_paused'] = 1.
    def universe(date):
        d = pd.Timestamp(date)
        names = symbols[:-1] if d < calendar[347] else symbols
        return pd.DataFrame(index=names)
    bars = {s: NS(open=float(x.loc[day, 'open']), high_limit=float(x.loc[day,'prev_close']*1.1),
        low_limit=float(x.loc[day,'prev_close']*.9), is_paused=bool(x.loc[day,'is_paused']),
        is_st=bool(x.loc[day,'is_st'])) for s, x in quotes.items()}
    for idx, (ns, ctx) in enumerate(states):
        ns['get_datetime'] = lambda: day
        ns['get_trade_days'] = lambda **kw: calendar[calendar <= day]
        ns['get_all_securities'] = lambda kind, date: universe(date)
        def history(group, fields, count, *args):
            history_calls[idx] += 1
            return {s: quotes[s].loc[quotes[s].index < day, fields].tail(count).copy() for s in group}
        ns['history'] = history
        for pos in ctx.portfolio.positions.values():
            pos.available_amount = pos.amount
        if t == 361 and ctx.portfolio.positions:
            s = sorted(ctx.portfolio.positions)[0]
            ctx.portfolio.positions[s].amount *= 2
            ctx.portfolio.positions[s].available_amount *= 2
        tick = time.perf_counter()
        ns['_before_trading'](ctx)
        elapsed[idx] += time.perf_counter() - tick
    left, right = [ns['g'] for ns, ctx in states]
    rebalance = left.alpha_first or (left.alpha_index - 1) % states[0][0]['INTERVAL'] == 0
    if rebalance:
        assert left.alpha_ranks == right.alpha_ranks
        ranking_checks += 1
    for s, info in right.alpha_info.items():
        assert info == left.alpha_info[s], (day, s)
    for ns, ctx in states:
        ns['_handle_bar'](ctx, bars)
        ns['_after_trading'](ctx)
    assert left.alpha_targets == right.alpha_targets, day
    assert states[0][0]['_calls'] == states[1][0]['_calls'], day
    assert states[0][1].portfolio.stock_account.available_cash == states[1][1].portfolio.stock_account.available_cash
assert history_calls[0] == history_calls[1]
result = dict(sessions=65, symbols=36, ranking_checks=ranking_checks,
    order_requests=len(states[0][0]['_calls']), parity='PASS',
    before_trading_seconds_original=elapsed[0], before_trading_seconds_fast=elapsed[1],
    history_calls_each=history_calls[0],
    caveat='Synthetic local API mock, not SuperMind fills or platform timing. No full-market outage parity on non-rebalance days.')
(ROOT/'test2_reference/validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
