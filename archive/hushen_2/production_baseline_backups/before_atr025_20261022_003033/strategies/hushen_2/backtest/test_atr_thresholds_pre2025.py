"""Four user-specified ATR filters, Q1-2020 starts to 2024 only. No production writes."""
from datetime import datetime
from pathlib import Path
import argparse
import inspect
import json
import hashlib
import numpy as np
import pandas as pd
from run_june2020_starts import ARCHIVE, BASE, ROOT, module
from baseline_fixed_ioc import fixed_ioc_engine
from compute_risk_metrics import recompute_metrics

END = pd.Timestamp('2024-12-31')
LAST = END-pd.Timedelta(days=37)
SOURCE = BASE/'results/holdout_restricted/fixed_ioc_atr_price_q1_2020/attempt_20261020_051613'
VARIANTS = [('original',0.),('atr_ge_025',.025),('atr_ge_040',.04),('atr_ge_045',.045)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--extra-actions',type=Path);args=parser.parse_args()
    out=BASE/'results/holdout_restricted/atr_thresholds_pre2025'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    print('OUTPUT',out,flush=True)
    audit_path=ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py'
    audit=module('atr_threshold_pre2025_audit',audit_path)
    audit.END_CURRENT=END
    # Read only the pre-2025 partition of the retained price-TR signals.
    signals=pd.read_parquet(SOURCE/'FROZEN_SIGNALS.parquet',filters=[('date','<=',LAST)])
    assert signals.date.max()<=LAST and not signals.duplicated(['date','symbol']).any()
    assert signals.groupby('date').size().max()<=3
    assert signals.atr_pct.between(.015-1e-10,.05+1e-10).all()
    # Same historical loader, with a predicate pushed into every OHLC read.
    loader_source=inspect.getsource(audit.load_raw)
    old='pd.read_parquet(path, columns=columns)'
    assert loader_source.count(old)==1
    loader_source=loader_source.replace(old,"pd.read_parquet(path, columns=columns, filters=[('date','>=',pd.Timestamp('2020-01-01')),('date','<=',END_CURRENT)])")
    exec(compile(loader_source,'<pre2025_raw_loader>','exec'),audit.__dict__)
    bars,calendar,raw=audit.load_raw(set(signals.symbol))
    assert min(calendar)>=pd.Timestamp('2020-01-01') and max(calendar)==END
    # Use unadjusted execution close, exactly as the selected baseline runner.
    signals=signals.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
    assert signals.close.notna().all()
    signals=signals.sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable').reset_index(drop=True)
    actions,known,action_sources=audit.load_actions()
    extras=[]
    receipt_paths=sorted((BASE/'results/holdout_restricted/june2020_all_starts').glob('supplemental_actions*.json'))
    if args.extra_actions:receipt_paths.append(args.extra_actions.resolve())
    for path in receipt_paths:
        payload=json.loads(path.read_text(encoding='utf-8'))
        receipts=payload.get('report_receipts',[])
        assert receipts and all(r['error_code']=='0' for r in receipts)
        for key,records in payload['records'].items():
            if key in known:continue
            known.add(key);symbol=key.split('/')[0]
            for row in records:
                if not row.get('dividOperateDate'):continue
                date=pd.Timestamp(row['dividOperateDate'])
                if not pd.Timestamp('2020-01-01')<=date<=END:continue
                number=lambda k:float(str(row.get(k,0)).strip() or 0)
                event=dict(cash=number('dividCashPsBeforeTax'),stock=number('dividStocksPs')+number('dividReserveToStockPs'),
                    taxable_stock=number('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or date),
                    release=pd.Timestamp(row.get('dividStockMarketDate') or date),source=row.get('source','retained verified BaoStock receipt'))
                identity=lambda x:tuple(x[k] for k in ['cash','stock','taxable_stock','pay','release'])
                existing=actions.setdefault((date,symbol),[])
                if identity(event) not in [identity(e) for e in existing]:existing.append(event)
        extras.append(dict(path=str(path.relative_to(ROOT)),sha256=digest(path)))
    actions={k:v for k,v in actions.items() if pd.Timestamp('2020-01-01')<=k[0]<=END}
    known={k for k in known if 2020<=int(k.split('/')[-1])<=2024}
    delistings=audit.load_delistings()
    assert all(x<=END for x in delistings.values())
    core=fixed_ioc_engine(audit.core,manual_expiry_open=False,filled_slots=False)
    starts=[d for d in calendar if pd.Timestamp('2020-01-01')<=d<=pd.Timestamp('2020-03-31')]
    assert len(starts)==58
    protected=[BASE/'CURRENT_SELECTION.json',BASE/'model/manifest.json',BASE/'tracker/data/ledger.sqlite3',BASE/'tracker/data/market_status.json']
    before={str(p):digest(p) for p in protected if p.exists()}
    protocol=dict(end=str(END.date()),last_signal_cutoff=str(LAST.date()),starts=[str(s.date()) for s in starts],
        thresholds=dict(VARIANTS),atr_policy='full-period price TR SMA14 / signal close clipped 1.5%-5%',
        filter_policy='Inclusive >=, applied to original daily top-three signals, preserving score order; no refill from rank 4+',
        execution=core.policy,slots=5,initial_cash=100000,actions_sources=action_sources,extra_action_sources=extras,
        research_boundary='All simulation bars/signals/actions/metrics <=2024-12-31. Fixed registered model, no training or post-2024 evaluation. Root has prior posterior exposure: not a fresh blind experiment.',
        source_hashes={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),audit_path,Path(__file__).with_name('baseline_fixed_ioc.py'),SOURCE/'FROZEN_SIGNALS.parquet']},
        protected_before=before,production_changed=False)
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    signals.to_parquet(out/'INPUT_SIGNALS_PRE2025.parquet',index=False)
    summaries=[];total_gaps=set()
    for name,threshold in VARIANTS:
        folder=out/name;folder.mkdir()
        selected=signals.loc[signals.atr_pct.ge(threshold)].copy()
        metrics=[];curves=[];trades=[];gaps_all=set()
        for ordinal,start in enumerate(starts,1):
            core.EVAL_START=start;core.HARD_MAX_DATE=END;core.LAST_SIGNAL_DATE=LAST;core.YEARS=list(range(2020,2025))
            gaps=set();curve=[]
            result,t=core.simulate(selected.loc[selected.date.between(start,LAST)],bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
                keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,delist_dates=delistings,slots=5,equity_curve_sink=curve)
            gaps_all.update(gaps)
            c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
            assert c.date.min()==start and c.date.max()==END
            m=recompute_metrics(c).iloc[0].to_dict()
            counts=t.reason.value_counts().to_dict() if len(t) else {}
            m.update(completed_trades=result['completed_trades'],filled_orders=result['filled_orders'],
                open_positions_at_end=result['open_positions_at_end'],pending_orders_at_end=result['pending_orders_at_end'],
                take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
                eligible_20_trades_each_year=result['eligible'],**{f'trades_{y}':result[f'trades_{y}'] for y in range(2020,2025)},
                **{f'return_{y}':result[f'return_{y}'] for y in range(2020,2025)})
            metrics.append(m);curves.append(c)
            t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t)
            if ordinal%10==0 or ordinal==58:print(name,ordinal,'/58','gaps',len(gaps_all),flush=True)
        frame=pd.DataFrame(metrics)
        frame.to_parquet(folder/'START_METRICS.parquet',index=False)
        pd.concat(curves,ignore_index=True).to_parquet(folder/'EQUITY_CURVES.parquet',index=False)
        pd.concat(trades,ignore_index=True).to_parquet(folder/'TRADES.parquet',index=False)
        summary=dict(variant=name,threshold=threshold,runs=58,signals=len(selected),
            cumulative_return_mean=float(frame.cumulative_return.mean()),cumulative_return_median=float(frame.cumulative_return.median()),
            annualized_return_mean=float(frame.annualized_return.mean()),annualized_return_median=float(frame.annualized_return.median()),
            worst_start_annualized_return=float(frame.annualized_return.min()),
            maximum_drawdown_mean=float(frame.maximum_drawdown.mean()),worst_start_drawdown=float(frame.maximum_drawdown.min()),
            sharpe_mean=float(frame.sharpe_zero_rf_252_ddof0.mean()),completed_trades_mean=float(frame.completed_trades.mean()),
            completed_trades_total=int(frame.completed_trades.sum()),eligible_starts_20_trades_each_year=int(frame.eligible_20_trades_each_year.sum()),
            **{f'trades_{y}_mean':float(frame[f'trades_{y}'].mean()) for y in range(2020,2025)},
            terminal_open_positions_max=int(frame.open_positions_at_end.max()),terminal_pending_orders_max=int(frame.pending_orders_at_end.max()),
            action_gaps=sorted(gaps_all))
        summaries.append(summary);total_gaps.update(gaps_all)
        (folder/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    unchanged={p:digest(Path(p))==h for p,h in before.items()}
    assert all(unchanged.values())
    report=dict(status='complete' if not total_gaps else 'incomplete_action_audit',end=str(END.date()),summaries=summaries,
        action_gaps=sorted(total_gaps),protected_files_unchanged=unchanged,production_changed=False)
    (out/'COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('COMPARISON',json.dumps(report,ensure_ascii=False),flush=True)
    assert not total_gaps,sorted(total_gaps)


if __name__=='__main__':main()
