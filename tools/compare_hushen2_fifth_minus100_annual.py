"""Q1 full-start annual/2025-continuous comparison, fifth-slot preset only."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
import argparse,json,sys
import numpy as np
import pandas as pd
import test_hushen2_fifth_minus100 as trial
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load

VARIANTS=['current','fifth_minus100']

def initialize(end,out):
    trial.initialize(end,out)

def run(job):
    v,group,i,start,end=job;trial.G['pack']['end']=end
    v,m,c,t,a,o,h,skip=trial.run((v,i,start));m['group']=group
    return v,group,m,c,t,a,o,h,skip

def fetch_gaps(out):
    import baostock as bs
    folder=out/'actions';folder.mkdir(exist_ok=True);assert bs.login().error_code=='0'
    try:
        for key in json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8')):
            symbol,year=key.split('/');response=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');records=[]
            while response.error_code=='0' and response.next():records.append(dict(zip(response.fields,response.get_row_data())))
            assert response.error_code=='0'
            (folder/(key.replace('/','_')+'.json')).write_text(json.dumps(dict(key=key,error_code=response.error_code,fields=response.fields,records=records,fetched_at=datetime.now().isoformat()),ensure_ascii=False,indent=2),encoding='utf-8')
            print('ACTION_RECEIPT',key,flush=True)
    finally:bs.logout()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--fetch-gaps',action='store_true');args=parser.parse_args()
    out=args.output or ROOT/'archive/reports/holdout_restricted/hushen2_fifth_minus100_annual'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=True)
    if args.fetch_gaps:fetch_gaps(out)
    sys.path.insert(0,str(APP/'runtime'));sys.path.insert(0,str(APP/'tracker'));market=load('fifth_annual_parent_market',APP/'tracker/market.py')
    health=market.health(APP/'tracker/data');end=pd.Timestamp(health['market_date']);calendar=[pd.Timestamp(d) for d in health['sessions']]
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['signal_filter']['minimum_atr']==.025 and not selection['selection']['signal_filter']['refill']
    assert selection['selection']['slots']==5
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for relative,expected in manifest[group].items():assert sha(GAME/relative)==expected
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',APP/'tracker/data/market_status.json',
        GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',STRATEGY/'model/manifest.json',APP/'tracker/service.py']
    before={str(p):sha(p) for p in protected}
    groups=[(str(y),y,pd.Timestamp(f'{y}-12-31') if y<2026 else end) for y in range(2020,2027)]+[('2025_to_current',2025,end)]
    names=['START_METRICS','EQUITY_CURVES','TRADES','ORDER_ATTEMPTS','PRESET_ORDERS']
    frames={(v,g):{n:[] for n in names} for g,y,stop in groups for v in VARIANTS};terminals={key:[] for key in frames};skips={key:[] for key in frames}
    jobs=[(v,g,i,start,stop) for g,y,stop in groups for i,start in enumerate([d for d in calendar if d.year==y and d.month<=3],1) for v in VARIANTS]
    print('OUTPUT',out,'PATHS',len(jobs),'END',end,flush=True);gaps=set()
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(str(end.date()),str(out))) as pool:
        for i,future in enumerate(as_completed([pool.submit(run,j) for j in jobs]),1):
            v,g,m,c,t,a,o,h,skip=future.result();gaps.update(m['action_gaps'])
            for n,f in zip(names,[pd.DataFrame([m]),c,t,a,o]):frames[(v,g)][n].append(f)
            terminals[(v,g)].append(dict(start=m['start_date'],positions=h));skips[(v,g)].append(dict(start=m['start_date'],orders=skip))
            if i%100==0 or i==len(jobs):print('COMPLETE',i,len(jobs),'GAPS',sorted(gaps),flush=True)
    rows=[];regression=[];paired={};metrics={};risk=load('fifth_annual_risk',STRATEGY/'backtest/compute_risk_metrics.py')
    fields=['ending_equity','cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','created','filled','failed','cash_rejected','expired','take_count','stop_count','expiry_count','fifth_orders','reduced_below_lot','terminal_positions']
    for group,year,stop in groups:
        for v in VARIANTS:
            folder=out/group/v;folder.mkdir(parents=True,exist_ok=True);saved={}
            for n,parts in frames[(v,group)].items():
                f=pd.concat(parts,ignore_index=True).sort_values('start_ordinal');f.to_parquet(folder/(n+'.parquet'),index=False);saved[n]=f
            m=saved['START_METRICS'].reset_index(drop=True);c=saved['EQUITY_CURVES'];t=saved['TRADES'];a=saved['ORDER_ATTEMPTS'];o=saved['PRESET_ORDERS'];metrics[(v,group)]=m
            calc=risk.recompute_metrics(c)
            for k in ['annualized_return','cumulative_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']:assert (calc[k]-m[k]).abs().max()<1e-12
            expected=[d for d in calendar if d.year==year and d.month<=3]
            assert len(m)==len(expected) and list(pd.to_datetime(m.start_date))==expected
            for r in m.itertuples():
                tr=t.loc[t.start_ordinal.eq(r.start_ordinal)];at=a.loc[a.start_ordinal.eq(r.start_ordinal)]
                assert len(tr)+r.terminal_positions==r.filled==at.filled_quantity.gt(0).sum()
                assert r.created==r.filled+r.failed
                assert r.cash_rejected==at.status.eq('insufficient_cash_rejected').sum()
            if v=='current' and year<2026 and group!='2025_to_current':
                old=pd.read_parquet(CASES/group/'START_METRICS.parquet').sort_values('start_ordinal').reset_index(drop=True)
                for newk,oldk in [('cumulative_return','cumulative_return'),('annualized_return','annualized_return'),('maximum_drawdown','maximum_drawdown'),
                    ('sharpe_zero_rf_252_ddof0','sharpe_zero_rf_252_ddof0'),('filled','filled_orders'),('created','pending_orders_created'),('failed','unfilled_orders')]:
                    assert (m[newk]-old[oldk]).abs().max()<1e-8,(group,newk)
                regression.append(dict(group=group,matches_retained_frozen_annual=True))
            for name,data in [('TERMINAL_POSITIONS',terminals[(v,group)]),('SKIPPED_ZERO_QUANTITY',skips[(v,group)])]:
                (folder/(name+'.json')).write_text(json.dumps(data,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
            rows.append(dict(group=group,variant=v,starts=len(m),end=str(m.end_date.iloc[0]),means={k:float(m[k].mean()) for k in fields}))
        base=metrics[('current',group)];new=metrics[('fifth_minus100',group)]
        paired[group]=dict(starts=len(base),annual_improved=int(new.annualized_return.gt(base.annualized_return).sum()))
    unchanged={p:sha(p)==h for p,h in before.items()};assert all(unchanged.values()) and market.health(APP/'tracker/data')['audit_sha256']==health['audit_sha256']
    (out/'ACTION_GAPS.json').write_text(json.dumps(sorted(gaps)),encoding='utf-8')
    report=dict(status='verified' if not gaps else 'incomplete_action_coverage',end=str(end.date()),paths=len(jobs),rows=rows,paired_improvements=paired,
        action_gaps=sorted(gaps),baseline_regression_checks=regression,protected_unchanged=unchanged,baseline_changed=False,software_changed=False,
        input_pack_sha256=before[str(CASES/'INPUT_PACK.pkl')],market_audit=health['audit'],
        protocol='2020-2025 each Q1 all trading starts to own nominal Dec31,2026Q1 to latest committed end,2025Q1 continuous to same end. Each empty100000,5slots20%. Compare current ATR025-only versus fifth occupancy(holdings+pending) preset100share reduction,skip if resulting<100. No trigger resizing/retry. Original fixedIOC,priceTR,7/30calendar,stop-first,T+1,2% volume,originalfees/slip,expiryclose,37caldaytail unchanged. Same frozen Oct22 extended snapshot signal vintage across years,committed raw tail only. No fitting or pricefilter; retrospective not blind; overlapping starts not independent. No software/account/baseline changes.')
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),**report),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
