"""Frozen-model, no-tuning approximation of the actual evening tracker workflow."""
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse,json,pickle,sys,inspect,time,hashlib,subprocess
import numpy as np
import pandas as pd
from replay_hushen2_local import ROOT,APP,STRATEGY,GAME,load,sha

G={}

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')

def engine():
    original=load('live_approx_original',GAME/'runtime/run_batch.py')
    adapter=load('live_approx_fixed',GAME/'runtime/baseline_fixed_ioc.py')
    core=adapter.fixed_ioc_engine(original,manual_expiry_open=True,filled_slots=False)
    source=core.adapted_source
    changes=[
        ('budget = max(0.0, equity / slots)','budget = max(0.0, min(equity / slots, cash + deferred_cash))'),
        ('pending.append(Pending(',
         'submitted_quantity=int(max(0.,budget-5.) // ((float(row["close"])*(1.+slip))*100))*100\n            if submitted_quantity < 100:\n                below_100_share_orders += 1\n                continue\n            pending.append(Pending('),
        ('quantity=int(budget // ((float(row["close"]) * (1.0 - entry_offset * float(row["atr_pct"]))) * (1.0 + slip) * 100)) * 100,','quantity=submitted_quantity,'),
        ('take_price=buy_price * (1.0 + take_mult * atr),','take_price=round(buy_price * (1.0 + take_mult * atr),2),'),
        ('stop_price=buy_price * (1.0 - stop_mult * atr),','stop_price=round(buy_price * (1.0 - stop_mult * atr),2),'),
        ('result["fixed_order_attempts"] = fixed_order_attempts',
         'result["fixed_order_attempts"] = fixed_order_attempts\n    result["terminal_positions"]=[asdict(x) for x in holdings]\n    result["terminal_pending"]=[asdict(x) for x in pending]\n    result["terminal_cash"]=cash\n    result["terminal_deferred"]=deferred_cash\n    result["terminal_receivables"]=sum(x[1] for x in receivables)')]
    for before,after in changes:
        assert source.count(before)==1,('unexpected frozen source',before)
        source=source.replace(before,after)
    core.asdict=asdict
    exec(compile(source,'<tracker_live_approximation>','exec'),core.__dict__)
    core.source=source
    return core

