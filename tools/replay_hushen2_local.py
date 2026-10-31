"""Read-only production-identity checked historical replay after repository split."""
from pathlib import Path
from datetime import datetime
from dataclasses import asdict
import argparse,hashlib,importlib.util,json,pickle,sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
STRATEGY=ROOT/'沪深2研究'
APP=ROOT/'沪深实盘工作台'
GAME=ROOT/'沪深2研究/K线练习'
CASES=GAME/'frozen_inputs/cases'

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def simulate(core,p,start,end,out,risk):
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end-pd.Timedelta(days=37);core.YEARS=[2026]
    signals=p['signals'].loc[p['signals'].date.between(start,core.LAST_SIGNAL_DATE)]
    gaps=set();curve=[]
    r,t=core.simulate(signals,p['bars'],[d for d in p['calendar'] if d<=end],'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
        keep_trades=True,actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    c=pd.DataFrame(curve);c['start_ordinal']=1;c['start_date']=start
    a=pd.DataFrame(r['fixed_order_attempts']);h=r['terminal_positions']
    residual=0.
    for x in h:
        mark=float(p['bars'][x['symbol']].loc[:end,'close'].iloc[-1]);value=x['frozen_value'] if x['frozen'] else x['shares']*mark
        residual+=value+x['dividends']-x['entry_cost']
    assert abs(c.equity.iloc[-1]-100000-t.pnl.sum()-residual)<1e-6
    fills=int(a.filled_quantity.gt(0).sum());zero=int(a.filled_quantity.eq(0).sum())
    assert r['filled_orders']==fills==len(t)+len(h)
    assert r['pending_orders_created']==fills+zero+r['expired_entry_orders']+r['pending_orders_at_end']
    m=risk.recompute_metrics(c).iloc[0].to_dict()
    e=c.equity.to_numpy();returns=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
    assert abs((e/np.maximum.accumulate(e)-1).min()-m['maximum_drawdown'])<1e-12
    assert abs(np.sqrt(252)*returns.mean()/returns.std(ddof=0)-m['sharpe_zero_rf_252_ddof0'])<1e-10
    m.update(ending_equity=float(e[-1]),filled_orders=fills,unfilled_orders=zero+r['expired_entry_orders'],
        cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()),expired_entry_orders=r['expired_entry_orders'],
        take_count=int(t.reason.eq('take').sum()),stop_count=int(t.reason.eq('stop').sum()),expiry_count=int(t.reason.eq('expiry').sum()),
        terminal_positions=len(h),pending_orders=r['pending_orders_at_end'],last_signal_cutoff=str(core.LAST_SIGNAL_DATE.date()),action_gaps=sorted(gaps))
    folder=out/str(end.date());folder.mkdir()
    c.to_parquet(folder/'EQUITY_CURVE.parquet',index=False);t.to_parquet(folder/'TRADES.parquet',index=False);a.to_parquet(folder/'ORDER_ATTEMPTS.parquet',index=False)
    (folder/'TERMINAL_POSITIONS.json').write_text(json.dumps(h,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    return m,c,t,a

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--start',default='2026-01-02')
    parser.add_argument('--frozen-only',action='store_true',help='Replay only through the immutable input cutoff; do not extrapolate signals')
    args=parser.parse_args()
    requested=pd.Timestamp(args.start)
    sys.path.insert(0,str(APP/'tracker'));sys.path.insert(0,str(APP/'runtime'))
    market=load('hushen2_local_market',APP/'tracker/market.py');health=market.health(APP/'tracker/data')
    end=pd.Timestamp(health['market_date']);sessions=[pd.Timestamp(d) for d in health['sessions']]
    start=min(d for d in sessions if d>=requested);assert start.year==2026
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',
        APP/'tracker/data/market_status.json',APP/'tracker/service.py',APP/'tracker/store.py',
        GAME/'PACKAGE_MANIFEST.json',GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl']
    for base in (STRATEGY,APP):protected+=list((base/'model').glob('*'))+list((base/'runtime').glob('*.py'))
    before={str(p):sha(p) for p in protected if p.is_file()}
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['slots']==5 and selection['selection']['initial_cash']==100000
    assert selection['selection']['signal_filter']['minimum_atr']==.025 and not selection['selection']['signal_filter']['refill']
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for relative,expected in manifest[group].items():assert sha(GAME/relative)==expected
    assert sha(GAME/'runtime/run_batch.py')==selection['research_provenance_sha256']['relocated_execution_engine_source'].lower()
    for base in (STRATEGY,APP):
        model=json.loads((base/'model/manifest.json').read_text(encoding='utf-8'))
        for name in ('utility','pen025','pen100'):assert sha(base/'model'/f'{name}.txt')==model[name].lower()
    with (CASES/'INPUT_PACK.pkl').open('rb') as f:p=pickle.load(f)
    frozen_end=pd.Timestamp(p['end']);assert start<=frozen_end<=end
    if args.frozen_only:end=frozen_end
    out=STRATEGY/'results/holdout_restricted/hushen2_local_replay'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True)
    print('OUTPUT',out,'REQUESTED',requested,'ACTUAL_START',start,'FROZEN_END',frozen_end,'REPLAY_END',end,flush=True)
    adapter=load('local_fixed_ioc',GAME/'runtime/baseline_fixed_ioc.py');original=load('local_frozen_core',GAME/'runtime/run_batch.py')
    core=adapter.fixed_ioc_engine(original,manual_expiry_open=False,filled_slots=False)
    anchor='result["fixed_order_attempts"] = fixed_order_attempts';assert core.adapted_source.count(anchor)==1
    core.asdict=asdict;source=core.adapted_source.replace(anchor,anchor+'\n    result["terminal_positions"] = [asdict(x) for x in holdings]')
    exec(compile(source,'<terminal_diagnostics_only>','exec'),core.__dict__)
    (out/'SIMULATE_SOURCE.txt').write_text(source,encoding='utf-8')
    risk=load('local_risk_recompute',STRATEGY/'backtest/compute_risk_metrics.py')
    old,c,t,a=simulate(core,p,start,frozen_end,out,risk)
    reference=pd.read_parquet(CASES/'2026/START_METRICS.parquet');reference=reference.loc[pd.to_datetime(reference.start_date).eq(start)].iloc[0]
    for k in ['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','filled_orders','take_count','stop_count','expiry_count']:
        assert abs(float(reference[k])-float(old[k]))<1e-10,k
    rows=[old];local_hashes={};extended=[]
    if end>frozen_end:
        assert (end-frozen_end).days<=3,'Frozen signals cannot be extrapolated beyond short verified extension'
        cutoff=end-pd.Timedelta(days=37)
        assert p['signals'].date.max()>=cutoff
        symbols=sorted(p['signals'].loc[p['signals'].date.between(start,cutoff),'symbol'].unique())
        numeric=['open','high','low','close','preclose','volume','amount']
        for symbol in symbols:
            path=market.DATA/'raw'/symbol[-2:]/f'{symbol}.parquet'
            if not path.exists():
                assert p['delists'].get(symbol,pd.Timestamp.max)<=frozen_end,symbol
                continue
            local_hashes[str(path)]=sha(path)
            b=pd.read_parquet(path);b.date=pd.to_datetime(b.date)
            for k in numeric:b[k]=pd.to_numeric(b[k],errors='raise')
            b=b.set_index('date').sort_index();frozen=p['bars'][symbol]
            overlap=frozen.index[(frozen.index>=start)&(frozen.index<=frozen_end)]
            common=b.index.intersection(overlap)
            assert len(common)==len(overlap),(symbol,'missing historical raw bars')
            for k in numeric:assert np.allclose(b.loc[common,k],frozen.loc[common,k],rtol=1e-10,atol=1e-7,equal_nan=True),(symbol,k)
            tail=b.loc[(b.index>frozen_end)&(b.index<=end)]
            if len(tail):p['bars'][symbol]=pd.concat([frozen,tail[frozen.columns]],axis=0);extended.append(symbol)
        p['calendar']=sorted(set(p['calendar'])|{d for d in sessions if frozen_end<d<=end})
        p['end']=end
        latest,c,t,a=simulate(core,p,start,end,out,risk);rows.append(latest)
    final_health=market.health(APP/'tracker/data');assert final_health['audit_sha256']==health['audit_sha256']
    unchanged={path:sha(path)==digest for path,digest in before.items()};assert all(unchanged.values())
    assert all(sha(path)==digest for path,digest in local_hashes.items())
    gaps=sorted({key for row in rows for key in row['action_gaps']})
    report=dict(status='verified' if not gaps else 'incomplete_action_coverage',requested_start=str(requested.date()),actual_start=str(start.date()),
        end=str(end.date()),rows=rows,frozen_reference_exact=True,action_gaps=gaps,extended_raw_symbols=extended,raw_input_hashes=local_hashes,
        market_health={k:v for k,v in health.items() if k!='sessions'},protected_unchanged=unchanged,protected_before_hashes=before,
        protocol='Current ATR025 original top3/no refill,100000,5slots20%,fixedIOC,7/30calendar,2% volume,originalcommission .0003min5,sellstamp .001,slippage .002,expiryclose,stop-first,T+1,37day no-new-order tail. No pricefilter,no retraining,no production/account writes. Frozen Oct22 inputs relocated in practice package, latest committed raw tail only appended after overlapping2026 raw bars compared. Signal vintage held fixed,not regenerated from latest qfq. January2 is exchange holiday,first eligible session January5. Not blind testing. Latest endpoint benchmark not extrapolated.')
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),status=report['status'],rows=rows,action_gaps=gaps,extended_symbols=len(extended),protected_unchanged=all(unchanged.values())),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
