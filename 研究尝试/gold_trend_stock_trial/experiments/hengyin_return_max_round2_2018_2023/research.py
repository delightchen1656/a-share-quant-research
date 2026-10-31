
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
import json,pathlib,hashlib,itertools,math
import numpy as np,pandas as pd
from numba import njit
OUT=pathlib.Path(__file__).resolve().parent
plan=json.loads((OUT/'SEARCH_PLAN.json').read_text(encoding='utf-8'));W=OUT.parents[1]/'inputs_pre2025/hengyin_2018_2023/WHITELIST.json';w=json.loads(W.read_text(encoding='utf-8-sig'));frames=[];audits=[]
for f in w['files']:
 p=resolve_recorded_path(f['path']);sha=hashlib.sha256(p.read_bytes()).hexdigest();assert sha==f['sha256'];d=pd.read_parquet(p).sort_values('date').reset_index(drop=True);dt=pd.to_datetime(d.date)
 assert len(d)==f['rows'] and dt.is_unique and dt.min()>=pd.Timestamp('2018-01-01') and dt.max()<=pd.Timestamp('2023-12-31') and d.code.eq('sh.603106').all()
 assert np.isfinite(d[['open','high','low','close']].to_numpy()).all() and (d[['open','high','low','close']]>0).all().all()
 frames.append(d);audits.append(dict(path=str(p),sha256=sha,rows=len(d),first=str(dt.min()),last=str(dt.max())))
q,r=frames;assert q.date.equals(r.date);keep=pd.to_numeric(q.tradestatus).eq(1)&pd.to_numeric(r.tradestatus).eq(1);q[~keep].to_csv(OUT/'suspension_rows.csv',index=False);q=q[keep].reset_index(drop=True);r=r[keep].reset_index(drop=True)
(OUT/'INPUT_AUDIT.json').write_text(json.dumps({'passed':True,'files':audits,'tradable_rows':len(q),'excluded_suspension_rows':int((~keep).sum())},indent=2),encoding='utf-8')
o=q.open.to_numpy(float);c=q.close.to_numpy(float);n=len(c);cs=pd.Series(c);dates=pd.to_datetime(q.date);years=(dates.iloc[-1]-dates.iloc[0]).days/365.2425
filters=['none','price_slow','slope5','recovery'];keys=['fast','slow','entry_buffer','exit_buffer','breakout','stop','cooldown','entry_filter'];numkeys=keys[:-1]+['filter_index']
mas=np.empty((166,n));highs=np.empty((121,n));mas[:]=np.nan;highs[:]=np.nan
for win in range(2,166):mas[win]=cs.rolling(win).mean().to_numpy()
for win in range(2,121):highs[win]=cs.shift(1).rolling(win).max().to_numpy()
pb=(1-cs/cs.rolling(60).max()).shift(1).rolling(20).max().to_numpy();gates=np.ones((4,166,n),dtype=np.bool_)
for slow in range(5,166):
 gates[1,slow]=c>mas[slow];gates[2,slow]=gates[1,slow]&(mas[slow]>=pd.Series(mas[slow]).shift(5).to_numpy());gates[3,slow]=gates[2,slow]&(c>highs[5])&(pb>=.04)
@njit
def simulate_many(params,o,c,mas,highs,gates):
 out=np.empty((len(params),7))
 for j in range(len(params)):
  f=int(params[j,0]);s=int(params[j,1]);eb=params[j,2];xb=params[j,3];b=int(params[j,4]);st=params[j,5];co=int(params[j,6]);gate=int(params[j,7]);warm=max(s,b+1)-1
  if gate>=2:warm=max(warm,s+4)
  if gate==3:warm=max(warm,79)
  cash=1.;qty=0.;pending=0;peak=0.;exit_i=-100000;top=1.;dd=0.;buys=0;sells=0;wins=0;entryprice=0.;held=0
  for i in range(len(c)):
   if pending==1:qty=cash/o[i];cash=0.;buys+=1;entryprice=o[i]
   elif pending==-1:
    cash=qty*o[i];qty=0.;sells+=1
    if o[i]>entryprice:wins+=1
   pending=0;nav=cash+qty*c[i];top=max(top,nav);dd=max(dd,1-nav/top)
   if qty>0:held+=1
   if i<warm:continue
   if qty>0:
    peak=max(peak,c[i])
    if mas[f,i]<mas[s,i]*(1-xb) or c[i]<peak*(1-st):pending=-1;exit_i=i
   elif i>=exit_i+co and gates[gate,s,i]:
    if mas[f,i]>mas[s,i]*(1+eb) or (c[i]>highs[b,i] and c[i]>mas[s,i]):pending=1;peak=c[i]
  out[j]=np.array([nav-1,dd,buys,sells,wins,1. if qty>0 else 0.,held])
 return out