def prepare(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(APP/'tracker'));sys.path.insert(0,str(APP/'runtime'))
    market=load('live_approx_market',APP/'tracker/market.py')
    subprocess.run([sys.executable,'-B',str(APP/'runtime/verify.py')],check=True,capture_output=True)
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert sha(GAME/'runtime/run_batch.py')==selection['research_provenance_sha256']['relocated_execution_engine_source'].lower()
    h=market.health(APP/'tracker/data');end=pd.Timestamp(h['market_date'])
    identity,inputs=market.pipeline_identity(h)
    protocol=dict(status='frozen_before_account_results',start_population='all 2020 Q1 exchange sessions; each starts empty, first signal at that close',end=str(end.date()),
        initial_cash=100000,slots=5,selection='current frozen C04_NEW full tracker universe; original daily top3 then ATR>=.025; no refill or retraining',
        entry='7 natural days; next-session onward; accepted fixed100-share quantity; budget=min(close equity/5,cash+same-day deferred proceeds); subtract5 before dividing trigger*1.002',
        protection='simulated actual fill*(1+4ATR)/(1-1.5ATR),rounded to .01; signal ATR frozen; T+1',
        expiry='30 natural days; last session on/before deadline retains protection; remaining position sells following session open; exchange calendar includes future sessions but no future prices',
        cash='sale proceeds reusable next session; pending buys occupy slots but do not reserve cash; duplicate stock blocked; accepts all feasible recommendations in rank order',
        costs=dict(one_side_slippage=.002,commission_rate=.0003,commission_min=5,sell_stamp=.001,separate_transfer_fee=False),
        approximations=['Daily OHLC,not historical five-best orderbook','2% full-day buy volume proxy; partial IOC remainder cancelled; one trigger attempt',
          'Same-day both touched: stop first,actual OCO chronology unknown','Fixed prior cost convention,not verified personal broker fee contract',
          'Keep verified dividend/share/receivable and delisting engine rather than invent manual corporate-action histories',
          'Daily qfq vintage retrospective replay; not a point-in-time feed archive; 2020-2024 model-development period,not fresh blind test',
          'No actual cash injections or discretionary rejected signals in hypothetical paths'],
        terminal='no37day entry blackout; no forced liquidation; include open positions and pending orders',pipeline_id=identity,inputs=inputs,
        production_model_changed=False,old_baseline_overwritten=False)
    dump(out/'PROTOCOL.json',protocol)
    last_print=[0.]
    def progress(msg):
        dump(out/'PROGRESS.json',dict(stage='signal_reconstruction',message=msg,at=datetime.now().isoformat()))
        if time.monotonic()-last_print[0]>25:
            print('PREPARE',msg,flush=True);last_print[0]=time.monotonic()
    progress('计算当前软件全历史特征')
    panel=market.score_panel(market.feature_panel(str(end.date()),progress),progress)
    progress('冻结模型完成；构建原前三并筛选ATR')
    signals=market.build_recommendations(panel)
    del panel
    signals=signals.loc[signals.date.between('2020-01-01',end)].copy()
    signals['factor']='C04_NEW'
    # The model feature close may be qfq. Broker trigger is that date's raw close.
    bars={};raw_inputs={}
    for symbol in sorted(signals.symbol.unique()):
        path=market.DATA/'raw'/symbol[-2:]/f'{symbol}.parquet'
        raw_inputs[str(path)]=sha(path)
        b=pd.read_parquet(path);b.date=pd.to_datetime(b.date)
        b=b.loc[b.date.le(end)].sort_values('date')
        assert not b.date.duplicated().any(),symbol
        for k in ('open','high','low','close','preclose','volume','amount','tradestatus'):
            b[k]=pd.to_numeric(b[k],errors='raise')
        bars[symbol]=b.set_index('date')
        mask=signals.symbol.eq(symbol)
        signals.loc[mask,'close']=signals.loc[mask,'date'].map(bars[symbol].close)
    assert signals.close.notna().all() and not signals.duplicated(['date','symbol']).any()
    latest_cache=market.signal_cache_path(APP/'tracker/data',str(end.date()))
    if latest_cache.exists():
        cached=json.loads(latest_cache.read_text(encoding='utf-8'))
        latest=signals.loc[signals.date.eq(end)].sort_values('rank' if 'rank' in signals else 'score',ascending='rank' in signals)
        if len(latest):
            actual=[(r.symbol,float(r.close),float(r.atr_pct)) for r in latest.itertuples()]
            expected=[(r['symbol'],r['trigger'],r['atr']) for r in cached['signals']]
            assert actual==expected,('latest tracker signal mismatch',actual,expected)
    source=ROOT/'archive/reports/holdout_restricted/hushen2_leader_pool/post2024_20261028_202602/INPUT_PACK.pkl'
    with source.open('rb') as stream:old=pickle.load(stream)
    p={k:old[k] for k in ('actions','known','delists','index')}
    p.update(signals=signals,bars=bars,calendar=[pd.Timestamp(d) for d in h['sessions']],end=end)
    # Verified later action receipts from the prior comparisons are additive only.
    for folder in [ROOT/'archive/reports/holdout_restricted/hushen1_cash_cost_vs_hushen2/attempt_20261028_213602/actions']:
        for path in folder.glob('*.json'):
            receipt=json.loads(path.read_text(encoding='utf-8'));key=receipt['key']
            if key in p['known']:continue
            add_receipt(p,receipt)
    assert p['calendar'][-1]>=end+pd.Timedelta(days=30)
    assert market.pipeline_identity(market.health(APP/'tracker/data'))[0]==identity
    signals.to_parquet(out/'SIGNALS.parquet',index=False)
    with (out/'INPUT_PACK.pkl').open('wb') as stream:pickle.dump(p,stream,pickle.HIGHEST_PROTOCOL)
    dump(out/'INPUT_AUDIT.json',dict(end=end,signals=len(signals),symbols=len(bars),raw_hashes=raw_inputs,
         pipeline_id=identity,source_pack=str(source),source_pack_sha256=sha(source)))
    print('PREPARED',len(signals),len(bars),str(end.date()),flush=True)

