import datetime
from settings import BASE,OLD,PRIOR,OUT,INPUTS,CORE,NEW,BLOCKS,variants,sha,dump,install_read_boundary

install_read_boundary()
OUT.mkdir(parents=True,exist_ok=True)
assert OUT.resolve()!=PRIOR.resolve() and OUT.resolve()!=OLD.resolve()
assert not (OUT/'registration.json').exists()
spec=dict(
    authorization='User continues Monday factor optimization; posterior results must never feed back into optimization.',
    boundary='Pre2024data only, initial training2018-2020, annual forward development2021-2023.2019/2020inner diagnostic years as prior round. No2024+quote, label, metric, image or posterior report read.',
    prior_information='Use only the previous45pre2024development factor trials. Prior posterior reports/images were displayed by file path without optimizer reading contents. No audit feedback used for this design.',
    hypothesis='Refine prior11factor anchor by combining previously promising pre2024factor blocks, prune its remaining factors, and test six fixed path/persistence/intraday features.',
    anchor=CORE,new_features=NEW,combination_blocks=BLOCKS,variants=variants(),trial_budget=36,
    cumulative_trial_context='45prior feature variants plus36this round;2this-round anchors repeat earlier feature sets. Reused development years and cumulative selection bias are acknowledged.',
    fixed_HGB=dict(max_iter=100,max_leaf_nodes=15,min_samples_leaf=200,learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=26027),
    frozen_controls='Original pool, previous-actual-close feature information, MondayOpen-TuesdayClose, top10stock count, original ordinary gross/excess labels, equal date weighting and train-only medians/scaler unchanged.',
    folds=[2019,2020,2021,2022,2023],
    feature_source='settings.new_features registered;6single new factors, all6group, longmomentum+new6;15nonempty pre-existing block combinations;11leave-one-out anchor prunes;2benchmarks.',
    objective='Mean of weekly top10known ordinary quote-label gross returns, with original selected denominator retained. Primary paired improvement vs11factor anchor, also compare original12.',
    uncertainty='2000circular5week block bootstrap paired deltas; approximate maxT simultaneous intervals over34new trials. Within-round correction does not remove prior cumulative selection bias.',
    upgrade_gate='Require pooled improvement>0, strictly positive improvement in EACH of2021/2022/2023, simultaneous95%lower bound>0, and label coverage no more than0.005below11factor anchor. Otherwise retain anchor and label higher sample means exploratory only.',
    best_exploratory='Highest pooled development mean among34new variants, lexicographic ties; report even if upgrade gate fails, never imply independent validation.',
    causal_selector='Before each2021-2023year, among34new variants require positive paired mean vsanchor in BOTH preceding2years; choose highest equal-year improvement, lexicographic ties; otherwise anchor11. No current-year outcomes in selection.',
    reporting='All36results, yearly mean/delta, unknown counts, joint-complete10label-week sensitivity, untradeable quote flags without deleting signals, best1/best5week exclusion sensitivity and arithmetic signal curves, no portfolio annualization.',
    no_feedback='Do not access any restricted_audit_2025_2026 or posterior_review directory. Read audit hook plus parquet whitelist enabled. Do not run a new post-period audit in this round.',
    stopping='Exactly36feature variants, no additional result-driven tuning or extra combined candidate after inspection; record failures and original hashes.')
dump(OUT/'spec.json',spec)
paths=[OLD/'weekly_factor_panel.parquet',PRIOR/'new_factor_panel.parquet',INPUTS/'kline_dev_v1/manifest.json']
paths+=list((BASE/'src_factor_v5').glob('*.py'))
dump(OUT/'registration.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    before_new_variant_outcomes=True,spec_sha256=sha(OUT/'spec.json'),
    files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in paths]))
print('Registered36development-only factor variants; posterior reads denied.',flush=True)
