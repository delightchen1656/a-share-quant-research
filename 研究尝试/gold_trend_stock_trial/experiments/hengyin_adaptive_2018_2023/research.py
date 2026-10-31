
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
import json,hashlib,itertools,math,pathlib
import numpy as np,pandas as pd
from numba import njit
OUT=pathlib.Path(__file__).resolve().parent
W=OUT.parents[1]/'inputs_pre2025/hengyin_2018_2023/WHITELIST.json'
plan=json.loads((OUT/'SEARCH_PLAN.json').read_text());w=json.loads(W.read_text(encoding='utf-8-sig'));frames=[];audits=[]
for f in w['files']:
 p=resolve_recorded_path(f['path']);h=hashlib.sha256(p.read_bytes()).hexdigest();assert h==f['sha256']
 d=pd.read_parquet(p).sort_values('date').reset_index(drop=True);dt=pd.to_datetime(d.date)
 assert len(d)==f['rows'] and dt.is_unique and dt.min()>=pd.Timestamp('2018-01-01') and dt.max()<=pd.Timestamp('2023-12-31')
 assert d.code.eq('sh.603106').all() and np.isfinite(d[['open','high','low','close']].to_numpy()).all() and (d[['open','high','low','close']]>0).all().all()
 frames.append(d);audits.append({'path':str(p),'sha256':h,'rows':len(d),'first':str(dt.min()),'last':str(dt.max())})
q,r=frames;assert q.date.equals(r.date)
keep=pd.to_numeric(q.tradestatus).eq(1)&pd.to_numeric(r.tradestatus).eq(1);q[~keep].to_csv(OUT/'suspension_rows.csv',index=False);q=q[keep].reset_index(drop=True);r=r[keep].reset_index(drop=True)
(OUT/'INPUT_AUDIT.json').write_text(json.dumps({'passed':True,'files':audits,'tradable_rows':len(q),'excluded_suspension_rows':int((~keep).sum())},indent=2),encoding='utf-8')
o=q.open.to_numpy(float);c=q.close.to_numpy(float);h=q.high.to_numpy(float);l=q.low.to_numpy(float);n=len(c);dates=pd.to_datetime(q.date);split=int(np.where(dates.dt.year.to_numpy()<=2021)[0][-1])
keys=['family','slope_lookback']+list(plan['grid']);configs=[]
for fam,desc in plan['families'].items():
 for slope in desc['slope_lookbacks']:
  for vals in itertools.product(*plan['grid'].values()):configs.append((fam,slope,*vals))
assert len(configs)==plan['configuration_count']
# Causal feature preparation; all prices are from the manifest's bounded tables.
cs=pd.Series(c);ma={v:cs.rolling(v).mean().to_numpy() for v in sorted(set(plan['grid']['fast']+plan['grid']['slow']+[20,60,120]))}
hi={v:cs.shift(1).rolling(v).max().to_numpy() for v in sorted(set(plan['grid']['breakout']+[5,90]))}
tr=np.maximum(h-l,np.maximum(abs(h-np.r_[c[0],c[:-1]]),abs(l-np.r_[c[0],c[:-1]])))
vols={'ATR14':np.clip(pd.Series(tr).rolling(14).mean().to_numpy()/c,.005,.15),'RV20':np.clip(np.log(cs/cs.shift(1)).rolling(20).std(ddof=0).to_numpy(),.005,.15)}
pullback=(1-cs/cs.rolling(60).max()).shift(1).rolling(20).max().to_numpy()
gates={('adaptive',s,0,v):np.ones(n,dtype=np.bool_) for s in plan['grid']['slow'] for v in plan['grid']['volatility']}
for fam in ['trend','recovery']:
 for s in plan['grid']['slow']:
  for slope in plan['families'][fam]['slope_lookbacks']:
   trend=(c>ma[s])&(ma[s]>=pd.Series(ma[s]).shift(slope).to_numpy())
   for v in plan['grid']['volatility']:gates[(fam,s,slope,v)]=trend if fam=='trend' else trend&(c>hi[5])&(pullback>=2*vols[v])