def add_receipt(p,r):
    assert r['error_code']=='0'
    key=r['key'];symbol,_=key.split('/');p['known'].add(key)
    for row in r['records']:
        if not row.get('dividOperateDate'):continue
        day=pd.Timestamp(row['dividOperateDate']);num=lambda k:float(str(row.get(k,'')).strip() or 0)
        p['actions'].setdefault((day,symbol),[]).append(dict(cash=num('dividCashPsBeforeTax'),stock=num('dividStocksPs')+num('dividReserveToStockPs'),
             taxable_stock=num('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or day),release=pd.Timestamp(row.get('dividStockMarketDate') or day)))

def initialize(out):
    with (Path(out)/'INPUT_PACK.pkl').open('rb') as stream:G['p']=pickle.load(stream)
    G['out']=Path(out);G['core']=engine()
    G['risk']=load('live_approx_risk',STRATEGY/'backtest/compute_risk_metrics.py')

def job(item):
    ordinal,start=item;p=G['p'];core=G['core'];end=p['end']
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=list(range(2020,end.year+1))
    curve=[];gaps=set()
    r,t=core.simulate(p['signals'].loc[p['signals'].date.ge(start)],p['bars'],p['calendar'],'C04_NEW',0.,30,'take4_stop1.5',4.,1.5,
        keep_trades=True,actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
    metric=G['risk'].recompute_metrics(c).iloc[0].to_dict()
    a=pd.DataFrame(r['fixed_order_attempts']);positions=r['terminal_positions'];pending=r['terminal_pending']
    residual=0.;value=0.
    for h in positions:
        mark=float(p['bars'][h['symbol']].loc[:end,'close'].iloc[-1])
        mv=h['frozen_value'] if h['frozen'] else h['shares']*mark
        residual+=mv+h['dividends']-h['entry_cost'];value+=mv
        if pd.Timestamp(h['deadline'])>end:assert pd.Timestamp(h['expiry_session'])>end
    assert abs(float(c.equity.iloc[-1])-100000-(float(t.pnl.sum()) if len(t) else 0)-residual)<1e-6
    assert abs(r['terminal_cash']+r['terminal_deferred']+r['terminal_receivables']+value-float(c.equity.iloc[-1]))<1e-6
    for tr in t.loc[t.reason.eq('expiry')].itertuples() if len(t) else []:
        deadline=pd.Timestamp(tr.entry_date)+pd.Timedelta(days=30)
        prior=max(d for d in p['calendar'] if d<=deadline)
        assert pd.Timestamp(tr.exit_date)>prior
    filled=int(a.filled_quantity.gt(0).sum()) if len(a) else 0
    zero=int(a.filled_quantity.eq(0).sum()) if len(a) else 0
    assert filled==r['filled_orders']==len(t)+len(positions)
    assert r['pending_orders_created']==filled+zero+r['expired_entry_orders']+len(pending)
    metric.update(ending_equity=float(c.equity.iloc[-1]),filled=filled,failed=zero+r['expired_entry_orders'],created=r['pending_orders_created'],
                  cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()) if len(a) else 0,
                  takes=int(t.reason.eq('take').sum()) if len(t) else 0,stops=int(t.reason.eq('stop').sum()) if len(t) else 0,
                  expiries=int(t.reason.eq('expiry').sum()) if len(t) else 0,terminal_positions=len(positions),terminal_pending=len(pending))
    dest=G['out']/'paths'/f'{ordinal:02d}_{str(start.date())}';dest.mkdir(parents=True,exist_ok=True)
    for name,frame in [('EQUITY',c),('TRADES',t),('ATTEMPTS',a)]:frame.to_parquet(dest/(name+'.parquet'),index=False)
    dump(dest/'TERMINAL.json',dict(holdings=positions,pending=pending,cash=r['terminal_cash'],deferred=r['terminal_deferred'],receivables=r['terminal_receivables']))
    dump(dest/'METRICS.json',metric)
    return metric,sorted(gaps)

def run(out,workers):
    out=Path(out)
    with (out/'INPUT_PACK.pkl').open('rb') as stream:p=pickle.load(stream)
    starts=[d for d in p['calendar'] if d.year==2020 and d.month<=3]
    assert len(starts)==58
    dump(out/'SOURCE_AUDIT.json',dict(engine_source=engine().source,starts=starts,workers=workers))
    results=[];gaps=set()
    with ProcessPoolExecutor(max_workers=workers,initializer=initialize,initargs=(str(out),)) as pool:
        futures=[pool.submit(job,(i,d)) for i,d in enumerate(starts,1)]
        for f in as_completed(futures):
            row,missing=f.result();results.append(row);gaps.update(missing)
            dump(out/'PROGRESS.json',dict(stage='backtest',completed=len(results),total=58,action_gaps=sorted(gaps),at=datetime.now().isoformat()))
            if len(results)%5==0:print('PATHS',len(results),58,'ACTION_GAPS',len(gaps),flush=True)
    dump(out/'ACTION_GAPS.json',sorted(gaps))
    if gaps:
        print('ACTION_COVERAGE_REQUIRED',len(gaps),flush=True)
        return
    m=pd.DataFrame(results).sort_values('start_ordinal');m.to_parquet(out/'START_METRICS.parquet',index=False)
    curves=pd.concat([pd.read_parquet(x) for x in sorted((out/'paths').glob('*/EQUITY.parquet'))],ignore_index=True)
    curves.to_parquet(out/'EQUITY_CURVES.parquet',index=False)
    keys=['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','ending_equity','filled','failed','cash_rejected','takes','stops','expiries','terminal_positions','terminal_pending']
    summary=dict(status='ok',start_population='2020Q1 full starts to current',starts=58,end=str(p['end'].date()),
         mean={k:float(m[k].mean()) for k in keys},median={k:float(m[k].median()) for k in keys},
         best=m.loc[m.cumulative_return.idxmax()].to_dict(),worst=m.loc[m.cumulative_return.idxmin()].to_dict(),
         earliest=m.iloc[0].to_dict(),positive_fraction=float(m.cumulative_return.gt(0).mean()),action_gaps=[])
    dump(out/'SUMMARY.json',summary)
    print(json.dumps(summary,ensure_ascii=False,default=str),flush=True)

def fetch_actions(out):
    out=Path(out);gaps=json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8'))
    if not gaps:return
    import socket,baostock as bs
    socket.setdefaulttimeout(15)
    with (out/'INPUT_PACK.pkl').open('rb') as stream:p=pickle.load(stream)
    folder=out/'actions';folder.mkdir(exist_ok=True)
    assert bs.login().error_code=='0'
    try:
        for key in gaps:
            symbol,year=key.split('/');res=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate')
            records=[]
            while res.error_code=='0' and res.next():records.append(dict(zip(res.fields,res.get_row_data())))
            assert res.error_code=='0',(key,res.error_msg)
            receipt=dict(key=key,error_code=res.error_code,records=records,fetched_at=datetime.now().isoformat())
            dump(folder/(key.replace('/','_')+'.json'),receipt);add_receipt(p,receipt)
            print('ACTION',key,len(records),flush=True)
    finally:bs.logout()
    with (out/'INPUT_PACK.pkl').open('wb') as stream:pickle.dump(p,stream,pickle.HIGHEST_PROTOCOL)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['prepare','run','fetch']);ap.add_argument('--out',required=True);ap.add_argument('--workers',type=int,default=3);a=ap.parse_args()
    if a.mode=='prepare':prepare(a.out)
    elif a.mode=='fetch':fetch_actions(a.out)
    else:run(a.out,a.workers)

if __name__=='__main__':main()
