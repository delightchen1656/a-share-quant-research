"""First-signal diagnostics only; do not optimize precision to force platform fit."""
import ast,json
import numpy as np
import pandas as pd
import group_research as g
from approximate_parity_gate import OUT

tree=ast.parse((g.HERE/'supermind_mainboard_baseline_2_pending1.py').read_text(encoding='utf-8'))
ns=dict(np=np,pd=pd,MIN_LISTING_BARS=250,MIN_AMOUNT20=50000000.,MIN_VOL20=.004,MAX_VOL20=.08)
names=['_rank01','_dividend_quality','_features','_rank_candidates']
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'features','exec'),ns)
rows={k:[] for k in ['reconstructed_adjustment','point_in_time_cents','prior_session']}
for i,s in enumerate(sorted(g.bt.load_universe()),1):
 if not g.bt.raw_path(s).exists() or not g.bt.qfq_path(s).exists():continue
 raw=pd.read_parquet(g.bt.raw_path(s));qfq=pd.read_parquet(g.bt.qfq_path(s))
 for z in [raw,qfq]:z['date']=pd.to_datetime(z.date)
 raw=raw[(raw.date<='2019-12-31')&(raw.tradestatus.astype(str)=='1')].sort_values('date').set_index('date').tail(752)
 adj=qfq[(qfq.date<='2019-12-31')&(qfq.tradestatus.astype(str)=='1')].sort_values('date').set_index('date').tail(752)
 if len(raw)<250 or len(adj)<250:continue
 raw=raw.rename(columns={'amount':'turnover','isST':'is_st'});adj=adj.rename(columns={'amount':'turnover','isST':'is_st'})
 lagraw=raw[raw.index<pd.Timestamp('2019-12-31')].tail(751);lagadj=adj[adj.index<pd.Timestamp('2019-12-31')].tail(751)
 ft=ns['_features'](lagadj,lagraw)
 if ft is not None:rows['prior_session'].append(dict(symbol=s,**ft))
 raw=raw.tail(751);adj=adj.tail(751)
 recon=raw.copy();ret=raw.close.astype(float)/raw.preclose.astype(float)
 if not np.isfinite(ret).all() or (ret<=0).any():continue
 reconstructed=ret.cumprod();recon['close']=reconstructed/reconstructed.iloc[-1]*float(raw.close.iloc[-1])
 normalized=adj.copy();normalized['close']=(adj.close.astype(float)/float(adj.close.iloc[-1])*float(raw.close.iloc[-1])).round(2)
 for k,z in [('reconstructed_adjustment',recon),('point_in_time_cents',normalized)]:
  ft=ns['_features'](z,raw)
  if ft is not None:rows[k].append(dict(symbol=s,**ft))
 if i%800==0:print('INPUT',i,flush=True)
platform=['603801.SH','603600.SH','603730.SH','603608.SH','601222.SH','600395.SH','600377.SH','603167.SH']
result={}
for k,r in rows.items():
 rank=ns['_rank_candidates'](pd.DataFrame(r),True)
 result[k]=dict(eligible=len(r),top8=rank.head(8).symbol.tolist(),overlap=len(set(rank.head(8).symbol)&set(platform)),status='diagnostic_hypothesis_not_validated_platform_data')
(OUT/'adjustment_hypotheses.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(result)
