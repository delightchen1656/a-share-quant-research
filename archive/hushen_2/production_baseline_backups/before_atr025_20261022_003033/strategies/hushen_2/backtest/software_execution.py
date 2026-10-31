"""Isolated historical execution adapter for current tracker quotes; never changes production.

User acceptance and broker fills are assumptions. Price/capacity/fees remain the registered
daily-bar approximation, while quantity and protection quotes use actual software expressions.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
import inspect
from pathlib import Path
import sys
import types

TRACKER=Path(__file__).resolve().parents[1]/'tracker'

def expression(path,function,target):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    parent=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==function)
    for node in ast.walk(parent):
        if not isinstance(node,ast.Assign):continue
        t=node.targets[0]
        if isinstance(t,ast.Name) and t.id==target:return ast.Expression(node.value)
        if isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant) and t.slice.value==target:
            return ast.Expression(node.value)
    raise ValueError((path,function,target))

BUDGET=expression(TRACKER/'service.py','snapshot','budget')
QUANTITY=expression(TRACKER/'service.py','snapshot','qty')
TAKE=expression(TRACKER/'store.py','state','take')
STOP=expression(TRACKER/'store.py','state','stop')
CODE={n:compile(e,'<actual_tracker_expression>','eval') for n,e in [('budget',BUDGET),('quantity',QUANTITY),('take',TAKE),('stop',STOP)]}

def software_order_parameters(equity,cash,deferred,pending,target):
    reserved=sum(p.quantity*p.target+5 for p in pending)
    state={'available':round(max(0,round(cash,2)-reserved),2),'deferred':round(deferred,2)}
    budget=eval(CODE['budget'],{},dict(equity=equity,state=state))
    quantity=eval(CODE['quantity'],{},dict(budget=budget,s={'trigger':target}))
    return budget,quantity

def software_take_price(price,atr):return eval(CODE['take'],{},dict(p={'average_price':price,'atr':atr}))
def software_stop_price(price,atr):return eval(CODE['stop'],{},dict(p={'average_price':price,'atr':atr}))

def adapted_engine(core):
    @dataclass
    class FixedQuantityPending(core.Pending):
        quantity:int=0
    module=types.ModuleType('hushen2_current_software_simulator');module.__dict__.update(vars(core))
    module.Pending=FixedQuantityPending
    module.software_order_parameters=software_order_parameters
    module.software_take_price=software_take_price;module.software_stop_price=software_stop_price
    source=inspect.getsource(core.simulate)
    replacements=[
      ('shares = int(affordable // (buy_price * 100)) * 100',
       'shares = min(p.quantity, int(cash // (buy_price * 100)) * 100)'),
      ('take_price=buy_price * (1.0 + take_mult * atr),','take_price=software_take_price(buy_price, atr),'),
      ('stop_price=buy_price * (1.0 - stop_mult * atr),','stop_price=software_stop_price(buy_price, atr),'),
      ('h.take_price /= factor_value','h.take_price = software_take_price(h.entry_notional / h.shares, h.atr_pct)'),
      ('h.stop_price /= factor_value','h.stop_price = software_stop_price(h.entry_notional / h.shares, h.atr_pct)'),
      ('equity = mark_equity(cash, deferred_cash, holdings, by_symbol, date, sum(x[1] for x in receivables))\n            budget = max(0.0, equity / slots)',
       'equity = mark_equity(round(cash, 2), round(deferred_cash, 2), holdings, by_symbol, date)\n            budget, order_quantity = software_order_parameters(equity, cash, deferred_cash, pending, float(row["close"]))\n            if order_quantity < 100:\n                below_100_share_orders += 1\n                continue'),
      ('budget=budget,','budget=budget,\n            quantity=order_quantity,'),
      ('pending = still_pending',
       'expired_entries += sum(p.expiry_date <= date for p in still_pending)\n        pending = [p for p in still_pending if p.expiry_date > date]'),
      ('return result, t if keep_trades else pd.DataFrame()',
       'result["terminal_positions"] = [{"symbol": h.symbol, "entry_date": str(h.entry_date.date()), "quantity": h.shares, "deadline": str(h.deadline.date()), "frozen": h.frozen} for h in holdings]\n    result["terminal_orders"] = [{"symbol": p.symbol, "signal_date": str(p.signal_date.date()), "quantity": p.quantity} for p in pending]\n    return result, t if keep_trades else pd.DataFrame()')]
    for before,after in replacements:
        assert source.count(before)==1,('Frozen source no longer matches adapter',before)
        source=source.replace(before,after)
    exec(compile(source,'<isolated_software_execution>','exec'),module.__dict__)
    module.adapted_source=source
    module.quote_expressions={k:ast.unparse(v) for k,v in [('budget',BUDGET),('quantity',QUANTITY),('take',TAKE),('stop',STOP)]}
    return module
