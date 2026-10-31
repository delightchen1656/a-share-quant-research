"""Freeze signal-return diagnostics without making capital-allocation assumptions."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'audits/holdout_restricted/signal_average_v3'
OUT.mkdir(parents=True,exist_ok=True)
assert not (OUT/'registration.json').exists()
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
spec=dict(
    authorization='User prioritizes lifting the average signal return curve; postpone Friday/Monday capital allocation and overlapping position rules.',
    endpoints=['previous Friday open -> following Tuesday close','Monday open -> Tuesday close'],
    information='Last actual market close strictly before each entry; no same-day close in ranking.',
    data='Existing independent pre2024 stock snapshots only. Train2018-2020, expanding annual forward development validation2021-2023. Posterior-informed, not untouched final validation.',
    methods='Exactly the ten previously registered methods, same12factors and fixed model hyperparameters. Monday saved scores reused unchanged; Friday models retrained on Friday-specific matured targets.',
    screening='Top10 per method and entry date; deterministic rank ties. No score threshold, stock-count, sign, weekday or hyperparameter search.',
    primary_metric='Ordinary quote-horizon gross returns among known scheduled labels, first equal-weight stocks within signal date, then equal-weight signal dates. Compare each date to full eligible pool and same-time index; report annual means and coverage.',
    curve='Arithmetic cumulative sum of per-date mean gross returns and mean excess vs eligible pool. These are signal diagnostics, not compound NAV or portfolio annualized returns.',
    unknowns='Corporate-reference changes or missing required quotes retain unknown labels; keep original selected denominator and unknown counts, never fill0 or use label flags in ranking. Quote-only conditional means may suffer label-availability bias.',
    execution='Report observable failed-open constraints separately; do not silently remove limit-up signals. No fills, cash allocation, fees, liquidity capacity or forced exits asserted in this stage.',
    dual_entries='Friday/Monday signal curves analyzed separately to avoid an assumed capital policy; this does not register two separate-account strategies.',
    boundaries='No2024+stock prices, deployment, new hyperparameters or further optimization after these comparisons.')
(OUT/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
bound=[BASE/'src_friday'/n for n in ['common.py','fit_methods.py','build_panel.py']]
bound += [BASE/'audits/holdout_restricted/friday_open_v2'/n for n in ['weekly_factor_panel.parquet','weekly_schedule.parquet']]
bound += [BASE/'audits/holdout_restricted/research_v1/selection_scores_top30.parquet']
reg=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_Friday_model_scores_and_signal_comparison=True,
    spec_sha256=digest(OUT/'spec.json'),files=[dict(path=str(p.relative_to(BASE)),sha256=digest(p)) for p in bound])
(OUT/'registration.json').write_text(json.dumps(reg,ensure_ascii=False,indent=2),encoding='utf-8')
print('Signal-diagnostic scope registered; no capital policy presumed.')
