"""Posterior-only fixed ATR>=2.5% annual and continuous Q1 account replays."""
from datetime import datetime
from pathlib import Path
import inspect,json,sys,argparse
import numpy as np
import pandas as pd
from run_june2020_starts import BASE,ROOT,ARCHIVE,module
from baseline_fixed_ioc import fixed_ioc_engine
from compute_risk_metrics import recompute_metrics
from test_atr_thresholds_pre2025 import digest
sys.path.insert(0,str(BASE/'tracker'))
import market

OLD=BASE/'results/holdout_restricted/atr_thresholds_to_current/attempt_20261021_202807'
EXTRA=BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_201802/supplemental_actions.json'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reuse-output',type=Path);args=parser.parse_args()
    health=market.health(BASE/'tracker/data');end=pd.Timestamp(health['market_date'])
    assert end==pd.Timestamp('2026-10-21')
    inventory=market.input_inventory()
    out=args.reuse_output or BASE/'results/holdout_restricted/atr025_annual_post2024'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    if not args.reuse_output:out.mkdir(parents=True,exist_ok=False)
    else:assert out.resolve().parent==(BASE/'results/holdout_restricted/atr025_annual_post2024').resolve()
    print('OUTPUT',out,flush=True)
    audit=module('atr025_annual_post_audit',ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py')
    audit.END_CURRENT=end
    signals=pd.read_parquet(OLD/'INPUT_SIGNALS.parquet')
    assert signals.date.max()==end-pd.Timedelta(days=37)
    signals=signals.loc[signals.atr_pct.ge(.025)].copy()
    source=inspect.getsource(audit.load_raw).replace('pd.read_parquet(path, columns=columns)',"pd.read_parquet(path, columns=columns, filters=[('date','>=',pd.Timestamp('2020-01-01')),('date','<=',END_CURRENT)])")
    exec(compile(source,'<bounded_raw>','exec'),audit.__dict__)
    bars,calendar,raw=audit.load_raw(set(signals.symbol))
    signals=signals.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
    assert signals.close.notna().all()
    actions,known,action_sources=audit.load_actions()
    receipt_paths=sorted((BASE/'results/holdout_restricted/june2020_all_starts').glob('supplemental_actions*.json'))+[EXTRA]
    for p in receipt_paths:
        payload=json.loads(p.read_text(encoding='utf-8'))
        assert payload['report_receipts'] and all(r['error_code']=='0' for r in payload['report_receipts'])
        for key,records in payload['records'].items():
            if key in known:continue
            known.add(key);symbol=key.split('/')[0]
            for row in records:
                if not row.get('dividOperateDate'):continue
                day=pd.Timestamp(row['dividOperateDate'])
                if not pd.Timestamp('2020-01-01')<=day<=end:continue
                n=lambda k:float(str(row.get(k,0)).strip() or 0)
                e=dict(cash=n('dividCashPsBeforeTax'),stock=n('dividStocksPs')+n('dividReserveToStockPs'),taxable_stock=n('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or day),release=pd.Timestamp(row.get('dividStockMarketDate') or day),source=row.get('source','verified BaoStock receipt'))
                identity=lambda x:tuple(x[k] for k in ['cash','stock','taxable_stock','pay','release'])
                existing=actions.setdefault((day,symbol),[])
                if identity(e) not in [identity(x) for x in existing]:existing.append(e)
    # Reuse official receipt but do not silently declare an entire missing year covered.
    official=OLD/'official_000026/OFFICIAL_ACTION_RECEIPT.json'
    receipt=json.loads(official.read_text(encoding='utf-8'))
    for doc in receipt['documents']:assert digest(Path(doc['local_file']))==doc['sha256']
    core=fixed_ioc_engine(audit.core,manual_expiry_open=False,filled_slots=False)
    delists=audit.load_delistings()
    # Query only the benchmark; no market update/download of stock datasets.
    import baostock as bs
    sys.path.insert(0,str(ROOT/'tools'))
    from daily_market_update import install_baostock_socket_safety
    if (out/'SSE_PRICE_INDEX.parquet').exists():index=pd.read_parquet(out/'SSE_PRICE_INDEX.parquet')
    else:
        install_baostock_socket_safety();response=bs.login();assert response.error_code=='0'
        try:
            response=bs.query_history_k_data_plus('sh.000001','date,code,close',start_date='2020-01-01',end_date=str(end.date()),frequency='d',adjustflag='3')
            assert response.error_code=='0';rows=[]
            while response.next():rows.append(response.get_row_data())
            assert response.error_code=='0'
        finally:bs.logout()
        index=pd.DataFrame(rows,columns=response.fields);index.date=pd.to_datetime(index.date);index.close=pd.to_numeric(index.close)
    assert index.date.max()==end and not index.date.duplicated().any()
    index.to_parquet(out/'SSE_PRICE_INDEX.parquet',index=False);ic=index.set_index('date').close
    assert index.date.tolist()==calendar
    protected=[BASE/'CURRENT_SELECTION.json',BASE/'model/manifest.json',BASE/'tracker/data/ledger.sqlite3',BASE/'tracker/data/market_status.json']
    before={str(p):digest(p) for p in protected if p.exists()}
    protocol=dict(end=str(end.date()),threshold=.025,slots=5,initial_cash=100000,execution=core.policy,filter='Original top3 >=0.025 inclusive; no refill',posterior_audit_only=True,source_signal_file=str(OLD/'INPUT_SIGNALS.parquet'),source_signal_sha256=digest(OLD/'INPUT_SIGNALS.parquet'),signal_splice_gap_preserved=True,benchmark='BaoStock sh.000001 unadjusted price index; same start/end; 365 calendar day annualization',action_sources=action_sources,extra_receipts={str(p):digest(p) for p in receipt_paths},protected_before=before,official_action_receipt=str(official),script_sha256=digest(Path(__file__)))
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    signals.to_parquet(out/'INPUT_SIGNALS.parquet',index=False)
    summaries=[];unresolved=set();resolutions=[]
    for label,year,stop,expected in [('2025',2025,pd.Timestamp('2025-12-31'),57),('2026',2026,end,56),('2020_to_current',2020,end,58),('2025_to_current',2025,end,57)]:
        folder=out/label;folder.mkdir(exist_ok=True);last=stop-pd.Timedelta(days=37)
        starts=[d for d in calendar if d.year==year and d.month<=3];assert len(starts)==expected
        selected=signals.loc[signals.date.le(last)]
        metrics=[];curves=[];trades=[];attempts=[];all_gaps=set();raw_results=[]
        cal=[d for d in calendar if d<=stop]
        for ordinal,start in enumerate(starts,1):
            if (folder/'START_METRICS.parquet').exists():break
            core.EVAL_START=start;core.HARD_MAX_DATE=stop;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(year,stop.year+1))
            gaps=set();curve=[]
            result,t=core.simulate(selected.loc[selected.date.ge(start)],bars,cal,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,delist_dates=delists,slots=5,equity_curve_sink=curve)
            all_gaps.update(gaps)
            a=pd.DataFrame(result['fixed_order_attempts']);a['start_ordinal']=ordinal;a['start_date']=start
            assert not a.duplicated(['symbol','signal_date']).any()
            fills=int(a.filled_quantity.gt(0).sum());zero=int(a.filled_quantity.eq(0).sum())
            assert fills==result['filled_orders']
            assert result['pending_orders_created']==fills+zero+result['expired_entry_orders']+result['pending_orders_at_end']
            counts=t.reason.value_counts().to_dict() if len(t) else {}
            assert fills==sum(counts.values())+result['open_positions_at_end']
            assert not result['open_positions_at_end'] and not result['pending_orders_at_end']
            c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
            m=recompute_metrics(c).iloc[0].to_dict();actual_end=c.date.max()
            bench=float((ic.loc[actual_end]/ic.loc[start])**(365/(actual_end-start).days)-1)
            m.update(benchmark_annualized=bench,annualized_excess=m['annualized_return']-bench,beat_sse=m['annualized_return']>bench,pending_orders_created=result['pending_orders_created'],filled_orders=fills,unfilled_orders=zero+result['expired_entry_orders'],expired_entry_orders=result['expired_entry_orders'],failed_trigger_orders=zero,partial_fill_orders=int(a.status.eq('partial_remainder_cancelled').sum()),take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),open_positions_at_end=result['open_positions_at_end'],pending_orders_at_end=result['pending_orders_at_end'],raw_action_gaps=sorted(gaps))
            metrics.append(m);curves.append(c);t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t);attempts.append(a)
            raw_results.append({k:v for k,v in result.items() if k!='fixed_order_attempts'})
            if ordinal%10==0 or ordinal==expected:print(label,ordinal,expected,'gaps',sorted(all_gaps),flush=True)
        if (folder/'START_METRICS.parquet').exists():
            f=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet');a=pd.read_parquet(folder/'FIXED_ORDER_ATTEMPTS.parquet')
            all_gaps=set(k for ks in f.raw_action_gaps for k in ks)
        else:
            f=pd.DataFrame(metrics);c=pd.concat(curves,ignore_index=True);t=pd.concat(trades,ignore_index=True);a=pd.concat(attempts,ignore_index=True)
            f.to_parquet(folder/'START_METRICS.parquet',index=False);c.to_parquet(folder/'EQUITY_CURVES.parquet',index=False);t.to_parquet(folder/'TRADES.parquet',index=False);a.to_parquet(folder/'FIXED_ORDER_ATTEMPTS.parquet',index=False)
            (folder/'RAW_RESULTS.json').write_text(json.dumps(raw_results,ensure_ascii=False,indent=2),encoding='utf-8')
        for key in all_gaps:
            if key!=receipt['key']:unresolved.add(key);continue
            sym,y=key.split('/');held=t.loc[t.symbol.eq(sym)&t.entry_date.le(pd.Timestamp(f'{y}-12-31'))&t.exit_date.ge(pd.Timestamp(f'{y}-01-01'))]
            for e in receipt['records'][key]:
                if e.get('dividOperateDate'):
                    day=pd.Timestamp(e['dividOperateDate']);assert not ((held.entry_date.lt(day))&(held.exit_date.ge(day))).any(),('Missing held action requires rerun',key)
            resolutions.append(dict(group=label,key=key,receipt_sha256=digest(official),held_windows=held[['start_ordinal','entry_date','exit_date']].astype(str).to_dict('records'),affected_positions=0))
        fields=['cumulative_return','annualized_return','benchmark_annualized','annualized_excess','beat_sse','maximum_drawdown','sharpe_zero_rf_252_ddof0','pending_orders_created','filled_orders','unfilled_orders','expired_entry_orders','failed_trigger_orders','partial_fill_orders','take_count','stop_count','expiry_count']
        summary=dict(group=label,runs=len(f),end=str(c.date.max().date()),last_signal_cutoff=str(last.date()),means={k:float(f[k].mean()) for k in fields},raw_action_gaps=sorted(all_gaps))
        summaries.append(summary);print('SUMMARY',json.dumps(summary),flush=True)
        if label=='2020_to_current':
            prior=pd.read_parquet(OLD/'atr_ge_025/EQUITY_CURVES.parquet')
            pd.testing.assert_frame_equal(c[['start_ordinal','date','equity']].reset_index(drop=True),prior[['start_ordinal','date','equity']].reset_index(drop=True),check_exact=True)
    assert market.input_inventory()==inventory
    unchanged={p:digest(Path(p))==h for p,h in before.items()};assert all(unchanged.values())
    report=dict(status='verified' if not unresolved else 'incomplete_action_coverage',summaries=summaries,unresolved_action_gaps=sorted(unresolved),official_coverage_resolutions=resolutions,protected_unchanged=unchanged,software_account_changed=False,order_identities_verified=True,prior_2020_curves_identical=True)
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print('FINAL',json.dumps(report,ensure_ascii=False),flush=True)
    assert not unresolved,sorted(unresolved)

if __name__=='__main__':main()
