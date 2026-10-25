"""Frozen P12 duplicate-symbol lots, slots 5..10; research only, no production writes."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from collections import Counter
from pathlib import Path
from datetime import datetime
import argparse,json,pickle
import pandas as pd
import numpy as np
from run_june2020_starts import BASE,ROOT,ARCHIVE,module
from baseline_fixed_ioc import fixed_ioc_engine
from compute_risk_metrics import recompute_metrics
from research_single_filters_pre2025 import digest,save
from run_pair_top5_post2024 import add_receipt

SOURCE=BASE/'results/holdout_restricted/retained_four_post2024/attempt_20261022_191355'
END=pd.Timestamp('2026-10-21');G={}
COUNTS={2020:58,2021:58,2022:58,2023:59,2024:58,2025:57,2026:56}


def repeat_engine(core):
    engine=fixed_ioc_engine(core,manual_expiry_open=False,filled_slots=False)
    source=engine.adapted_source
    changes=[
        ('skipped_duplicate_symbol = 0','skipped_duplicate_symbol = 0\n    repeated_signal_orders_created = 0'),
        ('if p.symbol in occupied_symbols:\n                continue','# Duplicate-symbol lots may fill independently.'),
        ('if symbol in occupied_symbols:\n                skipped_duplicate_symbol += 1\n                continue','if symbol in occupied_symbols:\n                repeated_signal_orders_created += 1'),
        ('still_pending: list[Pending] = []','still_pending: list[Pending] = []\n        symbol_volume_used = {}'),
        ('requested_quantity=p.quantity, filled_quantity=0, status="no_fill_remainder_cancelled")',
         'requested_quantity=p.quantity, filled_quantity=0, status="no_fill_remainder_cancelled", bar_volume=float(bar["volume"]), open_lots_before=sum(h.symbol == p.symbol for h in holdings))'),
        ('capacity = int((float(bar["volume"]) * 0.02) // 100) * 100',
         'capacity = max(0, int((float(bar["volume"]) * 0.02) // 100) * 100 - symbol_volume_used.get(p.symbol, 0))'),
        ('cash -= cost','cash -= cost\n            symbol_volume_used[p.symbol] = symbol_volume_used.get(p.symbol, 0) + shares'),
        ('"date": date,\n                "equity":','"date": date,\n                "held_lots": len(holdings),\n                "pending_lots": len(pending),\n                "max_symbol_lots": max(Counter(h.symbol for h in holdings).values(), default=0),\n                "equity":'),
        ('result["fixed_order_attempts"] = fixed_order_attempts','result["fixed_order_attempts"] = fixed_order_attempts\n    result["repeated_signal_orders_created"] = repeated_signal_orders_created')]
    for old,new in changes:
        assert source.count(old)==1,('Frozen engine changed',old,source.count(old));source=source.replace(old,new)
    engine.Counter=Counter
    exec(compile(source,'<p12_duplicate_lot_adapter>','exec'),engine.__dict__)
    engine.adapted_source=source
    return engine


def initialize(out):
    out=Path(out)
    with (out/'INPUT_PACK.pkl').open('rb') as f:G.update(pickle.load(f))
    original=module('p12_repeat_worker',ARCHIVE/'research/run_batch.py')
    G.update(out=out,repeat=repeat_engine(original),control=fixed_ioc_engine(original,manual_expiry_open=False,filled_slots=False))


def run(job):
    slots,group,year,end,duplicate=job
    label=f'repeat_{slots}' if duplicate else 'control_5'
    folder=G['out']/label/group;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'SUMMARY.json').exists():
        retained=json.loads((folder/'SUMMARY.json').read_text(encoding='utf-8'))
        if not retained['action_gaps']:return retained
    core=G['repeat'] if duplicate else G['control']
    calendar=[d for d in G['calendar'] if d<=end];last=end-pd.Timedelta(days=37)
    starts=[d for d in calendar if d.year==year and d.month<=3];assert len(starts)==COUNTS[year]
    metrics=[];curves=[];trades=[];attempts=[];all_gaps=set()
    for ordinal,start in enumerate(starts,1):
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(year,end.year+1))
        gaps=set();curve=[]
        result,t=core.simulate(G['signals'].loc[G['signals'].date.between(start,last)],G['bars'],calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
            keep_trades=True,actions=G['actions'],known_action_keys=G['known'],coverage_sink=gaps,delist_dates=G['delists'],slots=slots,equity_curve_sink=curve)
        c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
        a=pd.DataFrame(result['fixed_order_attempts']);a['start_ordinal']=ordinal;a['start_date']=start
        assert not a.duplicated(['symbol','signal_date']).any()
        filled=int(a.filled_quantity.gt(0).sum());zero=int(a.filled_quantity.eq(0).sum());unfilled=zero+result['expired_entry_orders']
        counts=t.reason.value_counts().to_dict()
        assert result['filled_orders']==filled==len(t)==sum(counts.values())
        assert result['pending_orders_created']==filled+unfilled
        assert result['peak_occupied_slots_eod']<=slots
        assert not result['open_positions_at_end'] and not result['pending_orders_at_end']
        assert abs(c.equity.iloc[-1]-100000-t.pnl.sum())<1e-6
        m=recompute_metrics(c).iloc[0].to_dict();actual=c.date.iloc[-1]
        benchmark=(G['index'].loc[actual]/G['index'].loc[start])**(365/(actual-start).days)-1
        m.update(annualized_excess=m['annualized_return']-benchmark,benchmark_annualized=benchmark,
            pending_orders_created=result['pending_orders_created'],filled_orders=filled,unfilled_orders=unfilled,
            expired_entry_orders=result['expired_entry_orders'],failed_trigger_orders=zero,
            take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
            repeat_signal_orders=result.get('repeated_signal_orders_created',0),
            repeat_buy_fills=int(a.loc[a.filled_quantity.gt(0),'open_lots_before'].gt(0).sum()) if duplicate else 0,
            peak_same_symbol_lots=int(c.max_symbol_lots.max()) if duplicate else 1,
            average_occupied_slots=result['average_occupied_slots_eod'],peak_occupied_slots=result['peak_occupied_slots_eod'],
            open_positions_at_end=0,pending_orders_at_end=0,action_gaps=sorted(gaps))
        if duplicate:
            assert result['skipped_duplicate_symbol']==0
            for (symbol,day),aa in a.groupby(['symbol','date']):
                assert aa.filled_quantity.sum()<=int((aa.bar_volume.iloc[0]*.02)//100)*100
        metrics.append(m);curves.append(c);t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t);attempts.append(a);all_gaps.update(gaps)
    m=pd.DataFrame(metrics)
    for filename,frame in [('START_METRICS',m),('EQUITY_CURVES',pd.concat(curves,ignore_index=True)),('TRADES',pd.concat(trades,ignore_index=True)),('FIXED_ORDER_ATTEMPTS',pd.concat(attempts,ignore_index=True))]:frame.to_parquet(folder/(filename+'.parquet'),index=False)
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0','pending_orders_created','filled_orders','unfilled_orders','expired_entry_orders','failed_trigger_orders','take_count','stop_count','expiry_count','repeat_signal_orders','repeat_buy_fills','peak_same_symbol_lots','average_occupied_slots']
    report=dict(slots=slots,duplicate=duplicate,group=group,runs=len(starts),end=str(actual.date()),last_signal_cutoff=str(last.date()),
        means={k:float(m[k].mean()) for k in keys},positive_start_fraction=float(m.cumulative_return.gt(0).mean()),beat_sse_fraction=float(m.annualized_excess.gt(0).mean()),
        folder=str(folder.relative_to(G['out'])),action_gaps=sorted(all_gaps))
    save(folder/'SUMMARY.json',report);return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);p.add_argument('--workers',type=int,default=4);p.add_argument('--extra-actions',action='append',type=Path,default=[]);args=p.parse_args()
    parent=BASE/'results/holdout_restricted/p12_repeat_slots'
    out=args.output or parent/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    assert out.resolve().parent==parent.resolve();out.mkdir(parents=True,exist_ok=bool(args.output));print('OUTPUT',out,flush=True)
    protected=[BASE/'CURRENT_SELECTION.json',BASE/'model/manifest.json',*sorted((BASE/'model').glob('*.txt')),BASE/'runtime/signal_policy.py',BASE/'tracker/service.py',BASE/'tracker/store.py',BASE/'tracker/performance.py']
    before={str(f):digest(f) for f in protected}
    if not (out/'INPUT_PACK.pkl').exists():
        with (SOURCE/'INPUT_PACK.pkl').open('rb') as f:pack=pickle.load(f)
        s=pack['signals'];pack['signals']=s.loc[s.atr_pct.ge(.025)&s.size_proxy.ge(16.901055936487055)&s.vol60.ge(.018471572551217057)].copy()
        assert pack['signals'].date.max()<=END-pd.Timedelta(days=37) and pack['calendar'][-1]==END
        with (out/'INPUT_PACK.pkl').open('wb') as f:pickle.dump(pack,f,protocol=pickle.HIGHEST_PROTOCOL)
        core=module('p12_repeat_source',ARCHIVE/'research/run_batch.py');engine=repeat_engine(core)
        (out/'SIMULATE_SOURCE.txt').write_text(engine.adapted_source,encoding='utf-8')
        save(out/'PROTOCOL.json',dict(end=str(END.date()),slots=list(range(5,11)),initial_cash=100000,start_months=3,
            duplicate_policy='Same symbol on different signal dates creates independent pending/held lots, each occupying a slot with own entry/ATR/deadline. Same signal never repeated; no rank4 refill.',
            capacity='Aggregate all same-symbol buy fills per day <= original 2% daily volume proxy; not 2% independently per duplicate order',
            unchanged='P12 frozen signals/thresholds, priceTR, equity/slots budget, pending+held slot occupancy, fixed 100-share quantities, 7/30 calendar days,T+1,stop-first,original fees/slippage,expiry-close,37day tail',
            yearly_groups='2020-2025 each own year-end; 2026 to common endpoint',
            continuous_groups=['2020_to_current','2026_to_current'],alias={'2026_to_current':'2026'},
            source=str(SOURCE),source_sha256=digest(SOURCE/'INPUT_PACK.pkl'),script_sha256=digest(Path(__file__)),
            protected_before=before,production_changed=False,posterior_research=True))
    if args.extra_actions:
        with (out/'INPUT_PACK.pkl').open('rb') as f:pack=pickle.load(f)
        for receipt in args.extra_actions:add_receipt(receipt,pack['actions'],pack['known'])
        with (out/'INPUT_PACK.pkl').open('wb') as f:pickle.dump(pack,f,protocol=pickle.HIGHEST_PROTOCOL)
        save(out/'ACTION_REPAIR_RECEIPTS.json',{str(p):digest(p) for p in args.extra_actions})
    groups=[(str(y),y,pd.Timestamp(f'{y}-12-31') if y<2026 else END) for y in range(2020,2027)]+[('2020_to_current',2020,END)]
    jobs=[(slots,g,y,end,True) for slots in range(5,11) for g,y,end in groups]+[(5,'2020_to_current',2020,END,False),(5,'2026',2026,END,False)]
    reports=[]
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(out),)) as pool:
        futures={pool.submit(run,j):j for j in jobs}
        for n,f in enumerate(as_completed(futures),1):
            r=f.result();reports.append(r);print('DONE',n,len(jobs),r['slots'],r['group'],'duplicate',r['duplicate'],'gaps',r['action_gaps'],flush=True)
    gaps=sorted({k for r in reports for k in r['action_gaps']});save(out/'ACTION_GAPS.json',gaps)
    controls=[]
    for group in ['2020_to_current','2026']:
        old=pd.read_parquet(SOURCE/group/'P12/EQUITY_CURVES.parquet');new=pd.read_parquet(out/'control_5'/group/'EQUITY_CURVES.parquet')
        cols=['start_ordinal','date','equity'];pd.testing.assert_frame_equal(old[cols],new[cols],check_exact=True);controls.append(group)
    unchanged={str(p):digest(p)==h for p,h in before.items()};assert all(unchanged.values())
    save(out/'SUMMARY.json',dict(status='verified' if not gaps else 'incomplete_action_coverage',end=str(END.date()),
        summaries=reports,action_gaps=gaps,control_exact=controls,protected_unchanged=unchanged,production_changed=False,
        unique_paths=sum(r['runs'] for r in reports),display_alias={'2026_to_current':'2026'}))
    print('FINAL',out/'SUMMARY.json','gaps',gaps,flush=True);assert not gaps,gaps


if __name__=='__main__':main()
