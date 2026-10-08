"""Calendar boundaries and actual daily callbacks with synthetic partial fills."""
from pathlib import Path
import ast,json
HERE=Path(__file__).resolve().parent
parent=HERE.parent
# Reuse only the established mock setup/functions, not its tests or file writes.
harness=(parent/'test_test2_fast.py').read_text(encoding='utf-8').split('original = ROOT/')[0]
ns={'__file__':str(parent/'test_test2_fast.py')};exec(compile(harness,'mock_setup','exec'),ns)
model,context=ns['load'](parent/'supermind_test2_D11_fast_weekly.py')
pd=ns['pd'];NS=ns['NS'];calendar=ns['calendar'];quotes=ns['quotes'];symbols=ns['symbols']
schedule=model['_weekly_rebalance_due']
cases=[('2026-10-12','2026-10-09',False,True),('2026-10-13','2026-10-12',False,False),
       ('2026-02-24','2026-02-13',False,True),('2026-01-05','2025-12-31',False,True),
       ('2025-01-02','2024-12-31',False,False),('2026-10-14','2026-10-13',True,True),
       ('2026-10-15','2026-10-14',False,False)]
for today,prior,first,expected in cases:assert schedule(today,prior,first)==expected
try:schedule('2026-10-12','2026-10-12',False);raise AssertionError('Invalid previous session accepted')
except ValueError:pass
def funcs(code):return {n.name:ast.dump(n) for n in ast.parse(code).body if isinstance(n,ast.FunctionDef)}
source=(HERE/'uploaded_source.py').read_text(encoding='utf-8');weekly=(parent/'supermind_test2_D11_fast_weekly.py').read_text(encoding='utf-8')
a,b=funcs(source),funcs(weekly)
for name in a:
    if name not in ('_init','_before_trading','_handle_bar'):assert a[name]==b[name],name
old='    rebalance = g.alpha_first or (g.alpha_index - 1) % INTERVAL == 0'
normalized=weekly.replace('    g.alpha_rebalance_due = _weekly_rebalance_due(today, prior[-1], g.alpha_first)\n    rebalance = g.alpha_rebalance_due',old,1)
normalized=normalized.replace('    rebalance = g.alpha_rebalance_due',old,1)
for name in ('_before_trading','_handle_bar'):assert funcs(normalized)[name]==a[name]
signal_calls=[];original_signal=model['compute_signals']
def traced(*args):signal_calls.append(day);return original_signal(*args)
model['compute_signals']=traced
rebalances=[];retry_days=0;previous_week=None
for t in range(332,397):
    day=calendar[t]
    quotes[symbols[0]].loc[calendar[350]:,'is_st']=1.
    quotes[symbols[1]].loc[calendar[353]:calendar[355],'is_paused']=1.
    model['get_datetime']=lambda:day
    model['get_trade_days']=lambda **kw:calendar[calendar<=day]
    model['get_all_securities']=lambda kind,date:pd.DataFrame(index=symbols)
    model['history']=lambda group,fields,count,*args:{s:quotes[s].loc[quotes[s].index<day,fields].tail(count).copy() for s in group}
    bars={s:NS(open=float(x.loc[day,'open']),high_limit=float(x.loc[day,'prev_close']*1.1),low_limit=float(x.loc[day,'prev_close']*.9),is_paused=bool(x.loc[day,'is_paused']),is_st=bool(x.loc[day,'is_st'])) for s,x in quotes.items()}
    for pos in context.portfolio.positions.values():pos.available_amount=pos.amount
    model['_before_trading'](context)
    week=day-pd.Timedelta(days=day.weekday());expected=previous_week is None or week!=previous_week
    assert model['g'].alpha_rebalance_due==expected,(day,expected)
    before=len(model['_calls']);model['_handle_bar'](context,bars);after=len(model['_calls'])
    model['_handle_bar'](context,bars);assert len(model['_calls'])==after
    if expected:rebalances.append(str(day.date()))
    elif after>before:retry_days+=1
    model['_after_trading'](context);previous_week=week
assert len(signal_calls)==len(rebalances)>10
assert retry_days>0
result=dict(calendar_cases=len(cases),invalid_previous_session_rejected=True,unchanged_factor_and_order_functions=True,
    only_schedule_changed_in_callbacks=True,sessions=65,rebalance_dates=rebalances,full_ranking_calls=len(signal_calls),
    non_rebalance_order_days=retry_days,order_requests=len(model['_calls']),duplicate_callback_orders_prevented=True,
    note='Synthetic local callback tests only. No platform backtest or return claim.')
(HERE/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