def rank(df):return df.sort_values(['cumulative_return','max_drawdown']+keys,ascending=[False,True]+[True]*len(keys))
def search(params,stage):
 a=np.array(params,dtype=float);v=simulate_many(a,o,c,mas,highs,gates);df=pd.DataFrame(a,columns=numkeys);df['entry_filter']=[filters[int(x)] for x in df.filter_index];df=df.drop(columns='filter_index');df[['cumulative_return','max_drawdown','buy_fills','sell_fills','closed_wins','open_position_at_end','holding_days']]=v;df['annualized_return']=np.maximum(0,1+df.cumulative_return)**(1/years)-1;df['closed_win_rate']=np.where(df.sell_fills>0,df.closed_wins/df.sell_fills,np.nan);df['stage']=stage
 for k in ['fast','slow','breakout','cooldown','buy_fills','sell_fills','closed_wins','open_position_at_end','holding_days']:df[k]=df[k].astype(int)
 df=rank(df).reset_index(drop=True);df.to_csv(OUT/f'all_configurations_{stage}.csv',index=False);return df
params1=[]
for cfg in itertools.product(*plan['stage1']['grid'].values()):
 if cfg[0]<cfg[1]:params1.append((*cfg[:-1],filters.index(cfg[-1])))
assert len(params1)==plan['stage1']['configurations'];print('Stage1 start',len(params1),flush=True);d1=search(params1,'stage1');del params1
seeds=d1.head(plan['stage2']['seed_count']);seeds.to_csv(OUT/'STAGE2_SEEDS.csv',index=False)
# Stage2 follows only the predeclared Cartesian offsets and clipping; no later interventions.
rule=plan['stage2']['frozen_generation_rule'];bounds=plan['stage2']['bounds'];params2=set()
for _,seed in seeds.iterrows():
 for offsets in itertools.product(*(rule[k+'_offsets'] for k in keys[:-1])):
  vals=[]
  for k,delta in zip(keys[:-1],offsets):
   value=min(bounds[k][1],max(bounds[k][0],float(seed[k])+delta));vals.append(int(value) if k in ['fast','slow','breakout','cooldown'] else round(value,6))
  if vals[0]<vals[1]:params2.add((*vals,filters.index(seed.entry_filter)))
