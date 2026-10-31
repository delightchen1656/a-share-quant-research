"""Replay original frozen Q1-2020 accounts, not current tracker policy. No production writes."""
from datetime import datetime
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import pandas as pd
from run_june2020_starts import ARCHIVE, BASE, ROOT, module
from compute_risk_metrics import recompute_metrics
sys.path.insert(0,str(BASE/'tracker'))
from market import digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--june',action='store_true');parser.add_argument('--start-year',type=int,choices=[2020,2025,2026],default=2020);parser.add_argument('--fixed-ioc',action='store_true');parser.add_argument('--legacy-expiry-close',action='store_true',help='Reproduce old fixed-IOC expiry-close results');parser.add_argument('--legacy-pending-slots',action='store_true',help='Retain pending orders occupying slots and old buffered quantity');parser.add_argument('--filled-slots',action='store_true',help='Experimental filled-only slots; not the selected production/backtest policy');parser.add_argument('--atr-policy',choices=['mixed','relative','price'],default='mixed');parser.add_argument('--atr-panel',type=Path);args=parser.parse_args()
    if args.legacy_pending_slots and not args.fixed_ioc:parser.error('--legacy-pending-slots requires --fixed-ioc')
    if args.filled_slots and not args.fixed_ioc:parser.error('--filled-slots requires --fixed-ioc')
    if args.filled_slots and args.legacy_pending_slots:parser.error('--filled-slots conflicts with --legacy-pending-slots')
    if args.atr_policy!='mixed' and (not args.fixed_ioc or not args.legacy_expiry_close or args.filled_slots or not args.atr_panel):
        parser.error('Uniform ATR requires --fixed-ioc --legacy-expiry-close --atr-panel, without --filled-slots')
    if args.legacy_expiry_close and not args.fixed_ioc:parser.error('--legacy-expiry-close requires --fixed-ioc')
    if args.june and args.start_year!=2020:parser.error('--june is only for 2020')
    compare_original=not args.june and args.start_year==2020 and not args.fixed_ioc
    source=ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py'
    audit=module('original_q1_frozen_audit',source)
    expected=audit.validate_sources()
    signals=audit.candidate_signals('C04_NEW',expected['C04_NEW'])
    atr_sources={}
    if args.atr_policy!='mixed':
        atr_receipt=args.atr_panel.with_name('VERIFICATION.json')
        verified=json.loads(atr_receipt.read_text(encoding='utf-8'))
        assert verified['status']=='verified' and digest(args.atr_panel)==verified['atr_panel_sha256']
        alternative=pd.read_parquet(args.atr_panel)
        joined=signals[['date','symbol','atr_pct']].merge(alternative,on=['date','symbol'],how='left',validate='one_to_one',suffixes=('_frozen','_input'))
        assert len(joined)==len(signals) and joined[args.atr_policy].notna().all()
        assert np.array_equal(joined.atr_pct_frozen.to_numpy(),joined.atr_pct_input.to_numpy())
        signals['atr_pct']=joined[args.atr_policy].to_numpy()
        for path,h in verified['input_hashes'].items():assert digest(ROOT/path)==h
        for path,h in verified['original_cache_hashes'].items():assert digest(ROOT/path)==h
        atr_sources={str(p.resolve().relative_to(ROOT)):digest(p) for p in [args.atr_panel,atr_receipt,Path(__file__).with_name('uniform_atr.py'),Path(__file__).with_name('ATR_UNIFORM_PROTOCOL.json')]}
    core=audit.core
    assert digest(ARCHIVE/'research/run_batch.py')=='2474856294d95f52868f82a256b7f557c9d01d00a80a935f5dc24f88f51c843d'
    output=BASE/'results/holdout_restricted/original_q1_replay'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    if args.june:output=BASE/'results/holdout_restricted/original_june_replay'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    elif not compare_original:output=BASE/f'results/holdout_restricted/original_q1_{args.start_year}_replay'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    if args.fixed_ioc:
        group='june2020' if args.june else f'q1_{args.start_year}'
        output=BASE/f'results/holdout_restricted/baseline_fixed_ioc_{group}'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
        if not args.legacy_expiry_close:
            output=BASE/f'results/holdout_restricted/fixed_ioc_manual_expiry_open_{group}'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
        if args.filled_slots:
            output=BASE/f'results/holdout_restricted/fixed_ioc_filled_slots_{group}'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
        if args.atr_policy!='mixed':
            output=BASE/f'results/holdout_restricted/fixed_ioc_atr_{args.atr_policy}_{group}'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    output.mkdir(parents=True,exist_ok=False)
    print('Output',output,flush=True)
    bars,calendar,raw=audit.load_raw(set(signals.symbol.astype(str)))
    signals=signals.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
    assert signals.close.notna().all()
    signals=signals.sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable').reset_index(drop=True)
    signals.to_parquet(output/'FROZEN_SIGNALS.parquet',index=False)
    actions,known,action_sources=audit.load_actions()
    if args.june:
        # June accounts encounter two previously verified stock-years absent from
        # the original Q1 paths. Add only missing keys; never overwrite old events.
        path=BASE/'results/holdout_restricted/june2020_all_starts/supplemental_actions_baostock_2020.json'
        receipt=json.loads(path.read_text(encoding='utf-8'))
        added=[]
        for key,records in receipt['records'].items():
            if key in known:continue
            known.add(key);added.append(key);symbol=key.split('/')[0]
            for row in records:
                if not row.get('dividOperateDate'):continue
                date=pd.Timestamp(row['dividOperateDate'])
                number=lambda k:float(str(row.get(k,0)).strip() or 0)
                event=dict(cash=number('dividCashPsBeforeTax'),stock=number('dividStocksPs')+number('dividReserveToStockPs'),
                    taxable_stock=number('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or date),
                    release=pd.Timestamp(row.get('dividStockMarketDate') or date),source=row.get('source','retained verified BaoStock receipt'))
                identity=lambda x:tuple(x[k] for k in ['cash','stock','taxable_stock','pay','release'])
                existing=actions.setdefault((date,symbol),[])
                if identity(event) not in [identity(e) for e in existing]:existing.append(event)
        action_sources['june_missing_key_receipt']={'path':str(path.relative_to(ROOT)),'sha256':digest(path),'added_keys':added}
    if args.fixed_ioc:
        action_sources['fixed_ioc_missing_key_receipts']=[]
        for path in sorted((BASE/'results/holdout_restricted/june2020_all_starts').glob('supplemental_actions*.json')):
            payload=json.loads(path.read_text(encoding='utf-8'))
            receipts=payload.get('report_receipts',[])
            assert receipts and all(r['error_code']=='0' for r in receipts)
            added=[]
            for key,records in payload['records'].items():
                if key in known:continue
                known.add(key);added.append(key);symbol=key.split('/')[0]
                for row in records:
                    if not row.get('dividOperateDate'):continue
                    date=pd.Timestamp(row['dividOperateDate'])
                    number=lambda k:float(str(row.get(k,0)).strip() or 0)
                    event=dict(cash=number('dividCashPsBeforeTax'),stock=number('dividStocksPs')+number('dividReserveToStockPs'),
                        taxable_stock=number('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or date),
                        release=pd.Timestamp(row.get('dividStockMarketDate') or date),source=row.get('source','retained verified BaoStock receipt'))
                    identity=lambda x:tuple(x[k] for k in ['cash','stock','taxable_stock','pay','release'])
                    existing=actions.setdefault((date,symbol),[])
                    if identity(event) not in [identity(e) for e in existing]:existing.append(event)
            action_sources['fixed_ioc_missing_key_receipts'].append({'path':str(path.relative_to(ROOT)),'sha256':digest(path),'added_keys':added})
    delistings=audit.load_delistings()
    index=pd.read_parquet(audit.INDEX_PATH);index['date']=pd.to_datetime(index.date)
    start_bounds=('2020-06-01','2020-06-30') if args.june else (f'{args.start_year}-01-01',f'{args.start_year}-03-31')
    starts=index.loc[index.date.between(*start_bounds),'date'].sort_values().tolist()
    assert len(starts)==(20 if args.june else {2020:58,2025:57,2026:56}[args.start_year])
    end=pd.Timestamp('2026-10-19');last=end-pd.Timedelta(days=37)
    stored=pd.read_parquet(BASE/'results/EQUITY_CURVES_2020Q1_STARTS_TO_20261019.parquet')
    stored_metrics=pd.read_csv(BASE/'results/RISK_METRICS_2020Q1_STARTS_TO_20261019.csv')
    paths=[source,ARCHIVE/'research/run_batch.py',audit.reopt.PANEL_PATH,expected['C04_NEW']['post'],audit.INDEX_PATH,
           BASE/'results/EQUITY_CURVES_2020Q1_STARTS_TO_20261019.parquet',BASE/'results/RISK_SUMMARY.json']
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in paths}
    if args.fixed_ioc:
        from baseline_fixed_ioc import fixed_ioc_engine,POLICY_PATH
        core=fixed_ioc_engine(core,manual_expiry_open=not args.legacy_expiry_close,filled_slots=args.filled_slots)
        for p in [Path(__file__),Path(__file__).with_name('baseline_fixed_ioc.py'),POLICY_PATH]:hashes[str(p.relative_to(ROOT))]=digest(p)
        if args.filled_slots:
            path=Path(__file__).with_name('FILLED_SLOT_PROTOCOL.json');hashes[str(path.relative_to(ROOT))]=digest(path)
        (output/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    hashes.update(atr_sources)
    protocol={'mode':'original_frozen_inputs_and_original_execution_not_tracker','strategy':'C04_NEW','slots':5,'initial_cash':100000,
              'starts':[str(x.date()) for x in starts],'end':str(end.date()),'last_signal_cutoff':str(last.date()),
              'atr':'Retained original mixed ATR, unchanged; no new-model prediction or current tracker ATR',
              'source_hashes':hashes,'action_sources':action_sources,'signals':len(signals),
              'production_account_changed':False,'original_results_overwritten':False}
    if args.fixed_ioc:
        protocol['mode']='baseline_only_fixed_quantity_ioc'
        protocol['execution_policy']=core.policy
        if not args.legacy_expiry_close:protocol['mode']='fixed_quantity_ioc_manual_next_session_expiry_open'
        if args.filled_slots:protocol['mode']='fixed_quantity_ioc_filled_slots_daily_priority'
    if args.atr_policy!='mixed':
        protocol['mode']='baseline_fixed_ioc_uniform_execution_atr'
        protocol['atr']=args.atr_policy
    (output/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    curves=[];trades=[];operations=[];comparisons=[];all_gaps=set();attempts=[]
    for ordinal,start in enumerate(starts,1):
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(2020,2027))
        gaps=set();curve=[]
        result,t=core.simulate(signals[signals.date.between(start,last)],bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
            keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,delist_dates=delistings,slots=5,equity_curve_sink=curve)
        all_gaps.update(gaps)
        for attempt in result.get('fixed_order_attempts',[]):attempts.append(dict(attempt,start_ordinal=ordinal))
        c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start;curves.append(c)
        if compare_original:
            old=stored[stored.start_ordinal.eq(ordinal)].sort_values('date').reset_index(drop=True)
            assert pd.to_datetime(old.date).tolist()==c.date.tolist()
            difference=np.abs(c.equity.to_numpy()-old.equity.to_numpy())
            comparisons.append(dict(start_ordinal=ordinal,start_date=str(start.date()),max_equity_abs_difference=float(difference.max()),
                ending_equity_difference=float(c.equity.iloc[-1]-old.equity.iloc[-1]),exact_curve_equal=bool(np.array_equal(c.equity.to_numpy(),old.equity.to_numpy()))))
        counts=t.reason.value_counts().to_dict() if not t.empty else {}
        operations.append(dict(start_ordinal=ordinal,completed_trades=result['completed_trades'],open_positions_at_end=result['open_positions_at_end'],
            pending_orders_at_end=result['pending_orders_at_end'],action_gap_count=len(gaps),take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
            filled_orders=result['filled_orders'],pending_orders_created=result['pending_orders_created'],expired_entry_orders=result['expired_entry_orders'],
            failed_trigger_orders=sum(x['filled_quantity']==0 for x in result.get('fixed_order_attempts',[])),
            no_slot_trigger_orders=sum(x['status']=='no_slot_rejected' for x in result.get('fixed_order_attempts',[])),
            insufficient_cash_trigger_orders=sum(x['status']=='insufficient_cash_rejected' for x in result.get('fixed_order_attempts',[])),
            partial_fill_orders=sum(0<x['filled_quantity']<x['requested_quantity'] for x in result.get('fixed_order_attempts',[]))))
        t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t)
        if comparisons:pd.DataFrame(comparisons).to_csv(output/'CURVE_COMPARISON.csv',index=False,encoding='utf-8-sig')
        if ordinal%5==0 or ordinal==len(starts):print(ordinal,len(starts),'gaps',len(gaps),flush=True)
    frame=pd.concat(curves,ignore_index=True);frame.to_parquet(output/'EQUITY_CURVES.parquet',index=False)
    pd.concat(trades,ignore_index=True).to_parquet(output/'TRADES.parquet',index=False)
    if args.fixed_ioc:pd.DataFrame(attempts).to_parquet(output/'FIXED_ORDER_ATTEMPTS.parquet',index=False)
    calculated=recompute_metrics(frame)
    calculated=calculated.merge(pd.DataFrame(operations),on='start_ordinal',validate='one_to_one')
    calculated.to_csv(output/'START_METRICS.csv',index=False,encoding='utf-8-sig')
    if not compare_original:
        bench=index.set_index('date').close
        calculated['annualized_excess']=[r.annualized_return-((float(bench.loc[end]/bench.loc[pd.Timestamp(r.start_date)]))**(365/(end-pd.Timestamp(r.start_date)).days)-1) for r in calculated.itertuples()]
        calculated.to_csv(output/'START_METRICS.csv',index=False,encoding='utf-8-sig')
        summary={'status':'complete' if not all_gaps else 'incomplete_action_audit','runs':len(starts),
            'start_range':[str(min(starts).date()),str(max(starts).date())],'end':str(end.date()),
            'cumulative_return_mean':float(calculated.cumulative_return.mean()),'cumulative_return_median':float(calculated.cumulative_return.median()),
            'annualized_return_mean':float(calculated.annualized_return.mean()),'annualized_excess_mean':float(calculated.annualized_excess.mean()),
            'beat_sse_fraction':float(calculated.annualized_excess.gt(0).mean()),'maximum_drawdown_mean':float(calculated.maximum_drawdown.mean()),
            'sharpe_mean':float(calculated.sharpe_zero_rf_252_ddof0.mean()),
            **{k+'_mean':float(calculated[k].mean()) for k in ['take_count','stop_count','expiry_count']},
            **{k+'_mean':float(calculated[k].mean()) for k in ['filled_orders','completed_trades','pending_orders_created','expired_entry_orders','failed_trigger_orders','no_slot_trigger_orders','insufficient_cash_trigger_orders','partial_fill_orders']},
            'unfilled_orders_mean':float((calculated.expired_entry_orders+calculated.failed_trigger_orders).mean()),
            'terminal_open_positions_max':int(calculated.open_positions_at_end.max()),'terminal_pending_orders_max':int(calculated.pending_orders_at_end.max()),
            'corporate_action_gaps':sorted(all_gaps),'production_account_changed':False}
        for path,h in hashes.items():assert digest(ROOT/path)==h
        (output/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'ACTION_GAPS.json').write_text(json.dumps(sorted(all_gaps),indent=2),encoding='utf-8')
        print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
        assert not all_gaps
        return
    from compute_risk_metrics import verify_metrics,build_summary,compare_nested
    verify_metrics(calculated,stored_metrics)
    summary=build_summary(calculated,calculated)
    previous=json.loads((BASE/'results/RISK_SUMMARY.json').read_text(encoding='utf-8'))
    compare_nested(summary,previous)
    assert not all_gaps and all(summary['assertions'].values())
    for path,h in hashes.items():assert digest(ROOT/path)==h,('Frozen source changed',path)
    outcome={'status':'ok','runs':58,'daily_curves_exactly_equal':all(x['exact_curve_equal'] for x in comparisons),
        'maximum_equity_abs_difference':max(x['max_equity_abs_difference'] for x in comparisons),
        'stored_metrics_equal_within_1e_12':True,'stored_risk_summary_equal_within_1e_12':True,'corporate_action_gaps':sorted(all_gaps),
        'recomputed_summary':summary,'production_account_changed':False,'original_results_overwritten':False}
    (output/'VERIFICATION.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(outcome,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
