"""Controlled fifth-occupied-slot preset share reduction; research only."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import argparse,json,sys,types
import numpy as np
import pandas as pd
import audit_hushen2_buy_wait as frozen
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load

G={}
VARIANTS=['current','fifth_minus100']

def initialize(end,out):
    frozen.initialize(end);p=frozen.G['pack'];base=frozen.G['core']
    for path in (Path(out)/'actions').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));assert r['error_code']=='0'
        if r['key'] in p['known']:continue
        p['known'].add(r['key']);symbol=r['key'].split('/')[0]
        for row in r['records']:
            if not row.get('dividOperateDate'):continue
            d=pd.Timestamp(row['dividOperateDate']);n=lambda k:float(str(row.get(k,'')).strip() or 0)
            p['actions'].setdefault((d,symbol),[]).append(dict(cash=n('dividCashPsBeforeTax'),stock=n('dividStocksPs')+n('dividReserveToStockPs'),
                taxable_stock=n('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d),source=str(path)))
    engines={}
    for v in VARIANTS:
        source=base.adapted_source
        old='trades: list[dict] = []';assert source.count(old)==1
        source=source.replace(old,old+'\n    preset_order_records=[]\n    reduced_below_lot=[]')
        quantity='int(budget // ((float(row["close"]) * (1.0 - entry_offset * float(row["atr_pct"]))) * (1.0 + slip) * 100)) * 100'
        anchor='pending.append(Pending(';assert source.count(anchor)==1
        prefix=f'original_quantity = {quantity}\n            is_fifth = free_slots == 1\n            preset_quantity = original_quantity - (100 if is_fifth and PRESET_MINUS100 else 0)\n            if PRESET_MINUS100 and is_fifth and preset_quantity < 100:\n                reduced_below_lot.append(dict(symbol=symbol,signal_date=date,original_quantity=original_quantity,preset_quantity=preset_quantity))\n                continue\n            '
        source=source.replace(anchor,prefix+anchor)
        old=f'quantity={quantity},';assert source.count(old)==1
        source=source.replace(old,'quantity=preset_quantity,')
        old='pending_orders_created += 1';assert source.count(old)==1
        source=source.replace(old,old+'\n            preset_order_records.append(dict(symbol=symbol,signal_date=date,occupied_slot=slots-free_slots+1,original_quantity=original_quantity,quantity=preset_quantity))')
        old='result["fixed_order_attempts"] = fixed_order_attempts';assert source.count(old)==1
        source=source.replace(old,old+'\n    result["preset_order_records"]=preset_order_records\n    result["reduced_below_lot"]=reduced_below_lot\n    result["terminal_positions"]=[asdict(h) for h in holdings]')
        core=types.ModuleType(v);core.__dict__.update(vars(base));core.PRESET_MINUS100=v=='fifth_minus100';core.asdict=asdict
        exec(compile(source,'<fifth_preset_'+v+'>','exec'),core.__dict__);core.trial_source=source;engines[v]=core
    risk=load('fifth_risk',STRATEGY/'backtest/compute_risk_metrics.py')
    G.update(pack=p,engines=engines,risk=risk)

def run(job):
    v,i,start=job;p=G['pack'];core=G['engines'][v];end=p['end'];last=end-pd.Timedelta(days=37)
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(2020,end.year+1))
    gaps=set();curve=[]
    r,t=core.simulate(p['signals'].loc[p['signals'].date.between(start,last)],p['bars'],[d for d in p['calendar'] if d<=end],
        'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,actions=p['actions'],known_action_keys=p['known'],
        coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    c=pd.DataFrame(curve);a=pd.DataFrame(r['fixed_order_attempts']);orders=pd.DataFrame(r['preset_order_records'])
    for f in (c,t,a,orders):f['start_ordinal']=i;f['start_date']=start
    h=r['terminal_positions'];residual=0.
    for x in h:
        mark=float(p['bars'][x['symbol']].loc[:end,'close'].iloc[-1]);value=x['frozen_value'] if x['frozen'] else x['shares']*mark
        residual+=value+x['dividends']-x['entry_cost']
    assert abs(c.equity.iloc[-1]-100000-t.pnl.sum()-residual)<1e-6
    filled=int(a.filled_quantity.gt(0).sum());zero=int(a.filled_quantity.eq(0).sum())
    assert filled==r['filled_orders']==len(t)+len(h)
    assert len(orders)==r['pending_orders_created']==filled+zero+r['expired_entry_orders']+r['pending_orders_at_end']
    fifth=orders.occupied_slot.eq(5)
    assert (orders.loc[~fifth,'original_quantity']==orders.loc[~fifth,'quantity']).all()
    if getattr(core,'PRESET_CASH_FIT',False):
        difference=orders.loc[fifth,'original_quantity']-orders.loc[fifth,'quantity']
        assert difference.ge(0).all() and difference.mod(100).eq(0).all()
    else:
        assert (orders.loc[fifth,'original_quantity']-orders.loc[fifth,'quantity']).eq(100 if v=='fifth_minus100' else 0).all()
    assert not r['pending_orders_at_end'] and r['peak_occupied_slots_eod']<=5
    m=G['risk'].recompute_metrics(c).iloc[0].to_dict()
    e=c.equity.to_numpy();returns=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
    assert abs((e/np.maximum.accumulate(e)-1).min()-m['maximum_drawdown'])<1e-12
    assert abs(np.sqrt(252)*returns.mean()/returns.std(ddof=0)-m['sharpe_zero_rf_252_ddof0'])<1e-10
    m.update(variant=v,ending_equity=float(e[-1]),created=r['pending_orders_created'],filled=filled,failed=zero+r['expired_entry_orders'],
        cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()),expired=r['expired_entry_orders'],
        take_count=int(t.reason.eq('take').sum()),stop_count=int(t.reason.eq('stop').sum()),expiry_count=int(t.reason.eq('expiry').sum()),
        fifth_orders=int(fifth.sum()),reduced_below_lot=len(r['reduced_below_lot']),terminal_positions=len(h),action_gaps=sorted(gaps))
    return v,m,c,t,a,orders,h,r['reduced_below_lot']

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--fetch-gaps',action='store_true');args=parser.parse_args()
    out=args.output or ROOT/'archive/reports/holdout_restricted/hushen2_fifth_minus100'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=True)
    if args.fetch_gaps:
        import baostock as bs
        assert bs.login().error_code=='0';folder=out/'actions';folder.mkdir(exist_ok=True)
        try:
            for key in json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8')):
                symbol,year=key.split('/');response=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');records=[]
                while response.error_code=='0' and response.next():records.append(dict(zip(response.fields,response.get_row_data())))
                assert response.error_code=='0';(folder/(key.replace('/','_')+'.json')).write_text(json.dumps(dict(key=key,error_code=response.error_code,records=records),ensure_ascii=False,indent=2),encoding='utf-8')
                print('RECEIPT',key,flush=True)
        finally:bs.logout()
    sys.path.insert(0,str(APP/'runtime'));sys.path.insert(0,str(APP/'tracker'));market=load('fifth_parent_market',APP/'tracker/market.py')
    health=market.health(APP/'tracker/data');end=health['market_date']
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for relative,expected in manifest[group].items():assert sha(GAME/relative)==expected
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',APP/'tracker/data/market_status.json',
        GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',STRATEGY/'model/manifest.json',APP/'tracker/service.py']
    before={str(p):sha(p) for p in protected}
    starts=[pd.Timestamp(d) for d in health['sessions'] if d.startswith('2020-') and d[5:7]<='03'];assert len(starts)==58
    names=['START_METRICS','EQUITY_CURVES','TRADES','ORDER_ATTEMPTS','PRESET_ORDERS'];frames={v:{n:[] for n in names} for v in VARIANTS};terminals={v:[] for v in VARIANTS};skips={v:[] for v in VARIANTS}
    jobs=[(v,i,s) for i,s in enumerate(starts,1) for v in VARIANTS]
    print('OUTPUT',out,'PATHS',len(jobs),'END',end,flush=True)
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(end,str(out))) as pool:
        for i,future in enumerate(as_completed([pool.submit(run,j) for j in jobs]),1):
            v,m,c,t,a,o,h,skip=future.result()
            for n,f in zip(names,[pd.DataFrame([m]),c,t,a,o]):frames[v][n].append(f)
            terminals[v].append(dict(start=m['start_date'],positions=h));skips[v].append(dict(start=m['start_date'],orders=skip))
            if i%20==0 or i==len(jobs):print('COMPLETE',i,len(jobs),flush=True)
    fields=['ending_equity','cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','created','filled','failed','cash_rejected','expired','take_count','stop_count','expiry_count','fifth_orders','reduced_below_lot','terminal_positions']
    rows=[];metrics={};gaps=set()
    for v in VARIANTS:
        folder=out/v;folder.mkdir(exist_ok=True)
        for n,parts in frames[v].items():
            f=pd.concat(parts,ignore_index=True).sort_values('start_ordinal');f.to_parquet(folder/(n+'.parquet'),index=False)
            if n=='START_METRICS':metrics[v]=f.reset_index(drop=True)
        m=metrics[v];gaps.update(k for keys in m.action_gaps for k in keys)
        for name,data in [('TERMINAL_POSITIONS',terminals[v]),('SKIPPED_ZERO_QUANTITY',skips[v])]:
            (folder/(name+'.json')).write_text(json.dumps(data,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
        rows.append(dict(variant=v,starts=len(m),means={k:float(m[k].mean()) for k in fields},median_cumulative_return=float(m.cumulative_return.median())))
    prior=ROOT/'archive/reports/holdout_restricted/hushen2_buy_wait/attempt_20261026_031013/PATH_COUNTS.parquet'
    old=pd.read_parquet(prior).sort_values('start_ordinal').reset_index(drop=True);base=metrics['current'];new=metrics['fifth_minus100']
    for k in ['created','filled','failed','cash_rejected','expired','ending_equity']:assert (base[k]-old[k]).abs().max()<1e-8,k
    unchanged={p:sha(p)==h for p,h in before.items()};assert all(unchanged.values()) and market.health(APP/'tracker/data')['audit_sha256']==health['audit_sha256']
    (out/'ACTION_GAPS.json').write_text(json.dumps(sorted(gaps)),encoding='utf-8')
    report=dict(status='verified' if not gaps else 'incomplete_action_coverage',end=end,rows=rows,paths=116,action_gaps=sorted(gaps),
        paired_annual_return_improved_paths=int(new.annualized_return.gt(base.annualized_return).sum()),baseline_regression_passed=True,
        protected_unchanged=unchanged,software_changed=False,baseline_changed=False,input_pack_sha256=before[str(CASES/'INPUT_PACK.pkl')],
        protocol='58Q1-2020 empty100000 accounts to same local committed end. Fifth occupancy counts holdings+pending at order creation,not fifth lifetime trade nor actual fifth fill. Only fifth-slot preset quantity reduced exactly100 once before submission; if resulting<100 do not submit/occupy slot; no dynamic resizing or retry. Other quantities20% budget,ATR025/top3/no refill,7/30calendar,stop-first,T+1,fixedIOC,2%capacity,originalfees/slip,expiryclose,37daytail unchanged. No production writes,no tuning. FrozenOct22 signals plus verified committed raw tail. Overlapping paths not independent.')
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),**report),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
