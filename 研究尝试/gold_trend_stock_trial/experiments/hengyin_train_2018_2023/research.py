
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
import json,hashlib,itertools,pathlib,math
import numpy as np
import pandas as pd
from numba import njit
OUT=pathlib.Path(__file__).resolve().parent
ROOT=OUT.parents[1]
W=ROOT/'inputs_pre2025/hengyin_2018_2023/WHITELIST.json'
# No input discovery: only the manifest and its two explicit paths are read.
w=json.loads(W.read_text(encoding='utf-8-sig'))
frames=[]; audits=[]
for f in w['files']:
 p=resolve_recorded_path(f['path']); h=hashlib.sha256(p.read_bytes()).hexdigest(); assert h==f['sha256']
 d=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
 dates=pd.to_datetime(d.date); assert dates.min()>=pd.Timestamp('2018-01-01') and dates.max()<=pd.Timestamp('2023-12-31')
 assert len(d)==f['rows'] and dates.is_unique and d.code.eq('sh.603106').all()
 assert np.isfinite(d[['open','close']].to_numpy()).all() and (d[['open','close']]>0).all().all()
 assert pd.to_numeric(d.tradestatus).isin([0,1]).all()
 frames.append(d);audits.append(dict(path=str(p),sha256=h,rows=len(d),first=str(d.date.iloc[0]),last=str(d.date.iloc[-1])))
q,r=frames; assert q.date.equals(r.date)
suspended=q[pd.to_numeric(q.tradestatus)!=1].copy();suspended.to_csv(OUT/'suspension_rows.csv',index=False)
keep=(pd.to_numeric(q.tradestatus)==1)&(pd.to_numeric(r.tradestatus)==1)
q=q[keep].reset_index(drop=True);r=r[keep].reset_index(drop=True)
(OUT/'INPUT_AUDIT.json').write_text(json.dumps({'passed':True,'files':audits,'date_alignment':True,'suspended_rows_excluded_before_indicators':len(suspended),'tradable_rows':len(q)},indent=2),encoding='utf-8')
plan=json.loads((OUT/'SEARCH_PLAN.json').read_text()); grid=plan['grid']; keys=list(grid)
configs=[x for x in itertools.product(*(grid[k] for k in keys)) if x[0]<x[1]]
o=q.open.to_numpy(float);c=q.close.to_numpy(float);n=len(c)
windows=sorted(set(grid['fast']+grid['slow']+[20,120])); breaks=sorted(set(grid['breakout']+[90]))
mas=np.array([pd.Series(c).rolling(v).mean().to_numpy() for v in windows]); highs=np.array([pd.Series(c).shift(1).rolling(v).max().to_numpy() for v in breaks])
@njit
def sim(o,c,fast,slow,high,eb,xb,stop,cool,warm):
 cash=1.;units=0.;pending=0;peak=0.;exit_i=-100000;top=1.;mdd=0.;count=0;first=-1
 for i in range(len(c)):
  if pending==1:
   units=cash/o[i];cash=0.;count+=1
  elif pending==-1:
   cash=units*o[i];units=0.
  pending=0
  nav=cash+units*c[i];top=max(top,nav);mdd=max(mdd,1-nav/top)
  if i<warm:continue
  if units>0:
   peak=max(peak,c[i])
   if fast[i]<slow[i]*(1-xb) or c[i]<peak*(1-stop):pending=-1;exit_i=i
  elif i>=exit_i+cool:
   if fast[i]>slow[i]*(1+eb) or (c[i]>high[i] and c[i]>slow[i]):
    pending=1;peak=c[i]
    if first<0:first=i
 return cash+units*c[-1]-1,mdd,count,first
rows=[]
for cfg in configs:
 f,s,eb,xb,b,st,co=cfg;res=sim(o,c,mas[windows.index(f)],mas[windows.index(s)],highs[breaks.index(b)],eb,xb,st,co,max(f,s,b+1)-1)
 rows.append((*cfg,*res))
bh=c[-1]/o[0]-1
res=pd.DataFrame(rows,columns=keys+['cumulative_return','max_drawdown','entries','first_signal_index'])
res['excess_return']=res.cumulative_return-bh
res=res.sort_values(['excess_return','max_drawdown']+keys,ascending=[False,True]+[True]*len(keys)).reset_index(drop=True)
res.to_csv(OUT/'all_configurations.csv',index=False)