prior=cs.shift(1);m60=pd.Series(ma[60]);down=((prior<m60.shift(1))&(m60.shift(1)<m60.shift(21))).to_numpy();up=((prior>m60.shift(1))&(m60.shift(1)>m60.shift(21))).to_numpy()
stocklog=np.log(c/np.r_[o[0],c[:-1]])
@njit
def simulate(o,c,fast,slow,high,vol,gate,eb,xb,stop,cool,warm,split,down,up,adaptive):
 cash=1.;qty=0.;pending=0;peak=0.;last_exit=-100000;top=1.;dd=0.;trainnav=1.;traindd=0.;testtop=1.;testdd=0.;entries=0;sells=0;held=0;dh=0;uplog=0.;prevnav=1.
 for i in range(len(c)):
  if pending==1:qty=cash/o[i];cash=0.;entries+=1
  elif pending==-1:cash=qty*o[i];qty=0.;sells+=1
  pending=0;nav=cash+qty*c[i];top=max(top,nav);dd=max(dd,1-nav/top)
  if i<=split:trainnav=nav;traindd=dd;testtop=nav
  else:testtop=max(testtop,nav);testdd=max(testdd,1-nav/testtop)
  if qty>0:
   held+=1
   if down[i]:dh+=1
  if up[i]:uplog+=np.log(nav/prevnav)
  prevnav=nav
  if i<warm:continue
  en=eb*vol[i] if adaptive else eb;ex=xb*vol[i] if adaptive else xb;st=min(.35,max(.03,stop*vol[i])) if adaptive else stop
  if qty>0:
   peak=max(peak,c[i])
   if fast[i]<slow[i]*(1-ex) or c[i]<peak*(1-st):pending=-1;last_exit=i
  elif i>=last_exit+cool and gate[i]:
   if fast[i]>slow[i]*(1+en) or (c[i]>high[i] and c[i]>slow[i]):pending=1;peak=c[i]
 return nav-1,dd,trainnav-1,traindd,nav/trainnav-1,testdd,entries,sells,held,dh,uplog

def warmup(cfg):
 fam,sl,f,s,eb,xb,b,st,co,v=cfg
 return max(s+(sl if fam!='adaptive' else 0),b+1,(15 if v=='ATR14' else 21),80 if fam=='recovery' else 0)-1
metrics=['cumulative_return','max_drawdown','train_2018_2021_return','train_2018_2021_max_drawdown','test_2022_2023_return','test_2022_2023_max_drawdown','buy_fills','sell_fills','holding_days','down_regime_holding_days','up_regime_strategy_log_return']
rows=[]
for cfg in configs:
 fam,sl,f,s,eb,xb,b,st,co,v=cfg
 vals=simulate(o,c,ma[f],ma[s],hi[b],vols[v],gates[(fam,s,sl,v)],eb,xb,st,co,warmup(cfg),split,down,up,True);rows.append((*cfg,*vals))
df=pd.DataFrame(rows,columns=keys+metrics);df['config_id']=np.arange(len(df));df['excess_vs_buy_hold']=df.cumulative_return-(c[-1]/o[0]-1);df['down_regime_exposure']=df.down_regime_holding_days/int(down.sum());df['up_regime_log_capture']=df.up_regime_strategy_log_return/stocklog[up].sum() if stocklog[up].sum()>0 else np.nan
rank=lambda a,col='cumulative_return',dd='max_drawdown':a.sort_values([col,dd]+keys,ascending=[False,True]+[True]*len(keys))
df=rank(df);df.to_csv(OUT/'all_configurations.csv',index=False)

