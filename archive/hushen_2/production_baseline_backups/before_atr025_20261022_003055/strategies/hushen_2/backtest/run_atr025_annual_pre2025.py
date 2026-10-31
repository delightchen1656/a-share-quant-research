"""ATR>=2.5%, every Q1 start in 2020-2024 through its own year end; research only."""
import argparse
from datetime import datetime
import inspect
import json
from pathlib import Path
import numpy as np
import pandas as pd
from run_june2020_starts import ARCHIVE, BASE, ROOT, module
from test_atr_thresholds_pre2025 import SOURCE, digest
from baseline_fixed_ioc import fixed_ioc_engine
from compute_risk_metrics import recompute_metrics

END=pd.Timestamp('2024-12-31')
DEFAULT_EXTRA=BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_201802/supplemental_actions.json'


def add_receipt(path,actions,known):
    payload=json.loads(path.read_text(encoding='utf-8'))
    receipts=payload.get('report_receipts',[])
    assert receipts and all(x['error_code']=='0' for x in receipts)
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


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--extra-actions',type=Path,action='append',default=[]);args=parser.parse_args()
    out=BASE/'results/holdout_restricted/atr025_annual_pre2025'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False);print('OUTPUT',out,flush=True)
    audit_path=ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py'
    audit=module('atr025_annual_pre_audit',audit_path);audit.END_CURRENT=END
    signals=pd.read_parquet(SOURCE/'FROZEN_SIGNALS.parquet',filters=[('date','<=',END)])
    assert not signals.duplicated(['date','symbol']).any() and signals.groupby('date').size().max()<=3
    signals=signals.loc[signals.atr_pct.ge(.025)].copy()
    loader=inspect.getsource(audit.load_raw)
    old='pd.read_parquet(path, columns=columns)';assert loader.count(old)==1
    loader=loader.replace(old,"pd.read_parquet(path, columns=columns, filters=[('date','>=',pd.Timestamp('2020-01-01')),('date','<=',END_CURRENT)])")
    exec(compile(loader,'<annual_pre2025_raw_loader>','exec'),audit.__dict__)
    bars,calendar,raw=audit.load_raw(set(signals.symbol))
    signals=signals.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
    assert signals.close.notna().all()
    signals=signals.sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable')
    actions,known,action_sources=audit.load_actions()
    extras=sorted((BASE/'results/holdout_restricted/june2020_all_starts').glob('supplemental_actions*.json'))+[DEFAULT_EXTRA]+[p.resolve() for p in args.extra_actions]
    for path in extras:add_receipt(path,actions,known)
    actions={k:v for k,v in actions.items() if pd.Timestamp('2020-01-01')<=k[0]<=END}
    known={k for k in known if 2020<=int(k.split('/')[-1])<=2024}
    delistings=audit.load_delistings()
    index=pd.read_parquet(audit.INDEX_PATH,filters=[('date','>=',pd.Timestamp('2020-01-01')),('date','<=',END)])
    index['date']=pd.to_datetime(index.date);index=index.set_index('date').close.sort_index()
    assert list(index.index)==calendar
    core=fixed_ioc_engine(audit.core,manual_expiry_open=False,filled_slots=False)
    protected=[BASE/'CURRENT_SELECTION.json',BASE/'model/manifest.json',BASE/'tracker/data/ledger.sqlite3',BASE/'tracker/data/market_status.json']
    before={str(p):digest(p) for p in protected if p.exists()}
    protocol=dict(threshold=.025,slots=5,initial_cash=100000,execution=core.policy,benchmark='SSE price index, same start/end session',
        end_anchor='Calendar December 31; no-order cutoff 37 calendar days earlier. Curves/CAGR/benchmark end at final actual trading session.',
        unfilled_definition='created orders - positive-fill orders - still pending; expiry without trigger + triggered zero-fill mutually exclusive',
        sources={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),SOURCE/'FROZEN_SIGNALS.parquet',audit_path,Path(__file__).with_name('baseline_fixed_ioc.py'),audit.INDEX_PATH]},
        extra_actions={str(p.relative_to(ROOT)):digest(p) for p in extras},action_sources=action_sources,protected_before=before,
        boundary='Evaluation exclusively 2020-2024, frozen model/threshold; root previously posterior-exposed, not new blind research.',production_changed=False)
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    signals.to_parquet(out/'INPUT_SIGNALS.parquet',index=False)
    index.rename('close').reset_index().to_parquet(out/'SSE_INDEX.parquet',index=False)
    summaries=[];all_gaps=set()
    for year in range(2020,2025):
        folder=out/str(year);folder.mkdir()
        end_anchor=pd.Timestamp(f'{year}-12-31');last=end_anchor-pd.Timedelta(days=37)
        end_session=max(d for d in calendar if d<=end_anchor)
        starts=[d for d in calendar if pd.Timestamp(f'{year}-01-01')<=d<=pd.Timestamp(f'{year}-03-31')]
        assert len(starts)=={2020:58,2021:58,2022:58,2023:59,2024:58}[year]
        curves=[];trades=[];attempts=[];rows=[];gaps_group=set()
        for ordinal,start in enumerate(starts,1):
            core.EVAL_START=start;core.HARD_MAX_DATE=end_anchor;core.LAST_SIGNAL_DATE=last;core.YEARS=[year]
            gaps=set();curve=[]
            result,t=core.simulate(signals.loc[signals.date.between(start,last)],bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
                keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,delist_dates=delistings,slots=5,equity_curve_sink=curve)
            gaps_group.update(gaps)
            c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
            assert c.date.min()==start and c.date.max()==end_session
            m=recompute_metrics(c).iloc[0].to_dict()
            counts=t.reason.value_counts().to_dict() if len(t) else {}
            aa=result['fixed_order_attempts'];zero=sum(x['filled_quantity']==0 for x in aa);partial=sum(0<x['filled_quantity']<x['requested_quantity'] for x in aa)
            unfilled=result['pending_orders_created']-result['filled_orders']-result['pending_orders_at_end']
            assert unfilled==result['expired_entry_orders']+zero
            assert result['filled_orders']==result['completed_trades']+result['open_positions_at_end']
            assert sum(counts.values())==result['completed_trades']
            benchmark_cum=float(index.loc[end_session]/index.loc[start]-1)
            benchmark_ann=(1+benchmark_cum)**(365/(end_session-start).days)-1
            m.update(benchmark_cumulative_return=benchmark_cum,benchmark_annualized_return=benchmark_ann,
                annualized_excess=m['annualized_return']-benchmark_ann,beat_benchmark=m['annualized_return']>benchmark_ann,
                filled_orders=result['filled_orders'],unfilled_orders=unfilled,pending_orders_created=result['pending_orders_created'],
                expired_untriggered_orders=result['expired_entry_orders'],triggered_zero_fill_orders=zero,partial_fill_orders=partial,
                take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
                open_positions_at_end=result['open_positions_at_end'],pending_orders_at_end=result['pending_orders_at_end'],action_gaps=sorted(gaps))
            rows.append(m);curves.append(c)
            t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t)
            attempts.extend(dict(a,start_ordinal=ordinal) for a in aa)
            if ordinal%15==0 or ordinal==len(starts):print(year,ordinal,'/',len(starts),'gaps',len(gaps_group),flush=True)
        frame=pd.DataFrame(rows)
        frame.to_parquet(folder/'START_METRICS.parquet',index=False)
        pd.concat(curves,ignore_index=True).to_parquet(folder/'EQUITY_CURVES.parquet',index=False)
        pd.concat(trades,ignore_index=True).to_parquet(folder/'TRADES.parquet',index=False)
        pd.DataFrame(attempts).to_parquet(folder/'ORDER_ATTEMPTS.parquet',index=False)
        summary=dict(group=str(year),start_count=len(starts),end=str(end_session.date()),end_anchor=str(end_anchor.date()),last_signal_cutoff=str(last.date()),
            **{k+'_mean':float(frame[k].mean()) for k in ['cumulative_return','annualized_return','benchmark_annualized_return','annualized_excess',
            'maximum_drawdown','sharpe_zero_rf_252_ddof0','filled_orders','unfilled_orders','take_count','stop_count','expiry_count',
            'pending_orders_created','expired_untriggered_orders','triggered_zero_fill_orders','partial_fill_orders']},
            beat_benchmark_fraction=float(frame.beat_benchmark.mean()),action_gaps=sorted(gaps_group),
            terminal_open_positions_max=int(frame.open_positions_at_end.max()),terminal_pending_orders_max=int(frame.pending_orders_at_end.max()))
        summaries.append(summary);all_gaps.update(gaps_group)
        (folder/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    unchanged={p:digest(Path(p))==h for p,h in before.items()};assert all(unchanged.values())
    report=dict(status='complete' if not all_gaps else 'incomplete_action_audit',summaries=summaries,action_gaps=sorted(all_gaps),protected_files_unchanged=unchanged,production_changed=False)
    (out/'COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'ACTION_GAPS.json').write_text(json.dumps(sorted(all_gaps)),encoding='utf-8')
    print('REPORT',json.dumps(report,ensure_ascii=False),flush=True)
    assert not all_gaps,sorted(all_gaps)


if __name__=='__main__':main()
