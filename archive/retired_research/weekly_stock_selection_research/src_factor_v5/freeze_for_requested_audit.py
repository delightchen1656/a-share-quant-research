"""Freeze user-requested exploratory post-period comparison without reading audit results."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json
import datetime
import shutil
import platform
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from settings import BASE,OLD,PRIOR,OUT,INPUTS,CORE,PRIOR_NEW,BASE_FACTORS,variants,sha,dump,install_read_boundary


def main():
    install_read_boundary()
    decision=json.loads((OUT/'decision.json').read_text(encoding='utf-8'))
    assert decision['best_exploratory_variant']=='combine__long_momentum'
    features=decision['best_exploratory_features']
    assert features==CORE+['momentum120']==variants()['combine__long_momentum']
    spec=json.loads((OUT/'spec.json').read_text(encoding='utf-8'))
    assert json.loads((OUT/'validation.json').read_text(encoding='utf-8'))['passed']
    assert json.loads((OUT/'fit_complete.json').read_text(encoding='utf-8'))['model_fits']==180
    previous=PRIOR/'frozen_candidate_v1'
    assert sha(previous/'FREEZE_MANIFEST.json')=='b3fe17097b531e35bf984685eb4a2bce93d9cc7f435d0b6bbce7c4128c57390b'
    oldmanifest=json.loads((previous/'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    for row in oldmanifest['files']:
        assert sha(previous/row['path'])==row['sha256']
    frozen=OUT/'frozen_exploratory_requested_v1'
    assert not frozen.exists(),'Never overwrite a post-period comparison freeze'
    frozen.mkdir()
    policy=dict(user_request='后验效果呢',
        interpretation='User requests post-period effect of this-round best exploratory feature set; fixed comparison to previous11factor anchor.',
        exploratory_variant='combine__long_momentum',development_upgrade_gate_passed=decision['upgrade_eligible'],
        retained_development_choice_unchanged='anchor11',
        training_boundary='2023-12-31',postperiod='Same2025-2026input snapshot and exact cutoff as prior completed audit; do not refresh or extend.',
        audit_type='Additional posthoc comparison on previously used period, NOT new independent blind validation.',
        no_feedback='Optimizer does not read postperiod quotes/labels/results/figures; subagent returns only status and paths. No factors/parameters/candidate changes based on outcome.',
        model_policy='Candidate fitted once on matured2018-2023labels; baseline exact byte copy of prior11factor frozen model. No audit retraining or selection.',
        scope='This one exploratory candidate and one fixed baseline only; no extra candidate, tuning or account backtest.')
    dump(frozen/'REQUEST_POLICY.json',policy)
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    prior_features=pd.read_parquet(PRIOR/'new_factor_panel.parquet')
    assert panel[['signal_date','symbol']].equals(prior_features[['signal_date','symbol']])
    panel[PRIOR_NEW]=prior_features[PRIOR_NEW]
    ranks=panel.groupby('signal_date')[features].rank(pct=True,na_option='keep')
    train=panel.label_maturity_date.le('2023-12-31')&panel.ordinary_quote_excess.notna()
    assert panel.loc[train,'label_maturity_date'].max()<='2023-12-31'
    med=ranks.loc[train].median()
    weights=(1/panel.loc[train].groupby('signal_date').symbol.transform('size')).to_numpy()
    weights/=weights.mean()
    scaler=StandardScaler().fit(ranks.loc[train].fillna(med),sample_weight=weights)
    model=HistGradientBoostingRegressor(**spec['fixed_HGB'])
    model.fit(scaler.transform(ranks.loc[train].fillna(med)),panel.loc[train,'ordinary_quote_excess'],sample_weight=weights)
    joblib.dump(dict(role='candidate',features=features,medians=med,scaler=scaler,model=model,training_end='2023-12-31'),frozen/'candidate.joblib',compress=3)
    shutil.copy2(previous/'candidate.joblib',frozen/'baseline.joblib')
    assert sha(frozen/'baseline.joblib')==sha(previous/'candidate.joblib')
    for name in ['runtime.py','factor_functions.py']:
        shutil.copy2(previous/name,frozen/name)
    protocol=json.loads((previous/'protocol.json').read_text(encoding='utf-8'))
    protocol.update(selected_variant='combine__long_momentum',ordered_candidate_features=features,baseline_features=CORE,
        baseline_external_role='baseline.joblib is exact prior11factor candidate.joblib; internal pack role remains candidate. Report by frozen filename/external role.',
        timing='Same MondayOpen-TuesdayClose dates and exact input cutoff as prior completed2025-2026audit; no expanded dates.',
        audit_sources='Reuse exact prior audit snapshots, calendar, index and schedule. Derive missing momentum120 from those same raw warmup snapshots if needed. No new current-market queries or updates.',
        known_context='Additional user-requested posthoc comparison on already-used stock period. Optimizer has never read postperiod performance. Candidate is exploratory and failed prior development upgrade gate; audit does not change that decision.',
        stop_policy='Exactly candidate plus11factor baseline; no retraining/tuning/replacement or passing performance back to optimization.')
    dump(frozen/'protocol.json',protocol)
    dump(frozen/'environment.json',dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__,joblib=joblib.__version__))
    files=sorted(p for p in frozen.iterdir() if p.is_file())
    dump(frozen/'FREEZE_MANIFEST.json',dict(frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_this_candidate_postperiod_evaluation=True,additional_posthoc_comparison_not_fresh_blind_test=True,
        training_rows=int(train.sum()),training_label_latest=panel.loc[train,'label_maturity_date'].max(),
        prior_anchor_model_sha256=sha(previous/'candidate.joblib'),
        development_decision_sha256=sha(OUT/'decision.json'),
        files=[dict(path=p.name,sha256=sha(p)) for p in files]))
    print('FROZEN:',frozen,flush=True)
    print('FREEZE_MANIFEST_SHA256:',sha(frozen/'FREEZE_MANIFEST.json'),flush=True)


if __name__=='__main__':
    main()