# Second implementation builds features anew with pandas and writes auditable events.
def ledger(cfg,label,limit=None,original=False,write=True):
 if original:
  f,s,eb,xb,b,st,co=cfg;fam='original';sl=0;v='FIXED';warm=max(f,s,b+1)-1
 else:
  fam,sl,f,s,eb,xb,b,st,co,v=cfg;warm=warmup(cfg)
 f,s,b,co,sl=map(int,(f,s,b,co,sl));N=n if limit is None else limit
 cc=pd.Series(c[:N]);oo=o[:N];hh=h[:N];ll=l[:N];ff=cc.rolling(f).mean();ss=cc.rolling(s).mean();bb=cc.shift(1).rolling(b).max()
 if original:vv=np.ones(N);gg=np.ones(N,dtype=bool)
 else:
  if v=='ATR14':
   rr=pd.concat([pd.Series(hh-ll),(pd.Series(hh)-cc.shift(1)).abs(),(pd.Series(ll)-cc.shift(1)).abs()],axis=1).max(axis=1);vv=(rr.rolling(14).mean()/cc).clip(.005,.15).to_numpy()
  else:vv=np.log(cc/cc.shift(1)).rolling(20).std(ddof=0).clip(.005,.15).to_numpy()
  gg=np.ones(N,dtype=bool) if fam=='adaptive' else ((cc>ss)&(ss>=ss.shift(sl))).to_numpy()
  if fam=='recovery':gg=gg&(cc>cc.shift(1).rolling(5).max()).to_numpy()&((1-cc/cc.rolling(60).max()).shift(1).rolling(20).max().to_numpy()>=2*vv)
 cash=1.;qty=0.;pending=None;peak=0.;last_exit=-100000;live=None;events=[];signals=[];trades=[];daily=[]
 for i in range(N):
  if pending:
   side,si,why=pending;rr=r.iloc[i];pc=float(rr.preclose);rate=.05 if int(rr.isST) else .1;upper=math.floor(pc*(1+rate)*100+.5000001)/100;lower=math.floor(pc*(1-rate)*100+.5000001)/100;rawopen=float(rr.open)
   flag='UP_LIMIT_ESTIMATE' if rawopen>=upper-.005 else ('DOWN_LIMIT_ESTIMATE' if rawopen<=lower+.005 else '')
   events.append(dict(side=side,signal_index=si,signal_date=str(q.date.iloc[si]),fill_index=i,fill_date=str(q.date.iloc[i]),qfq_open=oo[i],raw_open=rawopen,limit_flag=flag,estimated_upper=upper,estimated_lower=lower,reason=why))
   if side=='BUY':qty=cash/oo[i];cash=0.;live=dict(entry_signal_date=str(q.date.iloc[si]),entry_date=str(q.date.iloc[i]),entry_price=oo[i],entry_limit_flag=flag)
   else:cash=qty*oo[i];qty=0.;trades.append(dict(**live,exit_signal_date=str(q.date.iloc[si]),exit_date=str(q.date.iloc[i]),exit_price=oo[i],exit_limit_flag=flag,return_=oo[i]/live['entry_price']-1,status='CLOSED'));live=None
   pending=None
  nav=cash+qty*cc.iloc[i];daily.append(dict(date=str(q.date.iloc[i]),nav=nav,holding=int(qty>0),qfq_close=cc.iloc[i],causal_down_regime=int(down[i]),causal_up_regime=int(up[i])))
  if i<warm:continue
  en=eb if original else eb*vv[i];ex=xb if original else xb*vv[i];stop=st if original else min(.35,max(.03,st*vv[i]))
  if qty>0:
   peak=max(peak,cc.iloc[i]);why=[]
   if ff.iloc[i]<ss.iloc[i]*(1-ex):why.append('MA_EXIT')
   if cc.iloc[i]<peak*(1-stop):why.append('TRAIL_EXIT')
   if why:pending=('SELL',i,'+'.join(why));last_exit=i
  elif i>=last_exit+co and gg[i]:
   why=[]
   if ff.iloc[i]>ss.iloc[i]*(1+en):why.append('MA_ENTRY')
   if cc.iloc[i]>bb.iloc[i] and cc.iloc[i]>ss.iloc[i]:why.append('BREAKOUT_ENTRY')
   if why:pending=('BUY',i,'+'.join(why));peak=cc.iloc[i]
  if pending:signals.append(dict(index=i,date=str(q.date.iloc[i]),side=pending[0],reason=pending[2],peak=peak,volatility=float(vv[i]),entry_buffer=en,exit_buffer=ex,trailing_stop=stop))
 if live:trades.append(dict(**live,exit_signal_date='',exit_date=str(q.date.iloc[N-1]),exit_price=cc.iloc[-1],exit_limit_flag='',return_=cc.iloc[-1]/live['entry_price']-1,status='OPEN_MARK_ONLY'))
 daily=pd.DataFrame(daily);a=daily.nav.to_numpy();dd=float(np.max(1-a/np.maximum.accumulate(np.r_[1.,a])[1:]));assert abs(np.prod([1+t['return_'] for t in trades])-a[-1])<1e-9
 assert all(e['fill_index']==e['signal_index']+1 for e in events)
 if write:
  daily.to_csv(OUT/f'{label}_daily_nav.csv',index=False);pd.DataFrame(events).to_csv(OUT/f'{label}_fills.csv',index=False);pd.DataFrame(trades).to_csv(OUT/f'{label}_trades.csv',index=False);pd.DataFrame(signals).to_csv(OUT/f'{label}_signals.csv',index=False)
 logs=np.log(a/np.r_[1.,a[:-1]]);denom=stocklog[:N][up[:N]].sum();test=a[split+1:]/a[split] if N>split+1 else np.array([1.])
 result={'label':label,'cumulative_return':a[-1]-1,'max_drawdown':dd,'buy_fills':sum(e['side']=='BUY' for e in events),'sell_fills':sum(e['side']=='SELL' for e in events),'limit_fill_count':sum(bool(e['limit_flag']) for e in events),'holding_fraction':float(daily.holding.mean()),'down_regime_exposure':float(daily.loc[down[:N],'holding'].mean()),'up_regime_log_capture':float(logs[up[:N]].sum()/denom) if denom>0 else None,'first_effective_date':str(q.date.iloc[warm]),'first_signal_date':signals[0]['date'] if signals else None,'open_position_at_end':bool(live),'train_2018_2021_return':a[min(split,N-1)]-1,'test_2022_2023_return':a[-1]/a[split]-1 if N>split+1 else None,'test_2022_2023_max_drawdown':float(np.max(1-test/np.maximum.accumulate(np.r_[1.,test])[1:]))}
 return result,daily,signals

