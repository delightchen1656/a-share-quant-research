"""Run shipped feature code on local raw inputs; no parameter fitting."""
import ast,json
import numpy as np
import pandas as pd
import group_research as g
from align_platform_exports import OUT

tree=ast.parse((g.HERE/'supermind_mainboard_baseline_2_pending1.py').read_text(encoding='utf-8'))
names=['_rank01','_dividend_quality','_features','_rank_candidates']
ns={'np':np,'pd':pd,'MIN_LISTING_BARS':250,'MIN_AMOUNT20':50000000.,'MIN_VOL20':.004,'MAX_VOL20':.08}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'adapter','exec'),ns)
f=g.features();old=f[f.execute_date==pd.Timestamp('2020-01-02')];rows=[]
for s in sorted(g.bt.load_universe()):
 if not g.bt.raw_path(s).exists() or not g.bt.qfq_path(s).exists():continue
 raw=pd.read_parquet(g.bt.raw_path(s));adj=pd.read_parquet(g.bt.qfq_path(s))
 frames=[]
 for z in [raw,adj]:
  z['date']=pd.to_datetime(z.date);z=z[(z.date<=pd.Timestamp('2019-12-31'))&(z.tradestatus.astype(str)=='1')].sort_values('date').tail(751).set_index('date')
  frames.append(z.rename(columns={'amount':'turnover','isST':'is_st'}))
 ft=ns['_features'](frames[1],frames[0])
 if ft is not None:rows.append(dict(symbol=s,**ft))
x=pd.DataFrame(rows);rank=ns['_rank_candidates'](x,True)
comp=x.merge(old,on='symbol',suffixes=('_adapter','_cached'))
fields=['amount20','near_high','below_high','below_ma60','dividend','downside']
diff={c:float((comp[c+'_adapter']-comp[c+'_cached']).abs().max()) for c in fields}
out={'date':'2020-01-02','platform_eligible_from_log':1351,'local_adapter_eligible':len(x),'local_cache_eligible':len(old),'cached_vs_adapter_max_abs_factor_difference':diff,'local_adapter_top8':rank.head(8).symbol.tolist(),'platform_top8_from_log':['603801.SH','603600.SH','603730.SH','603608.SH','601222.SH','600395.SH','600377.SH','603167.SH']}
(OUT/'feature_input_diagnostic.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print(json.dumps(out,indent=2))
