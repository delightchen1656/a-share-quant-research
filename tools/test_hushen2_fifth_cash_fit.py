"""Fifth occupied slot: fit shares to known next-session cash at order creation."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
import argparse,json,sys,types
import numpy as np
import pandas as pd
import test_hushen2_fifth_minus100 as trial
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load

PRIOR=ROOT/'archive/reports/holdout_restricted/hushen2_fifth_minus100/attempt_20261026_031615'
LABEL='fifth_cash_fit'

def initialize(end,out):
    trial.initialize(end,out);base=trial.G['engines']['current'];source=base.trial_source
    old='preset_quantity = original_quantity - (100 if is_fifth and PRESET_MINUS100 else 0)';assert source.count(old)==1
    source=source.replace(old,'''preset_quantity = original_quantity
            estimated_buy_price = float(row["close"]) * (1.0-entry_offset*float(row["atr_pct"])) * (1.0+slip)
            creation_cash_estimate = cash + deferred_cash
            if is_fifth:
                while preset_quantity >= 100:
                    estimated_notional = preset_quantity * estimated_buy_price
                    if estimated_notional + commission(estimated_notional, comm_rate, comm_min) <= creation_cash_estimate + 1e-9:
                        break
                    preset_quantity -= 100''')
    old='if PRESET_MINUS100 and is_fifth and preset_quantity < 100:';assert source.count(old)==1
    source=source.replace(old,'if is_fifth and preset_quantity < 100:')
    old='preset_order_records.append(dict(symbol=symbol,signal_date=date,occupied_slot=slots-free_slots+1,original_quantity=original_quantity,quantity=preset_quantity))';assert source.count(old)==1
    source=source.replace(old,old[:-2]+',estimated_buy_price=estimated_buy_price,creation_cash_estimate=creation_cash_estimate,holdings_at_creation=len(holdings),pending_after_creation=len(pending)))')
    core=types.ModuleType(LABEL);core.__dict__.update(vars(base));core.PRESET_CASH_FIT=True
    exec(compile(source,'<fifth_creation_cash_fit_only>','exec'),core.__dict__);core.trial_source=source
    trial.G['engines'][LABEL]=core

def run(job):
    i,start=job
    return trial.run((LABEL,i,start))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    prior=json.loads((PRIOR/'SUMMARY.json').read_text(encoding='utf-8'));assert prior['status']=='verified'
    sys.path.insert(0,str(APP/'runtime'));sys.path.insert(0,str(APP/'tracker'));market=load('cashfit_parent_market',APP/'tracker/market.py')
    health=market.health(APP/'tracker/data');end=health['market_date'];assert end==prior['end'],'Use same committed endpoint for paired comparison'
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for relative,expected in manifest[group].items():assert sha(GAME/relative)==expected
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',APP/'tracker/data/market_status.json',
        GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',STRATEGY/'model/manifest.json',APP/'tracker/service.py']
    before={str(p):sha(p) for p in protected};assert before[str(CASES/'INPUT_PACK.pkl')]==prior['input_pack_sha256']
    out=args.output or ROOT/'archive/reports/holdout_restricted/hushen2_fifth_cash_fit'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=True)
    metrics=pd.read_parquet(PRIOR/'current/START_METRICS.parquet').sort_values('start_ordinal')
    names=['START_METRICS','EQUITY_CURVES','TRADES','ORDER_ATTEMPTS','PRESET_ORDERS'];frames={n:[] for n in names};terminals=[];skipped=[];gaps=set()
    print('OUTPUT',out,'FRESH_PATHS',len(metrics),'END',end,flush=True)
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(end,str(out))) as pool:
        for i,future in enumerate(as_completed([pool.submit(run,(int(r.start_ordinal),pd.Timestamp(r.start_date))) for r in metrics.itertuples()]),1):
            v,m,c,t,a,o,h,skip=future.result();gaps.update(m['action_gaps'])
            for n,f in zip(names,[pd.DataFrame([m]),c,t,a,o]):frames[n].append(f)
            terminals.append(dict(start=m['start_date'],positions=h));skipped.append(dict(start=m['start_date'],orders=skip))
            if i%10==0 or i==len(metrics):print('COMPLETE',i,len(metrics),'GAPS',sorted(gaps),flush=True)
    folder=out/LABEL;folder.mkdir(exist_ok=True)
    saved={}
    for n,parts in frames.items():
        f=pd.concat(parts,ignore_index=True).sort_values('start_ordinal');f.to_parquet(folder/(n+'.parquet'),index=False);saved[n]=f
    for name,data in [('TERMINAL_POSITIONS',terminals),('SKIPPED_ZERO_QUANTITY',skipped)]:
        (folder/(name+'.json')).write_text(json.dumps(data,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    m=saved['START_METRICS'].sort_values('start_ordinal').reset_index(drop=True);c=saved['EQUITY_CURVES'];o=saved['PRESET_ORDERS'];t=saved['TRADES'];a=saved['ORDER_ATTEMPTS']
    fifth=o.loc[o.occupied_slot.eq(5)].copy();fifth['reduction']=fifth.original_quantity-fifth.quantity
    cost=lambda q,price:q*price+np.maximum(5.,q*price*.0003)
    assert cost(fifth.quantity,fifth.estimated_buy_price).le(fifth.creation_cash_estimate+1e-8).all()
    reduced=fifth.loc[fifth.reduction.gt(0)]
    assert cost(reduced.quantity+100,reduced.estimated_buy_price).gt(reduced.creation_cash_estimate+1e-9).all()
    assert (o.loc[o.occupied_slot.ne(5),'original_quantity']==o.loc[o.occupied_slot.ne(5),'quantity']).all()
    risk=load('cashfit_saved_risk',STRATEGY/'backtest/compute_risk_metrics.py');calc=risk.recompute_metrics(c)
    for k in ['annualized_return','cumulative_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']:assert (calc[k]-m[k]).abs().max()<1e-12
    for r in m.itertuples():
        tr=t.loc[t.start_ordinal.eq(r.start_ordinal)];at=a.loc[a.start_ordinal.eq(r.start_ordinal)]
        assert len(tr)+r.terminal_positions==r.filled==at.filled_quantity.gt(0).sum()
        assert r.created==r.filled+r.failed
    fields=list(prior['rows'][0]['means']);row=dict(variant=LABEL,starts=len(m),means={k:float(m[k].mean()) for k in fields},median_cumulative_return=float(m.cumulative_return.median()))
    rows=prior['rows']+[row]
    annual_comparisons={}
    for label in ['current','fifth_minus100']:
        old=pd.read_parquet(PRIOR/label/'START_METRICS.parquet').sort_values('start_ordinal').reset_index(drop=True)
        annual_comparisons[label]=int(m.annualized_return.gt(old.annualized_return).sum())
    assert all(sha(p)==digest for p,digest in before.items()) and market.health(APP/'tracker/data')['audit_sha256']==health['audit_sha256']
    (out/'ACTION_GAPS.json').write_text(json.dumps(sorted(gaps)),encoding='utf-8')
    report=dict(status='verified' if not gaps else 'incomplete_action_coverage',end=end,fresh_paths=58,rows=rows,action_gaps=sorted(gaps),
        comparisons_improved_paths=annual_comparisons,prior_results=str(PRIOR/'SUMMARY.json'),prior_results_sha256=sha(PRIOR/'SUMMARY.json'),
        reduction_stats=dict(fifth_orders=len(fifth),reduced_orders=len(reduced),mean_reduced_orders_per_path=len(reduced)/58,
            reduction_share_quantiles={str(q):float(reduced.reduction.quantile(q)) for q in [0,.25,.5,.75,.9,1]}),
        checks=dict(saved_risk_recomputed=True,quantity_fits_known_cash_at_creation=True,one_more_lot_would_not_fit_when_reduced=True,
            nonfifth_quantities_unchanged=True,protected_unchanged=True,software_changed=False,baseline_changed=False),
        input_pack_sha256=before[str(CASES/'INPUT_PACK.pkl')],
        protocol='Same58Q1-2020 paths and frozen input vintage as prior current/minus100 trial. Fifth occupied slot counts holdings+pending at creation. Only fifth preset shares stepped down100 until trigger*(1+.002) notional+original commission .0003min5 fits cash+known deferred sales released next session; if<100 skip order. No other pending cash reservation. Shares fixed after placement,NO trigger-time resizing or retry. Other ATR025/top3/no refill,5slots20%,7/30calendar,stop-first,T+1,fixedIOC,2%volume,originalfees/slip,expiryclose,37daytail unchanged. No optimization/deployment. Prior two variants reused with identical input hash/endpoint; latest variant freshly rerun.')
    (out/'SUMMARY.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),**report),default=str,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
