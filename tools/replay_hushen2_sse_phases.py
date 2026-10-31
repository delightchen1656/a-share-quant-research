"""Retrospective 10% SSE close zigzag phases; no timing or parameter optimization."""
from pathlib import Path
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse,json,pickle,sys,time,subprocess
import numpy as np
import pandas as pd
from replay_hushen2_local import ROOT,APP,GAME,load,sha
from replay_hushen2_live_approx import engine,dump,fetch_actions

BASE=ROOT/'archive/reports/holdout_restricted/hushen2_live_approx/attempt_20261030'
G={}

def zigzag_phases(index,threshold=.10):
    """Prices only. Confirm using later close; boundaries are prior extrema."""
    dates=list(index.index);prices=index.to_numpy(dtype=float)
    direction=0;high=low=0;pivot=0;rows=[]
    for i,value in enumerate(prices):
        if direction==0:
            if value>prices[high]:high=i
            if value<prices[low]:low=i
            if value>=prices[low]*(1+threshold)-1e-9:
                pivot=low;direction=1;high=i
            elif value<=prices[high]*(1-threshold)+1e-9:
                pivot=high;direction=-1;low=i
        elif direction==1:
            if value>prices[high]:high=i
            if value<=prices[high]*(1-threshold)+1e-9:
                rows.append(dict(direction='up',start=dates[pivot],end=dates[high],confirmed_at=dates[i],complete=True))
                pivot=high;direction=-1;low=i
        else:
            if value<prices[low]:low=i
            if value>=prices[low]*(1+threshold)-1e-9:
                rows.append(dict(direction='down',start=dates[pivot],end=dates[low],confirmed_at=dates[i],complete=True))
                pivot=low;direction=1;high=i
    if direction:
        rows.append(dict(direction='up' if direction==1 else 'down',start=dates[pivot],end=dates[-1],confirmed_at=None,complete=False))
    return rows

