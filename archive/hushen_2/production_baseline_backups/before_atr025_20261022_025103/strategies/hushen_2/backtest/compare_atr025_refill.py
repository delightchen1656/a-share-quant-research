"""Research-only ATR025 refill comparison; never changes production or the ledger.

Scores are computed on the FULL original universe before the ATR filter. The
refill variant selects the first three eligible scores; it never re-ranks factor
components on the ATR-reduced universe.
"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import argparse
import inspect
import json
import sys
import shutil

import lightgbm as lgb
import numpy as np
import pandas as pd

from run_june2020_starts import BASE, ROOT, ARCHIVE, module, action_inputs
from baseline_fixed_ioc import fixed_ioc_engine
from compute_risk_metrics import recompute_metrics
from test_atr_thresholds_pre2025 import digest
sys.path.insert(0, str(BASE/'runtime'))
import frozen_builder as builder
from strategy import FACTOR_SPEC
sys.path.insert(0, str(BASE/'tracker'))
import market

PRIOR=BASE/'results/holdout_restricted/atr025_annual_post2024/attempt_20261022_001047'
UNFILTERED=BASE/'results/holdout_restricted/atr_thresholds_to_current/attempt_20261021_202807/INPUT_SIGNALS.parquet'
END=pd.Timestamp('2026-10-21')
LAST=END-pd.Timedelta(days=37)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def original_scored(panel):
    out=panel[['date','symbol','close','atr_pct']].copy()
    out['score']=(.6*builder.component_m(panel,tuple(FACTOR_SPEC['M_internal']))
                  +.4*builder.component_h(panel,tuple(FACTOR_SPEC['H_internal'])))
    return out.dropna(subset=['score']).sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable')


def prepare(out,audit):
    old=pd.read_parquet(UNFILTERED)
    assert old.date.max()==LAST and not old.duplicated(['date','symbol']).any()
    # Pre-2025 uses the preserved COMPLETE component panel, not the current
    # production re-computation which has known scattered historical differences.
    pre=original_scored(pd.read_parquet(audit.reopt.PANEL_PATH))
    tech_path=ARCHIVE/'cache/feature_panel_pre2025.parquet'
    tech=pd.read_parquet(tech_path,columns=['date','symbol','atr_pct'])
    pre=pre.drop(columns='atr_pct').merge(tech,on=['date','symbol'],how='left',validate='one_to_one')
    assert pre.atr_pct.notna().all()
    # Reproduce the ORIGINAL posterior feature/score arithmetic and its 2025
    # smoothing boundary. Only the model location is redirected to the already
    # registered lossless frozen Hushen2 files. No training or restoration occurs.
    source=ARCHIVE/'results/holdout_restricted/batch_006_defense_post2024_audit/run_post2024_audit.py'
    text=source.read_text(encoding='utf-8')
    start=text.index('def build_component_panel(')
    end=text.index('\ndef make_frozen_signals(',start)
    # The transactional pre-update backups retain the actual Oct-19 data vintage
    # used for the frozen historical predictions. Use them read-only rather than
    # silently introducing later adjustment rounding into the full rankings.
    snapshot=ROOT/'data_updates/20261020/before_update/sh_sz_market_research/data_pipeline/data/qfq'
    snapshot_paths=[snapshot/p.parent.name/p.name if (snapshot/p.parent.name/p.name).exists() else p
                    for p in sorted((market.DATA/'qfq').glob('*/*.parquet'))]
    namespace=dict(pd=pd,np=np,lgb=lgb,QFQ_ROOT=SimpleNamespace(glob=lambda pattern:snapshot_paths),START=pd.Timestamp('2025-01-01'),
                   numeric=lambda s:pd.to_numeric(s,errors='coerce'),batch2=SimpleNamespace(MODEL_FEATURES=market.FEATURES),
                   MODEL_DIR=BASE/'model')
    exec(compile(text[start:end],str(source),'exec'),namespace)
    post_cache=out/'REBUILT_POST_SCORES.parquet'
    if post_cache.exists():post=pd.read_parquet(post_cache)
    else:
        post=namespace['build_component_panel'](pd.Timestamp('2026-09-11'))
        post.to_parquet(post_cache,index=False)
    post['score']=.6*post.M+.4*post.H
    post=post[['date','symbol','close','atr_pct','score']]
    # Only the newly appended mature session uses the same verified reference
    # as the previous experiment; preserve its historical 2024 splice gap.
    verified=json.loads((BASE/'tracker/data/pipeline_verification.json').read_text(encoding='utf-8'))
    reference_path=ROOT/verified['reference_panel']
    reference=pd.read_parquet(reference_path,filters=[('date','<=',LAST)])
    addition=original_scored(reference)
    addition=addition.loc[addition.date.eq(LAST)]
    all_scores=pd.concat([pre,post,addition],ignore_index=True)
    all_scores=all_scores.loc[all_scores.date.isin(old.date)].sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable')
    assert not all_scores.duplicated(['date','symbol']).any()
    top=all_scores.groupby('date',sort=False).head(3)
    joined=old.merge(top,on=['date','symbol'],how='outer',suffixes=('_old','_rebuilt'),indicator=True)
    missing=joined.loc[~joined._merge.eq('both')].copy()
    both=joined.loc[joined._merge.eq('both')]
    parity=dict(original_rows=len(old),rebuilt_rows=len(top),membership_differences=len(missing),
                score_max_abs_error=float((both.score_old-both.score_rebuilt).abs().max()),
                atr_max_abs_error=float((both.atr_pct_old-both.atr_pct_rebuilt).abs().max()),
                complete_panel_rows=len(all_scores),reference_panel=str(reference_path),
                input_hashes={str(p):digest(p) for p in [UNFILTERED,audit.reopt.PANEL_PATH,tech_path,source,reference_path]})
    missing.to_parquet(out/'REBUILD_DIFFERENCES.parquet',index=False)
    save(out/'RANKING_VERIFICATION.json',parity)
    both.to_parquet(out/'MATCHED_TOP3_NUMERICAL_COMPARISON.parquet',index=False)
    print('RANKING',json.dumps(parity),flush=True)
    assert not len(missing), 'Original ranking membership could not be exactly reproduced; no comparison published'
    assert parity['score_max_abs_error']<1e-12 and parity['atr_max_abs_error']<1e-12
    all_scores['original_rank']=all_scores.groupby('date',sort=False).cumcount()+1
    # No score or winner substitution: both variants use the proven identical
    # full-universe scores. The old top3 input supplies an exact control.
    all_scores['factor']='C04_NEW'
    refill=all_scores.loc[all_scores.atr_pct.ge(.025)].groupby('date',sort=False).head(3).copy()
    no_refill=old.loc[old.atr_pct.ge(.025)].copy()
    no_refill=no_refill.merge(all_scores[['date','symbol','original_rank']],on=['date','symbol'],validate='one_to_one')
    common=refill.merge(no_refill[['date','symbol']],on=['date','symbol'],how='inner')
    assert len(common)==len(no_refill)
    assert len(refill)>=len(no_refill) and refill.groupby('date').size().le(3).all()
    refill.to_parquet(out/'REFILL_SIGNALS.parquet',index=False)
    no_refill.to_parquet(out/'NO_REFILL_SIGNALS.parquet',index=False)
    save(out/'SIGNAL_COUNTS.json',dict(no_refill=len(no_refill),refill=len(refill),
         added_from_rank4_plus=int(refill.original_rank.gt(3).sum()),
         affected_days=int(refill.loc[refill.original_rank.gt(3),'date'].nunique()),
         minimum_atr=.025,maximum_daily_signals=3,filter_before_component_ranking=False))
    return {'no_refill':no_refill,'refill':refill}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reuse-output',type=Path)
    parser.add_argument('--prepared-from',type=Path);parser.add_argument('--extra-actions',type=Path)
    args=parser.parse_args()
    root=BASE/'results/holdout_restricted/atr025_refill_comparison'
    out=args.reuse_output or root/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    assert out.resolve().parent==root.resolve()
    out.mkdir(parents=True,exist_ok=bool(args.reuse_output));print('OUTPUT',out,flush=True)
    assert market.health(BASE/'tracker/data')['market_date']==str(END.date())
    protected=[BASE/'CURRENT_SELECTION.json',BASE/'tracker/data/ledger.sqlite3',BASE/'tracker/data/market_status.json',
               BASE/'tracker/market.py',BASE/'tracker/service.py',BASE/'runtime/signal_policy.py']
    protected+=list((BASE/'model').glob('*'))
    before={str(p):digest(p) for p in protected if p.is_file()}
    inventory=market.input_inventory()
    audit=module('atr025_refill_original_audit',ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py')
    audit.END_CURRENT=END
    if args.prepared_from:
        assert args.prepared_from.resolve().parent==root.resolve()
        ranking=json.loads((args.prepared_from/'RANKING_VERIFICATION.json').read_text(encoding='utf-8'))
        assert ranking['membership_differences']==0 and ranking['score_max_abs_error']==0 and ranking['atr_max_abs_error']==0
        for path,h in ranking['input_hashes'].items():assert digest(Path(path))==h
        for name in ['REFILL_SIGNALS.parquet','NO_REFILL_SIGNALS.parquet','RANKING_VERIFICATION.json','SIGNAL_COUNTS.json','MATCHED_TOP3_NUMERICAL_COMPARISON.parquet']:
            assert not (out/name).exists();shutil.copyfile(args.prepared_from/name,out/name)
    if (out/'REFILL_SIGNALS.parquet').exists():
        variants={key:pd.read_parquet(out/f'{key.upper()}_SIGNALS.parquet') for key in ['no_refill','refill']}
    else:variants=prepare(out,audit)
    source=inspect.getsource(audit.load_raw).replace('pd.read_parquet(path, columns=columns)',
        "pd.read_parquet(path, columns=columns, filters=[('date','>=',pd.Timestamp('2020-01-01')),('date','<=',END_CURRENT)])")
    exec(compile(source,'<bounded_refill_raw>','exec'),audit.__dict__)
    symbols=set(pd.concat(list(variants.values())).symbol)
    bars,calendar,raw=audit.load_raw(symbols)
    for key,s in variants.items():
        s=s.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
        assert s.close.notna().all()
        variants[key]=s.sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable').reset_index(drop=True)
    actions,known,action_sources=audit.load_actions()
    # Preserve all prior events, then add verified receipts ONLY for missing
    # stock-years. Refilling can introduce new holdings, so coverage is checked.
    extra_events,extra_known,extra_sources,resolutions,conflicts=action_inputs(END,start='2020-01-01')
    for (day,symbol),events in extra_events.items():
        if f'{symbol}/{day.year}' not in known:actions[(day,symbol)]=events
    known|=extra_known
    receipts=[BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_201802/supplemental_actions.json']
    if args.extra_actions:receipts.append(args.extra_actions)
    for path in receipts:
        payload=json.loads(path.read_text(encoding='utf-8'))
        assert payload['report_receipts'] and all(r['error_code']=='0' for r in payload['report_receipts'])
        extra_sources[str(path)]=digest(path)
        for key,records in payload['records'].items():
            if key in known:continue
            known.add(key);symbol=key.split('/')[0]
            for row in records:
                if not row.get('dividOperateDate'):continue
                day=pd.Timestamp(row['dividOperateDate'])
                if not pd.Timestamp('2020-01-01')<=day<=END:continue
                number=lambda k:float(str(row.get(k,0)).strip() or 0)
                event=dict(cash=number('dividCashPsBeforeTax'),stock=number('dividStocksPs')+number('dividReserveToStockPs'),
                    taxable_stock=number('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or day),
                    release=pd.Timestamp(row.get('dividStockMarketDate') or day),source=row.get('source','verified BaoStock receipt'))
                actions.setdefault((day,symbol),[]).append(event)
    core=fixed_ioc_engine(audit.core,manual_expiry_open=False,filled_slots=False)
    delists=audit.load_delistings()
    index=pd.read_parquet(PRIOR/'SSE_PRICE_INDEX.parquet');ic=index.set_index('date').close
    assert index.date.tolist()==calendar
    protocol=dict(end=str(END.date()),last_signal_cutoff=str(LAST.date()),threshold=.025,slots=5,initial_cash=100000,
        execution=core.policy,variants=['original top3 then ATR filter; no refill','full original scores then ATR filter; top3 eligible'],
        unchanged='Full-universe factor scores, price-TR ATR, original signal date gap, fixed-IOC, fees/slippage, actions, 37-day maturity tail',
        posterior_audit_only=True,not_a_new_blind_test=True,production_changed=False,
        protected_before=before,input_signals=str(UNFILTERED),extra_action_sources=extra_sources,
        action_sources=action_sources,script_sha256=digest(Path(__file__)))
    save(out/'PROTOCOL.json',protocol)
    shutil.copyfile(Path(__file__),out/'RUNNER_SNAPSHOT.py')
    (out/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    summaries=[];all_gaps=set();all_conflicts=[]
    for variant,signals in variants.items():
        for label,year,expected in [('2020_to_current',2020,58),('2025_to_current',2025,57)]:
            folder=out/variant/label;folder.mkdir(parents=True,exist_ok=True)
            starts=[d for d in calendar if d.year==year and d.month<=3];assert len(starts)==expected
            metrics=[];curves=[];trades=[];attempts=[];raw_results=[]
            for ordinal,start in enumerate(starts,1):
                if (folder/'START_METRICS.parquet').exists():break
                core.EVAL_START=start;core.HARD_MAX_DATE=END;core.LAST_SIGNAL_DATE=LAST;core.YEARS=list(range(year,END.year+1))
                gaps=set();curve=[]
                result,t=core.simulate(signals.loc[signals.date.between(start,LAST)],bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
                    keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,delist_dates=delists,slots=5,equity_curve_sink=curve)
                a=pd.DataFrame(result['fixed_order_attempts']);a['start_ordinal']=ordinal;a['start_date']=start
                assert not a.duplicated(['symbol','signal_date']).any()
                fills=int(a.filled_quantity.gt(0).sum());zero=int(a.filled_quantity.eq(0).sum())
                counts=t.reason.value_counts().to_dict() if len(t) else {}
                assert fills==result['filled_orders']==sum(counts.values())+result['open_positions_at_end']
                assert result['pending_orders_created']==fills+zero+result['expired_entry_orders']+result['pending_orders_at_end']
                assert not result['open_positions_at_end'] and not result['pending_orders_at_end']
                c=pd.DataFrame(curve);c['start_ordinal']=ordinal;c['start_date']=start
                m=recompute_metrics(c).iloc[0].to_dict()
                bench=float((ic.loc[END]/ic.loc[start])**(365/(END-start).days)-1)
                m.update(benchmark_annualized=bench,annualized_excess=m['annualized_return']-bench,
                    filled_orders=fills,unfilled_orders=zero+result['expired_entry_orders'],
                    pending_orders_created=result['pending_orders_created'],expired_entry_orders=result['expired_entry_orders'],
                    failed_trigger_orders=zero,partial_fill_orders=int(a.status.eq('partial_remainder_cancelled').sum()),
                    take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
                    open_positions_at_end=result['open_positions_at_end'],pending_orders_at_end=result['pending_orders_at_end'],raw_action_gaps=sorted(gaps))
                metrics.append(m);curves.append(c);t['start_ordinal']=ordinal;t['start_date']=start;trades.append(t);attempts.append(a)
                raw_results.append({k:v for k,v in result.items() if k!='fixed_order_attempts'})
                if ordinal%10==0 or ordinal==expected:print(variant,label,ordinal,expected,flush=True)
            if metrics:
                f=pd.DataFrame(metrics);c=pd.concat(curves,ignore_index=True);t=pd.concat(trades,ignore_index=True);a=pd.concat(attempts,ignore_index=True)
                for name,frame in [('START_METRICS',f),('EQUITY_CURVES',c),('TRADES',t),('FIXED_ORDER_ATTEMPTS',a)]:frame.to_parquet(folder/f'{name}.parquet',index=False)
                save(folder/'RAW_RESULTS.json',raw_results)
            else:
                f=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet')
            if variant=='no_refill':
                prior_c=pd.read_parquet(PRIOR/label/'EQUITY_CURVES.parquet')
                pd.testing.assert_frame_equal(c[['start_ordinal','date','equity']].reset_index(drop=True),prior_c[['start_ordinal','date','equity']].reset_index(drop=True),check_exact=True)
            gaps=set(k for ks in f.raw_action_gaps for k in ks)
            # Missing-key resolution must prove that no held window crossed
            # the actual official action date; a receipt is not blanket coverage.
            official=json.loads((BASE/'results/holdout_restricted/atr_thresholds_to_current/attempt_20261021_202807/official_000026/OFFICIAL_ACTION_RECEIPT.json').read_text(encoding='utf-8'))
            if official['key'] in gaps:
                for doc in official['documents']:assert digest(Path(doc['local_file']))==doc['sha256']
                sym,y=official['key'].split('/')
                held=t.loc[t.symbol.eq(sym)]
                for event in official['records'][official['key']]:
                    if event.get('dividOperateDate'):
                        day=pd.Timestamp(event['dividOperateDate'])
                        assert not (held.entry_date.lt(day)&held.exit_date.ge(day)).any(),('Needs official action replay',variant,label,day)
                gaps.remove(official['key'])
            all_gaps|=gaps
            for conflict in conflicts:
                held=t.loc[t.symbol.eq(conflict['symbol'])];day=pd.Timestamp(conflict['date'])
                if (held.entry_date.lt(day)&held.exit_date.ge(day)).any():all_conflicts.append(dict(variant=variant,group=label,conflict=conflict))
            fields=['annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0','filled_orders','unfilled_orders','take_count','stop_count','expiry_count','pending_orders_created']
            summary=dict(variant=variant,group=label,runs=len(f),signals=int(signals.date.ge(starts[0]).sum()),
                         means={k:float(f[k].mean()) for k in fields},unresolved_action_gaps=sorted(gaps))
            summaries.append(summary);save(folder/'SUMMARY.json',summary);print('SUMMARY',json.dumps(summary),flush=True)
    unchanged={p:digest(Path(p))==h for p,h in before.items()}
    assert all(unchanged.values()) and market.input_inventory()==inventory
    report=dict(status='verified' if not all_gaps and not all_conflicts else 'incomplete_action_audit',end=str(END.date()),summaries=summaries,
                unresolved_action_gaps=sorted(all_gaps),held_action_conflicts=all_conflicts,
                no_refill_control_exactly_matches_prior=True,protected_unchanged=unchanged,software_account_changed=False)
    save(out/'COMPARISON.json',report)
    print('FINAL',json.dumps(report,ensure_ascii=False),flush=True)
    assert not all_gaps and not all_conflicts


if __name__=='__main__':main()
