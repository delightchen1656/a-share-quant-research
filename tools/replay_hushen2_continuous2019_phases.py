"""Run each2019Q1 account once; segment its unchanged equity path afterwards."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse,json,pickle
import numpy as np
import pandas as pd
from replay_hushen2_live_approx import ROOT,engine,dump,sha,fetch_actions

SOURCE=ROOT/'archive/reports/holdout_restricted/hushen2_sse_phases/attempt_20261030_zigzag10'
TAIL=ROOT/'archive/reports/holdout_restricted/hushen2_live_approx/attempt_20261030'
G={}

def prepare(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    verified=json.loads((SOURCE/'VERIFICATION.json').read_text(encoding='utf-8'))
    assert verified['status']=='passed' and sha(SOURCE/'INPUT_PACK.pkl')==verified['hashes']['INPUT_PACK.pkl']
    with (SOURCE/'INPUT_PACK.pkl').open('rb') as f:p=pickle.load(f)
    with (TAIL/'INPUT_PACK.pkl').open('rb') as f:tail=pickle.load(f)
    # Extend every available previously frozen bar, not only recent signal names:
    # a continuing account can carry an older holding across phase boundaries.
    overlap_checks=0
    for symbol,new in tail['bars'].items():
        if symbol not in p['bars']:continue
        old=p['bars'][symbol];old_end=old.index.max()
        if new.index.max()<=old_end:continue
        dates=old.index.intersection(new.index)
        dates=dates[dates>=old_end-pd.Timedelta(days=45)]
        for key in ['open','high','low','close','preclose','volume']:
            assert np.allclose(old.loc[dates,key],new.loc[dates,key],rtol=1e-10,atol=1e-7,equal_nan=True),(symbol,key)
        p['bars'][symbol]=pd.concat([old,new.loc[new.index>old_end,old.columns]]).sort_index();overlap_checks+=1
    starts=[d for d in p['calendar'] if d.year==2019 and d.month<=3]
    assert len(starts)==58
    protocol=dict(frozen_before_results=True,end=str(p['end'].date()),initial_cash=100000,starts=starts,
         start_population='All58 exchange sessions in2019Q1; each is a separate initially empty account',
         account_continuity='Exactly one full simulation per start,2019 to latest frozen date. No phase-start reset/liquidation/rebalance and no phase-end trade instruction.',
         phase_boundaries='Reuse exact previously frozen10% SSE close zigzag18phases; only used AFTER account simulation',
         attribution='Phase return=closing equity at phase end/closing equity at phase start-1; shared boundary close appears once in compounding,not as an extra daily return.',
         first_phase='Initial partial phase uses each actual Q1 startup day and100000 initial cash as its base; includes the one-day left-edge stub forJan2 start so total compounding reconciles.',
         annualized='Per start and segment: (end_equity/base_equity)^(365/calendar day span)-1; average across58 paths. Annualized excess subtracts matched SSE CAGR.',
         execution='Unchanged previously frozen actual-fill-anchor live-approx engine:5slots,ATR025/no refill,fixedIOC,7/30natural,T+1,next-open expiry,no37day tail,no forced final liquidation',
         costs='prior agreed approximation: one-side .002,commission .0003 min5,sell stamp .001,no separate transfer',
         source_input=str(SOURCE/'INPUT_PACK.pkl'),source_sha256=sha(SOURCE/'INPUT_PACK.pkl'),source_phases_sha256=sha(SOURCE/'PHASES.json'),
         engine_sha256=sha(ROOT/'tools/replay_hushen2_live_approx.py'),additional_frozen_raw_tails=overlap_checks,
         current_quote_directory_read=False,models_retrained=False,production_or_account_modified=False,
         limitations='Retrospective boundaries and old frozen signal vintage;2019 is not a model-available-at-that-time blind result; not hypothetical knowable regime timing')
    dump(out/'PROTOCOL.json',protocol)
    with (out/'INPUT_PACK.pkl').open('wb') as f:pickle.dump(p,f,pickle.HIGHEST_PROTOCOL)
    print('PREPARED',len(starts),'END',p['end'],'EXTENDED_BARS',overlap_checks,flush=True)

def initialize(out):
    out=Path(out)
    with (out/'INPUT_PACK.pkl').open('rb') as f:G['p']=pickle.load(f)
    core=engine()
    needle='"date": date,\n                "equity":'
    assert core.source.count(needle)==1
    source=core.source.replace(needle,'"date": date,\n                "positions": len(holdings), "pending": len(pending),\n                "cash": cash, "deferred": deferred_cash,\n                "held_symbols": ",".join(h.symbol for h in holdings),\n                "equity":')
    exec(compile(source,'<continuous_account_diagnostics_only>','exec'),core.__dict__)
    G.update(out=out,core=core)

def stats(equity,base,days,include_first):
    e=np.asarray(equity,dtype=float)
    daily=np.r_[e[0]/base-1,np.diff(e)/e[:-1]] if include_first else np.diff(e)/e[:-1]
    path=np.r_[base,e] if include_first else e
    total=float(e[-1]/base-1)
    return dict(cumulative_return=total,annualized_return=float((1+total)**(365/days)-1) if days>0 else None,
        maximum_drawdown=float((path/np.maximum.accumulate(path)-1).min()),
        sharpe=float(np.sqrt(252)*daily.mean()/daily.std(ddof=0)) if len(daily) and daily.std(ddof=0)>0 else None)

def job(item):
    ordinal,start=item;p=G['p'];core=G['core'];end=p['end']
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=list(range(2019,end.year+1))
    curves=[];gaps=set()
    r,t=core.simulate(p['signals'].loc[p['signals'].date.ge(start)],p['bars'],p['calendar'],'C04_NEW',0.,30,'take4_stop1.5',4.,1.5,
         keep_trades=True,actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curves)
    c=pd.DataFrame(curves);c['start_ordinal']=ordinal;c['start_date']=start
    positions=r['terminal_positions'];value=residual=0.
    for h in positions:
        b=p['bars'][h['symbol']]
        if not h['frozen']:assert end in b.index,('No verified latest holding bar',h['symbol'])
        mark=float(b.loc[:end,'close'].iloc[-1]);mv=h['frozen_value'] if h['frozen'] else h['shares']*mark
        value+=mv;residual+=mv+h['dividends']-h['entry_cost']
    e=c.equity.to_numpy()
    assert abs(e[-1]-100000-(float(t.pnl.sum()) if len(t) else 0)-residual)<1e-6
    assert abs(e[-1]-r['terminal_cash']-r['terminal_deferred']-r['terminal_receivables']-value)<1e-6
    overall=stats(e,100000.,(end-start).days,True)
    index=p['phase_index'];bm=float(index.loc[end]/index.loc[start]-1)
    overall.update(start_ordinal=ordinal,start=str(start.date()),end=str(end.date()),ending_equity=float(e[-1]),benchmark_return=bm,
         benchmark_annualized=(1+bm)**(365/(end-start).days)-1,
         filled=r['filled_orders'],takes=int(t.reason.eq('take').sum()),stops=int(t.reason.eq('stop').sum()),expiries=int(t.reason.eq('expiry').sum()),
         terminal_positions=len(positions),terminal_pending=len(r['terminal_pending']))
    overall['annualized_excess']=overall['annualized_return']-overall['benchmark_annualized']
    c=c.set_index('date');segments=[];product=1.
    for n,phase in enumerate(p['phases']):
        boundary=phase['start'];finish=phase['end']
        if n==0:
            boundary=start;base=100000.;part=c.loc[start:finish];include_first=True
        else:
            base=float(c.loc[boundary,'equity']);part=c.loc[boundary:finish];include_first=False
        span=(finish-boundary).days
        m=stats(part.equity.to_numpy(),base,span,include_first)
        benchmark=float(index.loc[finish]/index.loc[boundary]-1)
        m.update(start_ordinal=ordinal,phase=phase['id'],direction=phase['direction'],effective_start=str(boundary.date()),end=str(finish.date()),
             calendar_days=span,base_equity=base,end_equity=float(part.equity.iloc[-1]),benchmark_return=benchmark,
             benchmark_annualized=(1+benchmark)**(365/span)-1,cumulative_excess=m['cumulative_return']-benchmark,
             opening_positions=0 if n==0 else int(part.positions.iloc[0]),opening_pending=0 if n==0 else int(part.pending.iloc[0]),
             boundary_held_symbols='' if n==0 else part.held_symbols.iloc[0])
        m['annualized_excess']=m['annualized_return']-m['benchmark_annualized']
        product*=1+m['cumulative_return'];segments.append(m)
    assert abs(product-e[-1]/100000)<1e-10
    dest=G['out']/'paths'/f'{ordinal:02d}_{start.date()}';dest.mkdir(parents=True,exist_ok=True)
    c.reset_index().to_parquet(dest/'EQUITY.parquet',index=False);t.to_parquet(dest/'TRADES.parquet',index=False)
    pd.DataFrame(segments).to_parquet(dest/'SEGMENTS.parquet',index=False)
    pd.DataFrame(r['fixed_order_attempts']).to_parquet(dest/'ATTEMPTS.parquet',index=False)
    dump(dest/'METRICS.json',overall);dump(dest/'TERMINAL.json',dict(positions=positions,pending=r['terminal_pending']))
    return overall,segments,sorted(gaps)

def run(out,workers):
    out=Path(out)
    with (out/'INPUT_PACK.pkl').open('rb') as f:p=pickle.load(f)
    starts=[d for d in p['calendar'] if d.year==2019 and d.month<=3];assert len(starts)==58
    records=[];segments=[];gaps=set()
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize,initargs=(str(out),)) as pool:
        futures=[pool.submit(job,(i,d)) for i,d in enumerate(starts,1)]
        for f in as_completed(futures):
            m,parts,missing=f.result();records.append(m);segments+=parts;gaps.update(missing)
            if len(records)%10==0:print('CONTINUOUS',len(records),58,'ACTION_GAPS',len(gaps),flush=True)
    dump(out/'ACTION_GAPS.json',sorted(gaps))
    if gaps:print('ACTION_COVERAGE_REQUIRED',len(gaps),flush=True);return
    m=pd.DataFrame(records).sort_values('start_ordinal');parts=pd.DataFrame(segments).sort_values(['phase','start_ordinal'])
    m.to_parquet(out/'START_METRICS.parquet',index=False);parts.to_parquet(out/'SEGMENT_METRICS.parquet',index=False)
    rows=[]
    for phase in p['phases']:
        frame=parts.loc[parts.phase.eq(phase['id'])]
        keys=['cumulative_return','annualized_return','benchmark_return','benchmark_annualized','cumulative_excess','annualized_excess','maximum_drawdown','sharpe','opening_positions','opening_pending']
        rows.append(dict(id=phase['id'],direction=phase['direction'],start=str(phase['start'].date()),end=str(phase['end'].date()),complete=phase['complete'],paths=len(frame),
             means={k:float(frame[k].mean()) if frame[k].notna().any() else None for k in keys},
             min_effective_start=str(frame.effective_start.min()),max_effective_start=str(frame.effective_start.max()),
             positive_fraction=float(frame.cumulative_return.gt(0).mean()),beat_fraction=float(frame.cumulative_excess.gt(0).mean())))
    keys=['cumulative_return','annualized_return','benchmark_return','benchmark_annualized','annualized_excess','maximum_drawdown','sharpe','ending_equity','filled','takes','stops','expiries','terminal_positions','terminal_pending']
    result=dict(status='ok',starts=58,end=str(p['end'].date()),continuous=True,mean={k:float(m[k].mean()) for k in keys},
         median={k:float(m[k].median()) for k in keys},phases=rows,action_gaps=[],software_or_account_modified=False)
    dump(out/'SUMMARY.json',result);print('COMPLETE_CONTINUOUS',58,len(rows),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','fetch']);ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=3);a=ap.parse_args()
    if a.mode=='prepare':prepare(a.out)
    elif a.mode=='fetch':fetch_actions(a.out)
    else:run(a.out,a.workers)

if __name__=='__main__':main()
