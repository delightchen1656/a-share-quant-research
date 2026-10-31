"""User authorizes resume and a one-way2025-2026audit, before new trial results."""
import datetime
import shutil
from settings import BASE,OUT,sha,dump

assert not (OUT/'ONE_WAY_AUDIT_POLICY.json').exists()
assert not list(OUT.glob('fold_scores_*.parquet')),'Register selection policy before completed trial folds'
if (OUT/'fit_registration.json').exists():
    shutil.copy2(OUT/'fit_registration.json',OUT/'fit_registration_before_user_pause.json')
policy=dict(
    user_authorization='Resume factor optimization first; then use a subagent for2025-2026blind audit; audit must not return to optimization.',
    resumed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    development_end='2023-12-31',unused_for_factor_selection='2024',
    final_selection='Among45registered variants, require strictly positive mean improvement vsbaseline in BOTH2022and2023 and positive pooled2021-2023improvement. Choose largest equal-year mean of2022and2023improvements, lexicographic ties; otherwise baseline12.',
    finite_trial_scope='Complete existing45feature variants without adding results-driven variants or changing hyperparameters. This round ends when candidate is frozen and one-way audit is delivered.',
    frozen_models='Train selected fixed feature set and original baseline once on all fully matured2018-2023ordinary labels. Freeze fitted model, medians, scaler, ordered feature list, code, pool, dates,top10policy, target/unknown handling and hashes before any audit data read. No2024+retraining.',
    audit_scope='2025-01-01through latest verified complete committed session in2026 at time of audit. Explicit2024history may be used for lagged feature warmup, never fitting/selection. Same Monday-open Tuesday-close signal metric.',
    audit_output='Restricted audit directory. Report all scheduled weeks, per-year/per-period signal means, coverage, original baseline comparison, executable quote flags, arithmetic signal curves. No portfolio annualization or fictional fills.',
    optimizer_firewall='Parent and factor optimizer do not read2025-2026quotes, labels, metrics, charts or suggestions. Audit subagent returns only completion/error status and report paths, with no performance numbers, ranking or tuning advice.',
    no_feedback='After audit, no changing factors, thresholds, stockpool, models, training or candidates in response. Poor/unsupported audit stays in report; no silent retries, replacement candidates or resetting audit.',
    audit_failures='Engineering/data integrity fixes must preserve original freeze and be logged; if unsupported, report failure instead of modifying strategy.',
    context='Fork auditor with fork_turns=none, pass no development performance. Check public boundary_version and do not claim OS-level isolation. Audit role may read authorized future data only after hashes verified.',
    known_limit='Prior index weekday search included later periods; audit is one-way optimizer-blind stock-factor audit, not proof of a historically untouched entire research process.')
dump(OUT/'ONE_WAY_AUDIT_POLICY.json',policy)
dump(OUT/'RESUMED_BY_USER.json',dict(status='resumed_by_explicit_user_workflow_instruction',
     utc=policy['resumed_utc'],previous_pause_record_retained=True,policy_sha256=sha(OUT/'ONE_WAY_AUDIT_POLICY.json')))
print('Resumed; final selection and one-way audit firewall registered before new outcomes.',flush=True)