# Independent event ledger engine, using separately recomputed pandas indicators.
def ledger(cfg,label,close=c,opens=o,write=True):
 f,s,eb,xb,b,st,co=cfg;f,s,b,co=map(int,(f,s,b,co));warm=max(f,s,b+1)-1
 cs=pd.Series(close);fa=cs.rolling(f).mean();sl=cs.rolling(s).mean();hi=cs.shift(1).rolling(b).max()
 cash=1.;qty=0.;pending=None;peak=0.;last_exit=-100000;daily=[];signals=[];trades=[];live=None;events=[]
 def flag(i):
  rr=r.iloc[i];rate=.05 if int(rr.isST) else .1;pc=float(rr.preclose);op=float(rr.open)
  upper=math.floor(pc*(1+rate)*100+.5000001)/100;lower=math.floor(pc*(1-rate)*100+.5000001)/100
  return ('UP_LIMIT_ESTIMATE' if op>=upper-.005 else ('DOWN_LIMIT_ESTIMATE' if op<=lower+.005 else '')),upper,lower
 for i in range(len(close)):
  if pending:
   side,si,reason=pending;fl,up,lo=flag(i)
   events.append(dict(side=side,signal_index=si,signal_date=str(q.date.iloc[si]),fill_index=i,fill_date=str(q.date.iloc[i]),qfq_open=opens[i],raw_open=float(r.open.iloc[i]),limit_flag=fl,estimated_upper=up,estimated_lower=lo,reason=reason))
   if side=='BUY':
    qty=cash/opens[i];cash=0.;live=dict(entry_signal_date=str(q.date.iloc[si]),entry_date=str(q.date.iloc[i]),entry_price=opens[i],entry_limit_flag=fl)
   else:
    cash=qty*opens[i];qty=0.;trades.append(dict(**live,exit_signal_date=str(q.date.iloc[si]),exit_date=str(q.date.iloc[i]),exit_price=opens[i],exit_limit_flag=fl,return_=opens[i]/live['entry_price']-1,status='CLOSED'));live=None
   pending=None
  nav=cash+qty*close[i];daily.append(dict(date=str(q.date.iloc[i]),nav=nav,holding=int(qty>0),close=close[i]))
  if i<warm:continue
  if qty>0:
   peak=max(peak,close[i]);reasons=[]
   if fa.iloc[i]<sl.iloc[i]*(1-xb):reasons.append('MA_EXIT')
   if close[i]<peak*(1-st):reasons.append('TRAIL_EXIT')
   if reasons:pending=('SELL',i,'+'.join(reasons));last_exit=i
  elif i>=last_exit+co:
   reasons=[]
   if fa.iloc[i]>sl.iloc[i]*(1+eb):reasons.append('MA_ENTRY')
   if close[i]>hi.iloc[i] and close[i]>sl.iloc[i]:reasons.append('BREAKOUT_ENTRY')
   if reasons:pending=('BUY',i,'+'.join(reasons));peak=close[i]
  if pending:signals.append(dict(index=i,date=str(q.date.iloc[i]),side=pending[0],reason=pending[2],peak=peak))
 if live:trades.append(dict(**live,exit_signal_date='',exit_date=str(q.date.iloc[-1]),exit_price=close[-1],exit_limit_flag='',return_=close[-1]/live['entry_price']-1,status='OPEN_MARK_ONLY'))
 daily=pd.DataFrame(daily);vals=daily.nav.to_numpy();mdd=float(np.max(1-vals/np.maximum.accumulate(np.r_[1.,vals])[1:]))
 prod=float(np.prod([1+t['return_'] for t in trades]));assert abs(prod-vals[-1])<1e-10
 assert all(t['fill_index']==t['signal_index']+1 for t in events)
 if write:
  daily.to_csv(OUT/f'{label}_daily_nav.csv',index=False);pd.DataFrame(trades).to_csv(OUT/f'{label}_trades.csv',index=False);pd.DataFrame(events).to_csv(OUT/f'{label}_fills.csv',index=False);pd.DataFrame(signals).to_csv(OUT/f'{label}_signals.csv',index=False)
 return dict(label=label,cumulative_return=vals[-1]-1,max_drawdown=mdd,trade_count=len(trades),first_effective_date=str(q.date.iloc[warm]),first_signal_date=signals[0]['date'] if signals else None,limit_fill_count=sum(bool(e['limit_flag']) for e in events),open_position_at_end=bool(live)),daily,signals
