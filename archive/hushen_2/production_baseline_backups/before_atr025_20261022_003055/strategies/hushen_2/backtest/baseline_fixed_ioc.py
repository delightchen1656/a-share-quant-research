"""Auditable baseline adapters: fixed shares, manual expiry, and filled-only slots."""
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import types

POLICY_PATH=Path(__file__).with_name('BASELINE_FIXED_IOC_PROTOCOL.json')


def fixed_ioc_engine(core, manual_expiry_open=True, filled_slots=False):
    @dataclass
    class FixedPending(core.Pending):
        quantity:int=0
    engine=types.ModuleType('baseline_fixed_ioc_engine');engine.__dict__.update(vars(core));engine.Pending=FixedPending
    engine.pending_priority=pending_priority
    source=inspect.getsource(core.simulate)
    replacements=[
        ('trades: list[dict] = []','trades: list[dict] = []\n    fixed_order_attempts = []'),
        ('budget=budget,','budget=budget,\n                quantity=int(budget // ((float(row["close"]) * (1.0 - entry_offset * float(row["atr_pct"]))) * (1.0 + slip) * 100)) * 100,'),
        ('shares = int(affordable // (buy_price * 100)) * 100',
         'attempt = dict(symbol=p.symbol, signal_date=str(p.signal_date.date()), date=str(date.date()), requested_quantity=p.quantity, filled_quantity=0, status="no_fill_remainder_cancelled")\n            fixed_order_attempts.append(attempt)\n            shares = p.quantity\n            if shares * buy_price + commission(shares * buy_price, comm_rate, comm_min) > cash + 1e-9:\n                attempt["status"] = "insufficient_cash_rejected"\n                cash_limited_orders += 1\n                continue'),
        ('while shares >= 100 and cost > cash + 1e-9:\n                shares -= 100\n                gross = shares * buy_price\n                fee = commission(gross, comm_rate, comm_min) if shares else 0.0\n                cost = gross + fee',
         'if cost > cash + 1e-9:\n                attempt["status"] = "insufficient_cash_rejected"\n                cash_limited_orders += 1\n                continue'),
        ('cash -= cost','attempt["filled_quantity"] = shares\n            attempt["status"] = "filled" if shares == p.quantity else "partial_remainder_cancelled"\n            cash -= cost'),
        ('return result, t if keep_trades else pd.DataFrame()',
         'result["fixed_order_attempts"] = fixed_order_attempts\n    return result, t if keep_trades else pd.DataFrame()')]
    if manual_expiry_open:
        replacements.append((
            'if stop_hit:\n                reason = "stop"\n                base = min(opn, h.stop_price)\n            elif take_hit:\n                reason = "take"\n                base = max(opn, h.take_price)\n            elif date >= h.expiry_session:\n                reason = "expiry"\n                base = close',
            'if date > h.expiry_session:\n                # Manual exit is due at this session open, before intraday triggers.\n                reason = "expiry"\n                base = opn\n            elif stop_hit:\n                reason = "stop"\n                base = min(opn, h.stop_price)\n            elif take_hit:\n                reason = "take"\n                base = max(opn, h.take_price)'))
    if filled_slots:
        # Only these additional declared changes implement the new occupancy policy.
        quantity_before=replacements[1][1]
        replacements[1]=(replacements[1][0],quantity_before.replace(' * (1.0 + slip)', ''))
        before,after=replacements[2]
        replacements[2]=(before,after.replace('fixed_order_attempts.append(attempt)',
            'attempt.update(cash_before=cash, occupied_slots_before=filled_slots_today, trigger_phase="open" if float(bar["open"]) <= p.target else "intraday_order_unknown", priority_policy="date_open_then_signal_date_score_symbol")\n            fixed_order_attempts.append(attempt)'))
        replacements.extend([
            ('# Exit decisions occur before buy fills; proceeds become reusable next session.',
             '# Sold slots, like proceeds, become reusable next session (no unknown intraday ordering).\n        filled_slots_today = len(holdings)'),
            ('for p in pending:', 'for p in sorted(pending, key=lambda order: pending_priority(order, by_symbol, date)):'),
            ('shares = p.quantity\n            if shares * buy_price',
             'shares = p.quantity\n            if filled_slots_today >= slots:\n                attempt["status"] = "no_slot_rejected"\n                continue\n            if shares * buy_price'),
            ('filled_orders += 1', 'filled_orders += 1\n            filled_slots_today += 1'),
            ('free_slots = slots - len(pending) - len(holdings)', 'free_slots = slots - len(holdings)'),
            ('if free_slots <= 0:\n                skipped_no_free_slot += 1\n                continue',
             '# Pending orders do not occupy slots; eligibility is checked on trigger.'),
            ('free_slots -= 1', '# No slot is consumed until an actual fill.'),
            ('occupied_now = len(pending) + len(holdings)', 'occupied_now = len(holdings)'),
        ])
    for before,after in replacements:
        assert source.count(before)==1,('Frozen baseline changed; refusing broad patch',before)
        source=source.replace(before,after)
    exec(compile(source,'<baseline_fixed_quantity_ioc_only>','exec'),engine.__dict__)
    engine.adapted_source=source;engine.minimal_replacements=replacements
    engine.policy=json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    if not manual_expiry_open:
        engine.policy=dict(engine.policy, version='legacy-fixed-ioc-expiry-close', expiry_exit='Original expiry session close')
    if filled_slots:
        engine.policy=json.loads(Path(__file__).with_name('FILLED_SLOT_PROTOCOL.json').read_text(encoding='utf-8'))
        engine.policy=dict(engine.policy,manual_expiry_open=manual_expiry_open)
    return engine


def pending_priority(order,by_symbol,date):
    """No intraday path invented: known open triggers precede unresolved daily touches."""
    bars=by_symbol.get(order.symbol)
    at_open=False
    if bars is not None and date in bars.index:
        bar=bars.loc[date]
        at_open=float(bar['open'])<=order.target
    return (0 if at_open else 1,order.signal_date,-order.score,order.symbol)
