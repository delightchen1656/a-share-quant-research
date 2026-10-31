"""Independent original-source parity audit, read-only protected market inputs.

Evidence is private under tracker/data/. Does not enter broker/account records.
"""
from __future__ import annotations
import ast
import gc
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import lightgbm as lgb
import numpy as np
import pandas as pd
import market

ARCHIVE=market.ROOT/'archive/hushen_2/pre_registration_research_20261020/research'

def original_function(file,name,namespace):
    tree=ast.parse(file.read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(file),'exec'),namespace)
    return namespace[name]

def reference_components(day):
    """Execute preserved original functions with temporary caches and only date bounds extended."""
    with tempfile.TemporaryDirectory(prefix='hushen2_reference_') as temporary:
        core=SimpleNamespace(FEATURE_START=pd.Timestamp('2018-01-01'),HARD_MAX_DATE=pd.Timestamp(day),
                             EVAL_START=pd.Timestamp('2020-01-01'),LAST_SIGNAL_DATE=pd.Timestamp(day))
        g={'np':np,'pd':pd,'CACHE':Path(temporary),'QFQ_ROOT':market.DATA/'qfq','core':core,
           'FEATURE_START':core.FEATURE_START,'HARD_MAX_DATE':core.HARD_MAX_DATE,
           'EVAL_START':core.EVAL_START,'LAST_SIGNAL_DATE':core.LAST_SIGNAL_DATE,
           'MODEL_FEATURES':market.FEATURES,'numeric':lambda x:pd.to_numeric(x,errors='coerce'),
           'FEATURE_COLUMNS':['vol60','overnight20','intraday20','turn20','mom60','mom20','vol20','ret5','mom120','close_to_high60']}
        model=original_function(ARCHIVE/'run_batch_002.py','build_model_panel',g)()
        technical=original_function(ARCHIVE/'run_batch.py','build_feature_panel',g)()
        # Source Batch004 calls both builders and merges their eligible universes before ranking.
        core.build_feature_panel=lambda:technical
        batch2=SimpleNamespace(build_model_panel=lambda:model,MODEL_DIR=market.BASE/'model',MODEL_FEATURES=market.FEATURES)
        g.update(core=core,batch2=batch2,lgb=lgb,RESULTS=Path(temporary)/'components',BASE_PANEL_CACHE=Path(temporary)/'base.parquet')
        original_function(ARCHIVE/'run_batch_004.py','rank_center',g)
        out=original_function(ARCHIVE/'run_batch_004.py','build_base_panel',g)()
        # Keep the original model/ranking functions, but explicitly adopt the ATR
        # emitted by the original price-TR technical builder (post-2024 replay policy).
        out['atr_pct']=technical.set_index(['date','symbol']).atr_pct.reindex(pd.MultiIndex.from_frame(out[['date','symbol']])).to_numpy()
        return out

