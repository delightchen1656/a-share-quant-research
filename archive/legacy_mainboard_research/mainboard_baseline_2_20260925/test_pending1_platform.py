import ast,json
from types import SimpleNamespace as NS
import numpy as np
import pandas as pd
import group_research as g
from group_round3 import prepare

path=g.HERE/'supermind_mainboard_baseline_2_pending1.py'
tree=ast.parse(path.read_text(encoding='utf-8'))
names=['_rank01','_rank_candidates','_group_features','_trade_state','handle_bar']
scope={'np':np,'pd':pd}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),str(path),'exec'),scope)
f=g.features();ranks,_,states,_=prepare(f,[dict(name='control',family='control',value=0)])
for state in states:
 d=state['execute_date'];frame=f[f.execute_date==d]
 actual=scope['_rank_candidates'](frame,state['bull'])
 expected=ranks['control'][d]
 assert actual.head(24).symbol.tolist()==expected.head(24).symbol.tolist(),str(d)
 assert np.allclose(actual.head(24).score,expected.head(24).score),str(d)
raw=pd.DataFrame({'close':[10.]*20,'volume':[100000.]*20,'turnover_rate':[1.]*20})
assert scope['_group_features'](raw)=={'float_cap_proxy':100000000.,'turn20':1.}
assert scope['_group_features'](raw.drop(columns='turnover_rate')) is None
orders=[]
scope.update(g=NS(rebalance_pending=True,targets={'A':.1,'B':0.},submitted_date=None),get_datetime=lambda:pd.Timestamp('2026-01-05'),order_target_percent=lambda s,w:orders.append((s,w)),log=NS(info=lambda _:None))
context=NS(portfolio=NS(positions={'A':NS(amount=100.),'B':NS(amount=100.)},stock_account=NS(total_value=100000.)))
bars={'A':NS(open=11.,volume=10000.,is_paused=False,high_limit=11.,low_limit=9.),'B':NS(open=9.,volume=10000.,is_paused=False,high_limit=11.,low_limit=9.)}
scope['handle_bar'](context,bars);assert orders==[],orders
scope['g'].rebalance_pending=True;scope['g'].submitted_date=None
bars['A'].open=10.;bars['B'].open=10.
scope['handle_bar'](context,bars);assert orders==[('A',.1),('B',0.)],orders
result={'syntax':'passed','quarterly_top24_and_scores_matched':len(states),'group_proxy':'passed','missing_field':'passed','directional_price_limits':'passed','platform_execution':'not_run'}
(g.HERE/'pending1_platform_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(result)
