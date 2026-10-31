"""Freeze finite ablations/additions before observing their results."""
import datetime
from settings import BASE,OLD,OUT,INPUTS,BASE_FACTORS,GROUPS,NEW_FACTORS,variants,sha,dump

OUT.mkdir(parents=True,exist_ok=True)
assert not (OUT/'registration.json').exists(),'Do not replace a registered experiment'
assert OUT.resolve()!=OLD.resolve() and 'holdout_restricted' in OUT.parts
spec=dict(
    authorization='Continue Monday gradient-boosting factor research to improve average signal returns; signal diagnostics only, no capital allocation or production deployment.',
    frozen_timing='Monday open to Tuesday close; factors at last actual market close before Monday. Endpoint closures skip week.',
    data='Only local independent2018-2023white-listed raw stock/index/calendar snapshots. No2024+prices or old strategy/industry files.',
    known_context='Monday baseline results2021-2023and weekday search already observed. This is posterior-informed development, not untouched holdout.',
    base_factors=BASE_FACTORS,new_factor_groups=GROUPS,
    feature_definitions='settings.new_features source is registered. All new features are trailing price/volume/turnover or trailing relationship with same-past SSE returns; missing values not fabricated.',
    models=variants(),trial_budget=45,
    fixed_HGB=dict(max_iter=100,max_leaf_nodes=15,min_samples_leaf=200,learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=26027),
    preprocessing='Cross-sectional signal-date percentile ranks of original eligible pool. Train-only weighted medians and scaler, per-date equal total sample weight as before.',
    labels='Original ordinary quote-excess proxy, unchanged. Unknown reference-change/missing labels not0, never used to exclude stock pool before scoring.',
    folds=[2019,2020,2021,2022,2023],fit='Annual expanding train on fully matured labels strictly before fold year.2019/2020are inner diagnostic years,2021-2023reported development years.',
    primary='Each week select top10, equal-weight known ordinary gross stock labels, then equal-weight weeks; compare paired weekly means with baseline12.',
    nested_selector='For each2021-2023year choose only from variants beating baseline in BOTH preceding2years; maximize mean of those2annual improvements, lexicographic ties. If none qualify choose baseline12. This is a causal adaptive development path, not independent validation.',
    reporting='Keep all45results, per-year deltas, coverage, complete-label-window sensitivity, same-window paired deltas, common-label-stock intersection sensitivity, positive weekly fraction, block-bootstrap intervals and multiplicity caution.',
    safeguards='No hyperparameter/seed/stockcount/threshold search; no results-driven combined feature variant after inspection. No raw signal annualization. Failed entry/exit quote flags reported without deleting signals.',
    interpretation='Adding/removing a correlated factor changes tree interactions, not a proof of causal factor value. quote_reversal1 and last_quote_change are exact opposite forms; also test removing their pair.',
    importance='Direct leave-one-factor-out and add-one-factor experiments, group tests; no impurity importance substituted for signal-return improvements.')
dump(OUT/'spec.json',spec)
files=[OLD/'weekly_factor_panel.parquet',OLD/'selection_scores_top30.parquet',OLD/'weekly_schedule.parquet',INPUTS/'kline_dev_v1/manifest.json',INPUTS/'sse_dev_v1.parquet']
files+=list((BASE/'src_factor_v4').glob('*.py'))
dump(OUT/'registration.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_factor_variants_results=True,
     spec_sha256=sha(OUT/'spec.json'),files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in files]))
print('Registered45fixed factor variants, annual folds2019-2023; no future-year tuning.',flush=True)