bestcfg=tuple(res.iloc[0][keys]);ref=tuple(plan['reference']);best,bd,bs=ledger(bestcfg,'best');reference,rd,rs=ledger(ref,'reference')
# Validate an independently rebuilt full ledger on winners and drawdown/return alternatives.
selected=[bestcfg,ref]
for cap in [.1,.15,.2,.25,.3,.4]:
 subset=res[res.max_drawdown<=cap]
 if len(subset): selected.append(tuple(subset.iloc[0][keys]))
selected=list(dict.fromkeys(selected));checks=[]
for i,cfg in enumerate(selected):
 m,d,sig=ledger(cfg,f'candidate_{i}',write=False)
 fast,slow,eb,xb,b,st,co=cfg;v=sim(o,c,mas[windows.index(fast)],mas[windows.index(slow)],highs[breaks.index(b)],eb,xb,st,co,int(max(fast,slow,b+1)-1))
 assert abs(m['cumulative_return']-v[0])<1e-10 and abs(m['max_drawdown']-v[1])<1e-10
 checks.append(dict(zip(keys,cfg))|m|{'excess_return':m['cumulative_return']-bh})
pd.DataFrame(checks).to_csv(OUT/'tradeoff_candidates.csv',index=False)
# Prefix invariance: independently recompute truncated indicators and events, not a slice of full features.
for cut in [300,600,900,1200]:
 _,prefix,ss=ledger(bestcfg,'prefix',close=c[:cut],opens=o[:cut],write=False)
 assert np.allclose(prefix.nav,bd.nav.iloc[:cut],atol=1e-12,rtol=0)
 assert ss==[x for x in bs if x['index']<cut]
bnav=c/o[0];bench=pd.DataFrame({'date':q.date,'nav':bnav});bench.to_csv(OUT/'buy_hold_daily_nav.csv',index=False)
def yearly(df,label):
 rows=[];prev=1.
 for year,part in df.groupby(pd.to_datetime(df.date).dt.year):
  v=part.nav.to_numpy();dd=float(np.max(1-v/np.maximum.accumulate(np.r_[prev,v])[1:]));rows.append(dict(label=label,year=int(year),return_=v[-1]/prev-1,max_drawdown=dd));prev=v[-1]
 return rows
pd.DataFrame(yearly(bd,'best')+yearly(rd,'reference')+yearly(bench,'buy_hold')).to_csv(OUT/'annual_results.csv',index=False)
bmdd=float(np.max(1-bnav/np.maximum.accumulate(np.r_[1.,bnav])[1:]))
summary={'search_configurations':len(res),'objective':'training cumulative strategy return minus buy_hold return; lower drawdown tie break','best_parameters':dict(zip(keys,bestcfg)),'best':best,'reference_parameters':dict(zip(keys,ref)),'reference':reference,'buy_hold':{'cumulative_return':bh,'max_drawdown':bmdd,'entry_date':str(q.date.iloc[0]),'entry_qfq_open':o[0]},'best_excess_return':best['cumulative_return']-bh,'checks':{'input_hash_and_cutoff':True,'independent_engine':True,'trade_compounding':True,'next_bar_fills':True,'prefix_invariance_cuts':[300,600,900,1200]},'limitations':['In-sample finite-grid maximum, not global optimum and not out-of-sample evidence.','Qfq fractional-share gross price observation, no fees, slippage, real corporate-action cash/share ledger or executable-trading guarantee.','Limit-open flags estimated from raw preclose and isST at 10%/5%, not exchange limit-price validation; flagged fills remain idealized.','No pre-2018 warmup; remain cash until all windows ready. No artificial end liquidation; final positions marked at final close.']}
(OUT/'FROZEN_BEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print(pd.read_csv(OUT/'annual_results.csv').to_string(index=False))