def choose(col,dd,cap=None,frame=df):
 pool=frame if cap is None else frame[frame[dd]<=cap+1e-12]
 return None if len(pool)==0 else rank(pool,col,dd).iloc[0]
selected={};diagnostic_selection={}
for label,cap in [('cap30',.30),('cap35',.35),('unconstrained',None)]:
 row=choose('cumulative_return','max_drawdown',cap)
 if row is not None:selected[label]=tuple(row[k] for k in keys)
 row=choose('train_2018_2021_return','train_2018_2021_max_drawdown',cap)
 if row is not None:diagnostic_selection['split_'+label]=tuple(row[k] for k in keys)
allselected=selected|diagnostic_selection;results={};navs={};validations=[]
for label,cfg in allselected.items():
 result,daily,sigs=ledger(cfg,label);row=df[df.config_id==configs.index(cfg)].iloc[0]
 for field in ['cumulative_return','max_drawdown','train_2018_2021_return','test_2022_2023_return','test_2022_2023_max_drawdown']:assert abs(result[field]-row[field])<1e-9,(label,field)
 assert result['buy_fills']==int(row.buy_fills) and result['sell_fills']==int(row.sell_fills)
 for cut in [300,600,900,1200]:
  _,pr,sg=ledger(cfg,'prefix',limit=cut,write=False);assert np.allclose(pr.nav,daily.nav.iloc[:cut],atol=1e-12,rtol=0);assert sg==[x for x in sigs if x['index']<cut]
 results[label]=result;navs[label]=daily;validations.append({'label':label,'second_engine_equal':True,'prefix_invariance':[300,600,900,1200],'trade_compounding':True,'next_tradable_bar_fills':True})
for label,cfg in [('original_reference',plan['comparators']['reference']),('prior_frozen_best',plan['comparators']['prior_frozen_best'])]:
 result,daily,sig=ledger(cfg,label,original=True);results[label]=result;navs[label]=daily
 # Independent comparison to Numba fixed-parameter branch.
 f,s,eb,xb,b,st,co=cfg;v=simulate(o,c,ma[f],ma[s],hi[b],np.ones(n),np.ones(n,dtype=np.bool_),eb,xb,st,co,max(f,s,b+1)-1,split,down,up,False)
 assert abs(result['cumulative_return']-v[0])<1e-9 and abs(result['max_drawdown']-v[1])<1e-9