def main():
    folder=Path(__file__).resolve().parent/'data'
    h=market.health(folder);day=h['market_date'];before,inputs=market.pipeline_identity(h)
    print('Independent source reference',day,flush=True)
    reference=reference_components(day)
    print('Reference complete',len(reference),flush=True)
    ref_path=folder/f'pipeline_reference_{day}_{market.PIPELINE_VERSION}.parquet'
    reference.to_parquet(ref_path,index=False)
    del reference;gc.collect()
    production=market.score_panel(market.feature_panel(day,lambda s:print(s,flush=True)))
    reference=pd.read_parquet(ref_path)
    assert production[['date','symbol']].equals(reference[['date','symbol']]), 'Original/production eligible universe differs'
    errors={}
    for col in reference.columns:
        if col in ('date','symbol'):continue
        error=float(np.max(np.abs(production[col].to_numpy()-reference[col].to_numpy())))
        errors[col]=error
        assert error<1e-12,(col,error)
    spec=json.loads((market.BASE/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))['selection']['factor_spec']
    g={'pd':pd,'EXECUTION':{'top_k':3}}
    original_m=original_function(ARCHIVE/'run_batch_004.py','component_m',g)
    original_t=original_function(ARCHIVE/'run_batch_004.py','component_t',g)
    original_h=original_function(ARCHIVE/'run_batch_004.py','component_h',g)
    candidates=original_function(ARCHIVE/'run_batch_004.py','candidate_signals',g)
    a_original=candidates(reference,'C04_NEW',original_m(reference,spec['M_internal']),original_t(reference,spec['T_internal']),original_h(reference,spec['H_internal']),spec['outer']).reset_index(drop=True)
    b_original=market.build_signals(production).reset_index(drop=True)
    pd.testing.assert_frame_equal(a_original,b_original,check_exact=False,rtol=0,atol=1e-12)
    # Independent expression: original top3 first, then inclusive threshold, no refill.
    feature_rows=reference[['date','symbol','f_log_amount','f_turn','vol60']].copy()
    feature_rows['size_proxy']=feature_rows.f_log_amount-np.log(feature_rows.f_turn.clip(lower=1e-6))
    a=a_original.merge(feature_rows[['date','symbol','size_proxy','vol60']],on=['date','symbol'],validate='one_to_one',sort=False)
    a=a.loc[a.atr_pct.ge(.025)&a.size_proxy.ge(16.901055936487055)&a.vol60.ge(.018471572551217057)].reset_index(drop=True)
    b=market.build_recommendations(production).reset_index(drop=True)
    assert a[['date','symbol']].equals(b[['date','symbol']]),'Filtered signal order differs'
    max_score_error=float((a.score-b.score).abs().max());assert max_score_error<1e-12
    # Causal replay at several historical cutoffs must agree with full-run signals on those dates.
    cutoff_checks={}
    for date in ['2020-03-31','2022-06-30','2024-11-22',day]:
        subset=production[production.date.le(pd.Timestamp(date))]
        if subset.empty:continue
        causal=market.build_recommendations(subset)
        expected=b[b.date.eq(pd.Timestamp(date))].reset_index(drop=True)
        actual=causal[causal.date.eq(pd.Timestamp(date))].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual,expected)
        cutoff_checks[date]=True
    after=market.health(folder)
    assert market.pipeline_identity(after)[0]==before,'Market changed during audit'
    latest=b[b.date.eq(pd.Timestamp(day))].copy()
    for row in latest.itertuples():
        raw=pd.read_parquet(market.DATA/'raw'/row.symbol[-2:]/f'{row.symbol}.parquet')
        raw=raw[pd.to_datetime(raw.date).eq(pd.Timestamp(day))]
        assert len(raw)==1 and np.isfinite(float(raw.close.iloc[0])) and float(raw.close.iloc[0])>0
    report={'status':'ok','market_date':day,'pipeline_id':before,'inputs':inputs,'reference_rows':len(reference),
            'reference_panel':str(ref_path.relative_to(market.ROOT)).replace('\\','/'),'execution_atr_policy':market.EXECUTION_ATR_POLICY,
            'eligible_universe_identical':True,'component_max_abs_errors':errors,'signals_checked':len(b),
            'unfiltered_signal_rows_checked':len(a_original),'unfiltered_signal_order_identical':True,
            'signal_filter':market.signal_filter_configuration(),'filter_applied_after_original_top3':True,'refill':False,
            'signal_order_identical':True,'max_abs_score_error':max_score_error,'causal_cutoff_checks':cutoff_checks,
            'source_hashes':{n:market.digest(ARCHIVE/n) for n in ['run_batch.py','run_batch_002.py','run_batch_004.py']},
            'latest_signal_count':len(latest),'next_session':next(d for d in h['sessions'] if d>day),
            'account_records_changed':False,'protected_market_data_changed':False,
            'scope':'Original frozen model/top3 parity, price-TR ATR, then registered P12 AND thresholds after top3; no refill. Not a new blind test.'}
    destination=folder/'pipeline_verification.json'
    if destination.exists():
        old=json.loads(destination.read_text(encoding='utf-8'))
        retained=folder/f"pipeline_verification_{old['pipeline_id']}.json"
        if not retained.exists():retained.write_bytes(destination.read_bytes())
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
