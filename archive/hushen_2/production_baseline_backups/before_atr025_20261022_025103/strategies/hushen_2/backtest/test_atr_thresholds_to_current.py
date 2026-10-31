"""Frozen four ATR thresholds extended to latest committed session; no production writes.

Reuses the exact preceding experiment's account-loop source with explicit audited
date/input adaptations, preserving the historical signal splice gap.
"""
from datetime import datetime
from pathlib import Path
import inspect
import json
import sys
import numpy as np
import pandas as pd
import test_atr_thresholds_pre2025 as prior
from run_june2020_starts import BASE, ROOT

sys.path.insert(0,str(BASE/'tracker'))
import market

SOURCE=prior.SOURCE
EXTRA=BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_201802/supplemental_actions.json'


def load_signals(out):
    old=pd.read_parquet(SOURCE/'FROZEN_SIGNALS.parquet')
    verified_path=BASE/'tracker/data/pipeline_verification.json'
    verified=json.loads(verified_path.read_text(encoding='utf-8'))
    assert verified['status']=='ok' and verified['signal_order_identical']
    assert verified['execution_atr_policy']==market.EXECUTION_ATR_POLICY
    for path,h in verified['inputs']['files'].items():
        # Market inventory legitimately advanced after the saved verification;
        # frozen signal implementation and models may not have changed.
        if path.startswith('strategies/hushen_2/runtime/') or path.startswith('strategies/hushen_2/model/'):
            assert market.digest(ROOT/path)==h,(path,'frozen runtime/model mismatch')
    panel_path=ROOT/verified['reference_panel']
    panel=pd.read_parquet(panel_path,filters=[('date','<=',prior.LAST)])
    assert panel.date.max()==prior.LAST
    rebuilt=market.build_signals(panel)
    assert rebuilt.date.max()==prior.LAST
    # The old pre-2025 source intentionally ended its signals 37 days before
    # 2024 year end. Do not fill that gap as part of an ATR-only comparison.
    common=rebuilt.merge(old[['date','symbol','score','atr_pct']],on=['date','symbol'],suffixes=('_rebuilt','_old'),validate='one_to_one')
    common_days=rebuilt[rebuilt.date.isin(old.date)]
    score_delta=float((common.score_rebuilt-common.score_old).abs().max())
    atr_delta=float((common.atr_pct_rebuilt-common.atr_pct_old).abs().max())
    old_missing=old.merge(rebuilt[['date','symbol']],on=['date','symbol'],how='left',indicator=True)
    old_missing=old_missing.loc[old_missing._merge.eq('left_only')].drop(columns='_merge')
    new_replacements=common_days.merge(old[['date','symbol']],on=['date','symbol'],how='left',indicator=True)
    new_replacements=new_replacements.loc[new_replacements._merge.eq('left_only')].drop(columns='_merge')
    # Historical frozen signals remain authoritative. A later verified production
    # reference is used ONLY for the newly mature session, not to revise history.
    old_missing.to_parquet(out/'REFERENCE_OLD_MEMBERSHIP_DIFFERENCES.parquet',index=False)
    new_replacements.to_parquet(out/'REFERENCE_NEW_MEMBERSHIP_DIFFERENCES.parquet',index=False)
    common.to_parquet(out/'REFERENCE_MATCHED_SIGNAL_COMPARISON.parquet',index=False)
    old_end=old.date.max()
    addition=rebuilt.loc[rebuilt.date.gt(old_end)&rebuilt.date.le(prior.LAST)].copy()
    assert len(addition)==3 and addition.date.eq(prior.LAST).all()
    result=pd.concat([old,addition[old.columns]],ignore_index=True)
    result=result.loc[result.date.le(prior.LAST)].sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable')
    assert not result.duplicated(['date','symbol']).any()
    verification=dict(status='verified',old_rows=len(old),old_signal_end=str(old_end.date()),
        latest_signal_cutoff=str(prior.LAST.date()),added_rows=len(addition),
        addition=addition[['date','symbol','score','atr_pct']].assign(date=addition.date.astype(str)).to_dict('records'),
        rebuilt_reference_old_membership_identical=len(old_missing)==0,old_rows_missing_from_later_reference=len(old_missing),
        old_missing_records=old_missing.assign(date=old_missing.date.astype(str)).to_dict('records'),
        rebuilt_reference_max_abs_score_delta=score_delta,rebuilt_reference_max_abs_atr_delta=atr_delta,
        reference_difference_note='Later verified production intersection panel differs from frozen historical signal source on scattered dates in 2021-2026, not merely initial warmup. No historical replacement is made; causes beyond source-version differences are not established here.',
        preserved_gap_policy='All old signals retained unchanged; only append dates later than old post-2024 cutoff. No backfill of 2024 maturity-tail splice gap.',
        reference_panel=str(panel_path.relative_to(ROOT)),reference_panel_sha256=market.digest(panel_path),
        verification_sha256=market.digest(verified_path),production_changed=False)
    (out/'SIGNAL_EXTENSION_VERIFICATION.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SIGNAL_EXTENSION',json.dumps(verification,ensure_ascii=False),flush=True)
    return result


def main():
    health=market.health(BASE/'tracker/data')
    assert not health['missing_models']
    prior.END=pd.Timestamp(health['market_date']);prior.LAST=prior.END-pd.Timedelta(days=37)
    assert prior.END==pd.Timestamp('2026-10-21'),('Unexpected date; review extension assumptions first',prior.END)
    before_inventory=market.input_inventory()
    prior.load_signals=load_signals
    source=inspect.getsource(prior.main)
    replacements=[
        ("parser=argparse.ArgumentParser();parser.add_argument('--extra-actions',type=Path);args=parser.parse_args()",
         "parser=argparse.ArgumentParser();parser.add_argument('--extra-actions',type=Path,default=EXTRA);args=parser.parse_args()"),
        ("BASE/'results/holdout_restricted/atr_thresholds_pre2025'", "BASE/'results/holdout_restricted/atr_thresholds_to_current'"),
        ("signals=pd.read_parquet(SOURCE/'FROZEN_SIGNALS.parquet',filters=[('date','<=',LAST)])", "signals=load_signals(out)"),
        ("2020<=int(k.split('/')[-1])<=2024", "2020<=int(k.split('/')[-1])<=END.year"),
        ("range(2020,2025)", "range(2020,END.year+1)"),
        ("INPUT_SIGNALS_PRE2025.parquet", "INPUT_SIGNALS.parquet"),
        ("All simulation bars/signals/actions/metrics <=2024-12-31. Fixed registered model, no training or post-2024 evaluation. Root has prior posterior exposure: not a fresh blind experiment.",
         "Four previously specified thresholds frozen. Posterior extension through latest committed session; no training, tuning, or production changes. Prior posterior exposure: not a fresh blind experiment."),
    ]
    for old,new in replacements:
        assert old in source,old
        source=source.replace(old,new)
    # Keep the original experiment source as the loop implementation, but log
    # both the entry-point bytes and the complete adapted source in the output.
    prior.__dict__.update(EXTRA=EXTRA,__file__=__file__)
    exec(compile(source,'<frozen_atr_four_thresholds_to_current>','exec'),prior.__dict__)
    prior.main()
    assert market.health(BASE/'tracker/data')['audit_sha256']==health['audit_sha256']
    assert market.input_inventory()==before_inventory


if __name__=='__main__':main()
