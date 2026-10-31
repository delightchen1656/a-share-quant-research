"""Fixed-quantity IOC daily proxy. No broker calls and no changes to frozen engine."""
import json
from pathlib import Path
from software_execution import adapted_engine

POLICY_PATH=Path(__file__).with_name('BROKER_EXECUTION.json')


def one_price_limit_up(bar):
    # Conservative blocking proxy for the strategy's ordinary mainboard universe.
    # It does not assert actual queue position or cover every special limit regime.
    prior=float(bar['preclose'])
    return prior>0 and abs(float(bar['high'])-float(bar['low']))<1e-9 and float(bar['close'])/prior-1>=.095


def broker_engine(core):
    engine=adapted_engine(core)
    policy=json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    assert policy['order_type']=='five_best_immediate_or_cancel'
    engine.one_price_limit_up=one_price_limit_up
    source=engine.adapted_source
    replacements=[
        ('trades: list[dict] = []','trades: list[dict] = []\n    ioc_attempts = []'),
        ('base = min(float(bar["open"]), p.target)',
         'attempt = dict(side="buy", symbol=p.symbol, signal_date=str(p.signal_date.date()), date=str(date.date()), requested_quantity=p.quantity, filled_quantity=0, status="triggered")\n            ioc_attempts.append(attempt)\n            if one_price_limit_up(bar):\n                attempt["status"] = "one_price_limit_up_no_fill"\n                continue\n            base = min(float(bar["open"]), p.target)'),
        ('shares = min(p.quantity, int(cash // (buy_price * 100)) * 100)',
         'shares = p.quantity\n            if shares * buy_price + commission(shares * buy_price, comm_rate, comm_min) > cash + 1e-9:\n                attempt["status"] = "insufficient_cash_rejected"\n                cash_limited_orders += 1\n                continue'),
        ('if shares < 100:\n                below_100_share_orders += 1\n                continue\n            gross = shares * buy_price',
         'if shares < 100:\n                below_100_share_orders += 1\n                attempt["status"] = "ioc_no_fill_remainder_cancelled"\n                continue\n            gross = shares * buy_price'),
        ('while shares >= 100 and cost > cash + 1e-9:\n                shares -= 100\n                gross = shares * buy_price\n                fee = commission(gross, comm_rate, comm_min) if shares else 0.0\n                cost = gross + fee',
         'if cost > cash + 1e-9:\n                attempt["status"] = "insufficient_cash_rejected"\n                cash_limited_orders += 1\n                continue'),
        ('cash -= cost',
         'attempt["filled_quantity"] = shares\n            attempt["status"] = "filled" if shares == p.quantity else "partial_remainder_cancelled"\n            cash -= cost'),
        ('if is_one_price_limit_down(bar):',
         'attempt = dict(side="sell", symbol=h.symbol, signal_date=str(h.signal_date.date()), date=str(date.date()), requested_quantity=h.shares, filled_quantity=0, status="triggered")\n            ioc_attempts.append(attempt)\n            if is_one_price_limit_down(bar):\n                attempt["status"] = "one_price_limit_down_no_fill"'),
        ('sell_price = max(0.01, base * (1.0 - slip))\n            gross = h.shares * sell_price',
         'sell_price = min(high, max(low, max(0.01, base * (1.0 - slip))))\n            old_position = (h.shares, h.entry_cost, h.entry_notional, h.dividends)\n            capacity = int((float(bar["volume"]) * 0.02) // 100) * 100\n            sold = min(h.shares, capacity)\n            if sold <= 0:\n                attempt["status"] = "ioc_no_fill_rearm_next_evening"\n                survivors.append(h)\n                continue\n            attempt["filled_quantity"] = sold\n            attempt["status"] = "filled" if sold == h.shares else "partial_remainder_cancelled_rearm_next_evening"\n            fraction = sold / h.shares\n            h.shares = sold\n            h.entry_cost *= fraction\n            h.entry_notional *= fraction\n            h.dividends *= fraction\n            gross = h.shares * sell_price'),
        ('})\n        holdings = survivors',
         '})\n            if sold < old_position[0]:\n                h.shares = old_position[0] - sold\n                h.entry_cost = old_position[1] * (1 - fraction)\n                h.entry_notional = old_position[2] * (1 - fraction)\n                h.dividends = old_position[3] * (1 - fraction)\n                survivors.append(h)\n        holdings = survivors'),
        ('return result, t if keep_trades else pd.DataFrame()',
         'result["ioc_attempts"] = ioc_attempts\n    result["broker_policy"] = BROKER_POLICY\n    return result, t if keep_trades else pd.DataFrame()')]
    for before,after in replacements:
        assert source.count(before)==1,('Software source no longer matches broker adapter',before)
        source=source.replace(before,after)
    engine.BROKER_POLICY=policy
    exec(compile(source,'<isolated_broker_ioc_execution>','exec'),engine.__dict__)
    engine.adapted_source=source
    engine.broker_policy=policy
    return engine