print('Stage2 start',len(params2),flush=True);d2=search(sorted(params2),'stage2');del params2
champions=rank(pd.concat([d1.head(100),d2.head(100)],ignore_index=True));champions.to_csv(OUT/'TOP_CANDIDATES.csv',index=False);winner=champions.iloc[0]
old=plan['old_training_winner'];ref=plan['old_reference'];best=[winner[k] for k in keys]
# Separately coded event ledger with freshly computed pandas features.
def ledger(cfg,label,limit=None,cost_bps=0,write=True):
 f,s,eb,xb,b,st,co,flt=cfg;f,s,b,co=map(int,(f,s,b,co));N=n if limit is None else limit;cc=pd.Series(c[:N]);oo=o[:N];fa=cc.rolling(f).mean();sl=cc.rolling(s).mean();hh=cc.shift(1).rolling(b).max();warm=max(f,s,b+1)-1;gate=np.ones(N,dtype=bool)
 if flt!='none':gate=(cc>sl).to_numpy()
 if flt in ['slope5','recovery']:gate=gate&(sl>=sl.shift(5)).to_numpy();warm=max(warm,s+4)
 if flt=='recovery':gate=gate&(cc>cc.shift(1).rolling(5).max()).to_numpy()&((1-cc/cc.rolling(60).max()).shift(1).rolling(20).max().to_numpy()>=.04);warm=max(warm,79)
 cash=1.;qty=0.;pending=None;peak=0.;exit_i=-100000;live=None;daily=[];events=[];signals=[];trades=[];rate=cost_bps/10000
 for i in range(N):
  if pending:
   side,si,why=pending;rr=r.iloc[i];pc=float(rr.preclose);limitrate=.05 if int(rr.isST) else .1;upper=math.floor(pc*(1+limitrate)*100+.5000001)/100;lower=math.floor(pc*(1-limitrate)*100+.5000001)/100;rawopen=float(rr.open);flag='UP_LIMIT_ESTIMATE' if rawopen>=upper-.005 else ('DOWN_LIMIT_ESTIMATE' if rawopen<=lower+.005 else '')
   events.append(dict(side=side,signal_index=si,signal_date=str(q.date.iloc[si]),fill_index=i,fill_date=str(q.date.iloc[i]),qfq_open=oo[i],raw_open=rawopen,limit_flag=flag,estimated_upper=upper,estimated_lower=lower,reason=why,one_way_cost_bps=cost_bps))
   if side=='BUY':qty=cash*(1-rate)/oo[i];cash=0.;live=dict(entry_signal_date=str(q.date.iloc[si]),entry_date=str(q.date.iloc[i]),entry_price=oo[i],entry_limit_flag=flag)
   else:cash=qty*oo[i]*(1-rate);qty=0.;trades.append(dict(**live,exit_signal_date=str(q.date.iloc[si]),exit_date=str(q.date.iloc[i]),exit_price=oo[i],exit_limit_flag=flag,return_=oo[i]/live['entry_price']*(1-rate)**2-1,status='CLOSED'));live=None
   pending=None
  nav=cash+qty*cc.iloc[i];daily.append(dict(date=str(q.date.iloc[i]),nav=nav,holding=int(qty>0),qfq_close=cc.iloc[i]))
  if i<warm:continue
  if qty>0:
   peak=max(peak,cc.iloc[i]);why=[]
   if fa.iloc[i]<sl.iloc[i]*(1-xb):why.append('MA_EXIT')
   if cc.iloc[i]<peak*(1-st):why.append('TRAIL_EXIT')
   if why:pending=('SELL',i,'+'.join(why));exit_i=i
  elif i>=exit_i+co and gate[i]:
   why=[]
   if fa.iloc[i]>sl.iloc[i]*(1+eb):why.append('MA_ENTRY')
   if cc.iloc[i]>hh.iloc[i] and cc.iloc[i]>sl.iloc[i]:why.append('BREAKOUT_ENTRY')
   if why:pending=('BUY',i,'+'.join(why));peak=cc.iloc[i]
  if pending:signals.append(dict(index=i,date=str(q.date.iloc[i]),side=pending[0],reason=pending[2],peak=peak))
 if live:trades.append(dict(**live,exit_signal_date='',exit_date=str(q.date.iloc[N-1]),exit_price=cc.iloc[-1],exit_limit_flag='',return_=cc.iloc[-1]/live['entry_price']*(1-rate)-1,status='OPEN_MARK_ONLY'))
 daily=pd.DataFrame(daily);nav=daily.nav.to_numpy();closed=[t for t in trades if t['status']=='CLOSED'];assert abs(np.prod([1+t['return_'] for t in trades])-nav[-1])<1e-9;assert all(e['fill_index']==e['signal_index']+1 for e in events)
 result=dict(label=label,cumulative_return=nav[-1]-1,annualized_return=nav[-1]**(1/years)-1,max_drawdown=float(np.max(1-nav/np.maximum.accumulate(np.r_[1.,nav])[1:])),buy_fills=sum(e['side']=='BUY' for e in events),sell_fills=sum(e['side']=='SELL' for e in events),closed_trades=len(closed),open_trades=int(bool(live)),closed_win_rate=sum(t['return_']>0 for t in closed)/len(closed) if closed else None,limit_fill_count=sum(bool(e['limit_flag']) for e in events),first_effective_date=str(q.date.iloc[warm]),first_signal_date=signals[0]['date'] if signals else None,one_way_cost_bps=cost_bps)
 if write:daily.to_csv(OUT/f'{label}_daily_nav.csv',index=False);pd.DataFrame(trades).to_csv(OUT/f'{label}_trades.csv',index=False);pd.DataFrame(events).to_csv(OUT/f'{label}_fills.csv',index=False);pd.DataFrame(signals).to_csv(OUT/f'{label}_signals.csv',index=False)
 return result,daily,signals