navs['buy_hold']=pd.DataFrame({'date':q.date.astype(str),'nav':c/o[0],'holding':1,'causal_down_regime':down.astype(int),'causal_up_regime':up.astype(int)});navs['buy_hold'].to_csv(OUT/'buy_hold_daily_nav.csv',index=False)
results['buy_hold']={'label':'buy_hold','cumulative_return':c[-1]/o[0]-1,'max_drawdown':float(np.max(1-(c/o[0])/np.maximum.accumulate(np.r_[1.,c/o[0]])[1:])),'down_regime_exposure':1.,'up_regime_log_capture':1.}
annual=[];splitrows=[]
for label,daily in navs.items():
 prev=1.
 for year,part in daily.groupby(pd.to_datetime(daily.date).dt.year):
  a=part.nav.to_numpy();annual.append({'label':label,'year':int(year),'return_':a[-1]/prev-1,'max_drawdown':float(np.max(1-a/np.maximum.accumulate(np.r_[prev,a])[1:]))});prev=a[-1]
 for period,start,end in [('fit_2018_2021',0,split+1),('diagnostic_2022_2023',split+1,n)]:
  part=daily.iloc[start:end];a=part.nav.to_numpy();base=float(daily.nav.iloc[start-1]) if start else 1.;logs=np.log(a/np.r_[base,a[:-1]]);u=up[start:end];de=down[start:end];den=stocklog[start:end][u].sum()
  splitrows.append({'label':label,'period':period,'return_':a[-1]/base-1,'max_drawdown':float(np.max(1-a/np.maximum.accumulate(np.r_[base,a])[1:])),'down_regime_exposure':float(part.loc[de,'holding'].mean()),'up_regime_log_capture':float(logs[u].sum()/den) if den>0 else np.nan})
pd.DataFrame(annual).to_csv(OUT/'annual_comparison.csv',index=False);pd.DataFrame(splitrows).to_csv(OUT/'chronological_diagnostic.csv',index=False);pd.DataFrame(results.values()).to_csv(OUT/'selected_comparison.csv',index=False)
# Complete two-dimensional Pareto frontier, followed by family/cap winners.
front=[];bestreturn=-np.inf
for _,row in df.sort_values(['max_drawdown','cumulative_return'],ascending=[True,False]).iterrows():
 if row.cumulative_return>bestreturn+1e-12:front.append(row);bestreturn=row.cumulative_return
pd.DataFrame(front).to_csv(OUT/'pareto_frontier.csv',index=False)
familyrows=[]
for fam in plan['families']:
 for label,cap in [('cap30',.30),('cap35',.35),('unconstrained',None)]:
  row=choose('cumulative_return','max_drawdown',cap,df[df.family==fam])
  if row is not None:familyrows.append(row.to_dict()|{'constraint':label})
pd.DataFrame(familyrows).to_csv(OUT/'family_champions.csv',index=False)
summary={'scope':'白名单数据隔离的区间内训练搜索；已观察区间内时间切分诊断，不是盲测','configurations':len(configs),'selected_parameters':{label:dict(zip(keys,cfg)) for label,cfg in allselected.items()},'selected_results':results,'selection_protocol':plan['selection'],'chronological_protocol':plan['diagnostics']['time_split'],'regime_days':{'down':int(down.sum()),'up':int(up.sum()),'neutral':int((~down&~up).sum())},'validations':validations,'limitations':['Prior original search observed all 2018..2023; no untouched holdout exists here.','Full-training risk constraints are in-sample only, not forward drawdown guarantees.','Fractional qfq price gross returns, no fees/slippage or real corporate-action ledger.','Limit flags are estimated with raw preclose and isST, not official limit validation or fill guarantees.','Daily-close drawdowns omit intraday peaks and troughs.']}
(OUT/'FROZEN_CANDIDATES.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)))