def prepare(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    # Use immutable verified snapshots while another quote transaction is staged.
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for key,expected in manifest['inputs'].items():
        assert sha(GAME/key)==expected,(key,'frozen input hash mismatch')
    with (BASE/'INPUT_PACK.pkl').open('rb') as stream:tail=pickle.load(stream)
    source=GAME/'frozen_inputs/cases/INPUT_PACK.pkl'
    with source.open('rb') as stream:p=pickle.load(stream)
    frozen_end=pd.Timestamp(p['end']);end=pd.Timestamp(tail['end'])
    p['calendar']=tail['calendar'];p['end']=end
    signals=p['signals'].loc[p['signals'].date.ge('2019-01-01')].copy()
    cache_receipts=[]
    for day in [d for d in p['calendar'] if frozen_end<d<=end]:
        files=list((APP/'tracker/data').glob(f'signals_{day.date()}_price_tr_sma14_over_signal_close_clip015_050_v1_original_top3_atr_ge025_no_refill_v1.json'))
        assert len(files)==1,('Missing completed frozen signal day',str(day.date()))
        receipt=json.loads(files[0].read_text(encoding='utf-8'))
        import hashlib
        digest=hashlib.sha256(json.dumps(receipt['signals'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        assert digest==receipt['signals_sha256'] and receipt['market_date']==str(day.date())
        extra=pd.DataFrame([dict(date=day,symbol=x['symbol'],close=x['trigger'],atr_pct=x['atr'],score=x['score'],factor='C04_NEW') for x in receipt['signals']])
        signals=pd.concat([signals,extra],ignore_index=True)
        cache_receipts.append(dict(path=str(files[0]),sha256=sha(files[0])))
    needed=set(signals.loc[signals.date>=end-pd.Timedelta(days=45),'symbol'])
    for symbol in needed:
        assert symbol in tail['bars'],('No frozen raw tail; wait for quote transaction',symbol)
        newer=tail['bars'][symbol]
        if symbol not in p['bars']:
            p['bars'][symbol]=newer.copy();continue
        older=p['bars'][symbol]
        overlap=older.index.intersection(newer.index)
        overlap=overlap[(overlap>=frozen_end-pd.Timedelta(days=45))&(overlap<=frozen_end)]
        for field in ['open','high','low','close','preclose','volume']:
            assert np.allclose(older.loc[overlap,field],newer.loc[overlap,field],rtol=1e-10,atol=1e-7,equal_nan=True),(symbol,field,'frozen overlap mismatch')
        p['bars'][symbol]=pd.concat([older,newer.loc[newer.index>frozen_end,older.columns]]).sort_index()
    extra_keys=tail['known']-p['known']
    for (day,symbol),actions in tail['actions'].items():
        if f'{symbol}/{day.year}' in extra_keys:p['actions'][day,symbol]=actions
    p['known']|=tail['known']
    p['signals']=signals.sort_values(['date','score','symbol'],ascending=[True,False,True]).reset_index(drop=True)
    assert not p['signals'].duplicated(['date','symbol']).any()
    identity=sha(source)
    old=pd.read_parquet(GAME/'frozen_inputs/market/SSE_PRICE_INDEX.parquet').set_index('date').close
    old.index=pd.to_datetime(old.index)
    recent=pd.read_parquet(BASE/'BENCHMARKS.parquet').query("benchmark=='SSE'").set_index('date').close
    recent.index=pd.to_datetime(recent.index)
    overlap=old.index.intersection(recent.index)
    assert np.allclose(old.loc[overlap],recent.loc[overlap],rtol=0,atol=1e-6)
    index=pd.concat([old.loc[old.index<recent.index.min()],recent]).sort_index()
    index=index.loc[index.index<=p['end']]
    phases=[r for r in zigzag_phases(index) if r['start']>=pd.Timestamp('2019-01-01') and r['end']>r['start']]
    for i,row in enumerate(phases,1):
        row['id']=i
        days=index.index[(index.index>=row['start'])&(index.index<=row['end'])]
        row['sessions']=len(days);row['starts']=list(days[:5])
        row['index_full_phase_return']=float(index.loc[row['end']]/index.loc[row['start']]-1)
    dump(out/'PHASES.json',phases)
    index.rename('close').to_frame().to_parquet(out/'SSE_INDEX.parquet')
    protocol=dict(frozen_before_results=True,start='2019 onward',end=str(p['end'].date()),reversal_threshold=.10,
        phases='SSE close index,seeded with2013+ history; up phase ends at peak confirmed by10% later drawdown; down ends at trough confirmed by10% later rebound; equal-extreme ties keep first occurrence',
        censoring='Only phases whose pivot start is2019 or later; ongoing last phase ends at last committed close and is not confirmed complete',
        samples='first5 exchange trading days of each phase,or all available if shorter; each starts100000 cash,no holdings/pending; signals from start close,first entry no earlier than following session',
        execution='same frozen live-approx engine and cost convention as'+str(BASE/'PROTOCOL.json'),
        no_terminal_entry_blackout=True,no_forced_liquidation=True,partial_positions='phase-end closing mark to NAV; dividends/receivables included',
        primary_metrics='Mean cumulative return,matched SSE return and cumulative excess; mean path maximum drawdown and Sharpe252/ddof0/rf0',
        retrospective_only=True,not_executable_market_timing=True,model_training_period='2020-2024; earlier replay is not historical available-model evidence',
        signal_extension_2019='Verified original ATR025 signal pack2019 through20261022; completed software day caches after that; do not rebuild from the uncommitted quote directory',
        no_retraining=True,no_parameter_selection=True,software_or_account_modified=False,
        source_pack=str(source),source_pack_sha256=sha(source),tail_pack=str(BASE/'INPUT_PACK.pkl'),tail_pack_sha256=sha(BASE/'INPUT_PACK.pkl'),
        current_quote_directory_read=False,source_engine_sha256=sha(ROOT/'tools/replay_hushen2_live_approx.py'),pipeline_id=identity,
        completed_signal_caches=cache_receipts,input_limit='Historical frozen signal vintage differs from the freshly rebuilt2020+ full-pool run; this is a separate phase audit,not its strict re-partition')
    dump(out/'PROTOCOL.json',protocol)
    print('PHASES',len(phases),'PATHS',sum(len(r['starts']) for r in phases),flush=True)
    p['phase_index']=index;p['phases']=phases
    with (out/'INPUT_PACK.pkl').open('wb') as stream:pickle.dump(p,stream,pickle.HIGHEST_PROTOCOL)
    p['signals'].to_parquet(out/'SIGNALS.parquet',index=False)
    dump(out/'INPUT_AUDIT.json',dict(total_signals=len(p['signals']),source2019_feature='verified existing frozen signals',
         input_pack_sha256=sha(out/'INPUT_PACK.pkl'),software_unchanged=True))
    print('PREPARED_FROZEN',len(p['signals']),flush=True)

def initialize(out):
    with (Path(out)/'INPUT_PACK.pkl').open('rb') as stream:G['p']=pickle.load(stream)
    G['out']=Path(out);G['core']=engine()

def job(item):
    phase_id,start_number,start=item;p=G['p'];core=G['core'];phase=next(r for r in p['phases'] if r['id']==phase_id)
    end=phase['end'];core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=list(range(start.year,end.year+1))
    curve=[];gaps=set()
    sig=p['signals'].loc[p['signals'].date.between(start,end)]
    r,t=core.simulate(sig,p['bars'],p['calendar'],'C04_NEW',0.,30,'take4_stop1.5',4.,1.5,keep_trades=True,actions=p['actions'],
         known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    c=pd.DataFrame(curve);c['start_date']=start;c['phase']=phase_id;c['start_number']=start_number
    e=c.equity.to_numpy();ret=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]];span=(end-start).days
    positions=r['terminal_positions'];unrealized=0.;position_value=0.
    for h in positions:
        mark=float(p['bars'][h['symbol']].loc[:end,'close'].iloc[-1]);value=h['frozen_value'] if h['frozen'] else h['shares']*mark
        unrealized+=value+h['dividends']-h['entry_cost'];position_value+=value
        if pd.Timestamp(h['deadline'])>end:assert pd.Timestamp(h['expiry_session'])>end
    assert abs(e[-1]-100000-(float(t.pnl.sum()) if len(t) else 0)-unrealized)<1e-6
    assert abs(e[-1]-r['terminal_cash']-r['terminal_deferred']-r['terminal_receivables']-position_value)<1e-6
    index=p['phase_index'];benchmark=float(index.loc[end]/index.loc[start]-1)
    cumulative=float(e[-1]/100000-1)
    m=dict(phase=phase_id,direction=phase['direction'],start_number=start_number,start=str(start.date()),end=str(end.date()),
           trading_days=len(c),cumulative_return=cumulative,benchmark_return=benchmark,cumulative_excess=cumulative-benchmark,
           annualized_return=(1+cumulative)**(365/span)-1 if span>0 else None,
           maximum_drawdown=float((e/np.maximum.accumulate(e)-1).min()),sharpe=float(np.sqrt(252)*ret.mean()/ret.std(ddof=0)) if ret.std(ddof=0)>0 else None,
           ending_equity=float(e[-1]),filled=r['filled_orders'],takes=int(t.reason.eq('take').sum()) if len(t) else 0,
           stops=int(t.reason.eq('stop').sum()) if len(t) else 0,expiries=int(t.reason.eq('expiry').sum()) if len(t) else 0,
           positions_at_end=len(positions),pending_at_end=len(r['terminal_pending']))
    dest=G['out']/'paths'/f'{phase_id:02d}_{start_number}_{str(start.date())}';dest.mkdir(parents=True,exist_ok=True)
    c.to_parquet(dest/'EQUITY.parquet',index=False);t.to_parquet(dest/'TRADES.parquet',index=False)
    pd.DataFrame(r['fixed_order_attempts']).to_parquet(dest/'ATTEMPTS.parquet',index=False)
    dump(dest/'METRICS.json',m);dump(dest/'TERMINAL.json',dict(positions=positions,pending=r['terminal_pending']))
    return m,sorted(gaps)

def run(out,workers):
    out=Path(out)
    with (out/'INPUT_PACK.pkl').open('rb') as stream:p=pickle.load(stream)
    items=[(r['id'],j,d) for r in p['phases'] for j,d in enumerate(r['starts'],1)]
    results=[];gaps=set()
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize,initargs=(str(out),)) as pool:
        futures=[pool.submit(job,item) for item in items]
        for f in as_completed(futures):
            m,missing=f.result();results.append(m);gaps.update(missing)
            if len(results)%10==0:print('PATHS',len(results),len(items),'ACTION_GAPS',len(gaps),flush=True)
    dump(out/'ACTION_GAPS.json',sorted(gaps))
    if gaps:
        print('ACTION_COVERAGE_REQUIRED',len(gaps),flush=True);return
    metrics=pd.DataFrame(results).sort_values(['phase','start_number']);metrics.to_parquet(out/'START_METRICS.parquet',index=False)
    summaries=[]
    for phase in p['phases']:
        m=metrics.loc[metrics.phase.eq(phase['id'])]
        keys=['cumulative_return','benchmark_return','cumulative_excess','maximum_drawdown','sharpe','ending_equity','filled','takes','stops','expiries','positions_at_end','pending_at_end']
        summaries.append(dict(**{k:v for k,v in phase.items() if k!='starts'},starts=len(m),
          means={k:float(m[k].mean()) if m[k].notna().any() else None for k in keys},
          median_return=float(m.cumulative_return.median()),positive_fraction=float(m.cumulative_return.gt(0).mean()),
          beat_fraction=float(m.cumulative_excess.gt(0).mean())))
    dump(out/'SUMMARY.json',dict(status='ok',threshold=.10,end=str(p['end'].date()),phase_count=len(summaries),paths=len(items),
          summaries=summaries,action_gaps=[],software_or_account_changed=False,retrospective_boundary=True))
    print('COMPLETE',len(summaries),len(items),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','fetch']);ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=3);a=ap.parse_args()
    if a.mode=='prepare':prepare(a.out)
    elif a.mode=='fetch':fetch_actions(a.out)
    else:run(a.out,a.workers)

if __name__=='__main__':main()