results={};navs={};validations=[]
for label,cfg in [('best',best),('old_training_winner',old),('original_reference',ref)]:
 result,daily,sig=ledger(cfg,label);results[label]=result;navs[label]=daily;param=np.array([[*cfg[:-1],filters.index(cfg[-1])]],dtype=float);nv=simulate_many(param,o,c,mas,highs,gates)[0]
 assert abs(result['cumulative_return']-nv[0])<1e-9 and abs(result['max_drawdown']-nv[1])<1e-9
 for cut in [300,600,900,1200]:
  _,pre,sg=ledger(cfg,'prefix',limit=cut,write=False);assert np.allclose(pre.nav,daily.nav.iloc[:cut],atol=1e-12,rtol=0);assert sg==[x for x in sig if x['index']<cut]
 validations.append(dict(label=label,second_engine=True,trade_compounding=True,prefix_cuts=[300,600,900,1200],next_bar=True))
assert abs(results['old_training_winner']['cumulative_return']-1.2069333171965284)<1e-12
# Prior adaptive champion only as fixed comparator, using its already authorized own artifact.
adaptive_path=OUT.parent/'hengyin_adaptive_2018_2023/cap35_daily_nav.csv';adaptive=pd.read_csv(adaptive_path);assert pd.to_datetime(adaptive.date).equals(dates);navs['prior_adaptive_cap35']=adaptive
navs['buy_hold']=pd.DataFrame({'date':q.date.astype(str),'nav':c/o[0],'holding':1});navs['buy_hold'].to_csv(OUT/'buy_hold_daily_nav.csv',index=False)
annual=[]
for label,daily in navs.items():
 prev=1.
 for year,part in daily.groupby(pd.to_datetime(daily.date).dt.year):
  a=part.nav.to_numpy();annual.append(dict(label=label,year=int(year),return_=a[-1]/prev-1,max_drawdown=float(np.max(1-a/np.maximum.accumulate(np.r_[prev,a])[1:]))));prev=a[-1]
pd.DataFrame(annual).to_csv(OUT/'annual_comparison.csv',index=False)
costs=[]
for label,cfg in [('best',best),('old_training_winner',old)]:
 base=results[label];fillcount=base['buy_fills']+base['sell_fills']
 for bp in plan['cost_sensitivity']['one_way_rates_bps']:
  rr,dd,ss=ledger(cfg,label,write=False,cost_bps=bp);assert abs(1+rr['cumulative_return']-(1+base['cumulative_return'])*(1-bp/10000)**fillcount)<1e-9;costs.append(rr)
pd.DataFrame(costs).to_csv(OUT/'cost_sensitivity.csv',index=False)
summary={'scope':'2018..2023 observed training only, no holdout','stages':{'stage1':len(d1),'stage2_unique_within_stage':len(d2),'total_evaluations_including_cross_stage_repeats':len(d1)+len(d2)},'best_parameters':dict(zip(keys,best)),'best':results['best'],'old_training_winner':results['old_training_winner'],'original_reference':results['original_reference'],'cumulative_return_improvement_percentage_points':100*(results['best']['cumulative_return']-results['old_training_winner']['cumulative_return']),'buy_hold_return':c[-1]/o[0]-1,'best_cumulative_excess_vs_buy_hold':results['best']['cumulative_return']-(c[-1]/o[0]-1),'validations':validations,'objective':plan['primary_objective'],'selection_note':'Highest of two predeclared finite search stages, no global optimum or future efficacy claim; drawdown only reported and tie-broken.','limitations':['Previously observed full interval; aggressive in-sample optimization can overfit.','Gross qfq fractional-share observation, not actual corporate-action account, integer lots or guaranteed fills.','Raw preclose/isST 10%/5% estimated limit flags, not official exchange limit validation.','No fees/slippage in objective; separately stated proportional-cost sensitivity is idealized reporting.','Daily-close drawdown, no intraday drawdown.']}
(OUT/'FROZEN_BEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),flush=True)
