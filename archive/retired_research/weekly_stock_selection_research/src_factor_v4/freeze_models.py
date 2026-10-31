"""Train final pre2024models once and hash a self-contained, immutable audit package."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import inspect
import datetime
import platform
import shutil
import sys
import json
import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from settings import BASE,OLD,OUT,INPUTS,BASE_FACTORS,NEW_FACTORS,quotes_valid,new_features,variants,sha,dump


def main():
    assert json.loads((OUT/'feature_validation.json').read_text(encoding='utf-8'))['passed']
    assert json.loads((OUT/'fit_complete.json').read_text(encoding='utf-8'))['model_fits']==225
    decision=json.loads((OUT/'final_development_decision.json').read_text(encoding='utf-8'))
    assert decision['policy_sha256']==sha(OUT/'ONE_WAY_AUDIT_POLICY.json')
    spec=json.loads((OUT/'spec.json').read_text(encoding='utf-8'))
    selected=decision['selected_variant']
    assert decision['features']==variants()[selected]
    frozen=OUT/'frozen_candidate_v1'
    assert not frozen.exists(),'Never overwrite a frozen audit candidate'
    frozen.mkdir()
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    new=pd.read_parquet(OUT/'new_factor_panel.parquet')
    assert panel[['signal_date','symbol']].equals(new[['signal_date','symbol']])
    panel[NEW_FACTORS]=new[NEW_FACTORS]
    all_factors=BASE_FACTORS+NEW_FACTORS
    xs=panel.groupby('signal_date')[all_factors].rank(pct=True,na_option='keep')
    train=panel.label_maturity_date.le('2023-12-31')&panel.ordinary_quote_excess.notna()
    assert panel.loc[train,'label_maturity_date'].max()<='2023-12-31'
    weights=(1/panel.loc[train].groupby('signal_date').symbol.transform('size')).to_numpy()
    weights/=weights.mean()
    for role,features in [('baseline',BASE_FACTORS),('candidate',decision['features'])]:
        med=xs.loc[train,features].median()
        scaler=StandardScaler().fit(xs.loc[train,features].fillna(med),sample_weight=weights)
        model=HistGradientBoostingRegressor(**spec['fixed_HGB'])
        model.fit(scaler.transform(xs.loc[train,features].fillna(med)),panel.loc[train,'ordinary_quote_excess'],sample_weight=weights)
        pack=dict(role=role,features=features,medians=med,scaler=scaler,model=model,training_end='2023-12-31')
        joblib.dump(pack,frozen/f'{role}.joblib',compress=3)
    shutil.copy2(BASE/'src_factor_v4/runtime.py',frozen/'runtime.py')
    function_source='import numpy as np\nimport pandas as pd\n\n'+inspect.getsource(quotes_valid)+'\n\n'+inspect.getsource(new_features)
    function_source=function_source.replace('assert list(f.columns)==NEW_FACTORS',f'assert list(f.columns)=={NEW_FACTORS!r}')
    (frozen/'factor_functions.py').write_text(function_source,encoding='utf-8')
    protocol=dict(boundary_version='public-pre2025-v2',role='one-way post-freeze auditor, not isolated factor developer',
        selected_variant=selected,ordered_candidate_features=decision['features'],baseline_features=BASE_FACTORS,
        training_end='2023-12-31',fixed_models_no_retraining=True,
        data_prefixes=['600','601','603','605','000','001','002','003'],
        warmup='Use2018-2023local whitelist unchanged plus authorized2024+raw history as trailing-feature warmup. New historical entrants need120observed valid bars. No current status/delisting metadata filter.',
        pool='Positive active quotes/nonST at signal close, close>=3CNY, cumulative valid count>=120, last20active coverage>=0.9, median last20amount>=20millionCNY. Exactly runtime.py semantics.',
        information='Last actual market close before Monday open; cross-sectional percentiles from that signal eligible pool; frozen medians/scaler/model; deterministic score descending/symbol ascending top10.',
        timing='Monday actual open to Tuesday actual close. Both endpoints open, else skip, no shifted weekdays. Audit2025-2026latest verified complete committed market cutoff, exclude immature final week.',
        label='Same original ordinary quote proxy: both endpoint active positive valid quotes and Tuesdaypreclose matches Mondayclose within0.015. Else unknown; never zero, never pre-entry pool deletion.',
        metric='Each weekly top10known ordinary gross returns averaged, then equal-weight weeks. Original selected denominators/unknown counts retained. Per-year/YTD and cumulative arithmetic mean lines, not annualized NAV.',
        constraints='Report opening_upper_limit/no-active/nonST buy flags and Tuesdaylower-limit/no-active exit flags without deleting selected signals. No fee/fill/portfolio assertion.',
        audit_sources='Only protected rawKline and official calendar metadata via unified entry after verifying update audit/metadata commit/process. SSE independent read-only query via tools/daily_market_update.py if needed; never launch duplicate update.',
        stop_policy='One audit of candidate and baseline only. No new factor tuning, seed/model/threshold search, replacement candidates or suggestions to optimizer.',
        reporting_firewall='Write full results only to audit directory. Return to parent only completion/error status and paths, NEVER any period performance, relative ranking, factor or tuning advice.',
        original_whitelist_manifest_sha256=sha(INPUTS/'kline_dev_v1/manifest.json'),
        known_context='Overall index timing was already searched on later dates. Audit is optimizer-blind factor audit, not historically untouched whole-process validation. Universe/company-action completeness remains conditional.')
    dump(frozen/'protocol.json',protocol)
    dump(frozen/'environment.json',dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,sklearn=sklearn.__version__,joblib=joblib.__version__))
    files=[p for p in frozen.iterdir() if p.is_file()]
    dump(frozen/'FREEZE_MANIFEST.json',dict(frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_audit_data_read=True,policy_sha256=sha(OUT/'ONE_WAY_AUDIT_POLICY.json'),
        selection_decision_sha256=sha(OUT/'final_development_decision.json'),
        training_rows=int(train.sum()),training_label_latest=panel.loc[train,'label_maturity_date'].max(),
        files=[dict(path=p.name,sha256=sha(p)) for p in sorted(files)]))
    print('FROZEN:',frozen,flush=True)
    print('Manifest sha256:',sha(frozen/'FREEZE_MANIFEST.json'),flush=True)


if __name__=='__main__':
    main()
