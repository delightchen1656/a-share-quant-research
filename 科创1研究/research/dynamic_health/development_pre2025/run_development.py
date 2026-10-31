from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn

from engine import BASE_RULES, SCHEMES, add_matured_event_outcomes, canonical_sha256, load_snapshot, metrics, score_candidates, sha256_file, simulate


EXPECTED_INPUT_MANIFEST = "16d0877a399588ff61ec548da6c5ab3c1d20cdc622bcf4786f8576a299a448bf"
PERIODS = {"build_2020_2022": ("2020-01-01", "2022-12-31"), "selection_2023": ("2023-01-01", "2023-12-31"), "confirmation_2024": ("2024-01-01", "2024-12-31")}
HISTORY_START = "2020-01-01"
DATA_START = "2019-07-22"


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "artifacts")
    args = ap.parse_args(); inputs = args.inputs.resolve(); out = args.output.resolve()
    manifest_hash = sha256_file(inputs / "MANIFEST.json")
    if manifest_hash != EXPECTED_INPUT_MANIFEST:
        raise SystemExit(f"input manifest mismatch: {manifest_hash}")
    out.mkdir(parents=True, exist_ok=False)
    raw, qfq = load_snapshot(inputs)
    if max(raw.date.max(), qfq.date.max()) > pd.Timestamp("2024-12-31"):
        raise SystemExit("boundary violation")
    scored, model_meta = score_candidates(qfq, inputs / "frozen_models")
    scored = add_matured_event_outcomes(scored, qfq, model_meta["event_horizon"], model_meta["event_target"])
    # Candidate structures are fixed in source before any selection-year or confirmation-year result is evaluated.
    def run_period(scheme, report_start: str, end: str):
        eq, tr, dec = simulate(raw, scored, model_meta["event_threshold"], scheme, HISTORY_START, end)
        eq = eq[pd.to_datetime(eq.date) >= pd.Timestamp(report_start)].reset_index(drop=True)
        tr = tr[pd.to_datetime(tr.exit_date) >= pd.Timestamp(report_start)].reset_index(drop=True) if len(tr) else tr
        dec = dec[pd.to_datetime(dec.date) >= pd.Timestamp(report_start)].reset_index(drop=True)
        return eq, tr, dec

    dev_metrics = {}; selection_metrics = {}
    for name, scheme in SCHEMES.items():
        eq, tr, dec = run_period(scheme, *PERIODS["build_2020_2022"])
        dev_metrics[name] = metrics(eq, tr)
        eq, tr, dec = run_period(scheme, *PERIODS["selection_2023"])
        selection_metrics[name] = metrics(eq, tr)
    def selection_score(name: str) -> tuple[float, int]:
        m = selection_metrics[name]
        if not m["trades"] or m["annualized_return"] is None: return (-1e99, -list(SCHEMES).index(name))
        return (float(m["annualized_return"]) + 0.5 * float(m["max_drawdown"]), -list(SCHEMES).index(name))
    selected = max(SCHEMES, key=selection_score)
    frozen_config = {"schema": 1, "candidate_name": selected, "selection_rule": "maximize 2023 annualized_return + 0.5 * max_drawdown; deterministic source-order tie break",
                     "event_threshold": model_meta["event_threshold"], "base_rules": BASE_RULES, "scheme": SCHEMES[selected],
                     "feature_contract": "engine.py:FEATURES", "data_start": DATA_START, "history_start": HISTORY_START, "input_manifest_sha256": manifest_hash,
                     "model_hashes": {"event_model.joblib": sha256_file(inputs / "frozen_models/event_model.joblib"), "stop_risk_model.joblib": sha256_file(inputs / "frozen_models/stop_risk_model.joblib")}}
    freeze_hash_before_confirmation = canonical_sha256(frozen_config)
    # The 2024 pass happens only after the candidate configuration has been frozen in memory.
    eq24, tr24, dec24 = run_period(SCHEMES[selected], *PERIODS["confirmation_2024"])
    confirmation = metrics(eq24, tr24)
    if canonical_sha256(frozen_config) != freeze_hash_before_confirmation:
        raise RuntimeError("candidate mutated after confirmation data became visible")
    yearly = {"build_2020_2022": dev_metrics, "selection_2023": selection_metrics,
              "confirmation_2024": {selected: confirmation},
              "confirmation_policy": "2024 remains development data. After it was first exposed, two methodological interface bugs were corrected: year-boundary health-state reset and omitted pre-history feature warmup in the independent adapter contract. Neither correction changed candidate structures or thresholds. No post-2024 data was accessed."}
    write_json(out / "development_metrics.json", yearly)
    eq24.to_csv(out / "confirmation_2024_equity.csv", index=False)
    dec24.to_csv(out / "confirmation_2024_decisions.csv", index=False)
    tr24.to_csv(out / "confirmation_2024_trades.csv", index=False)
    package = out / "frozen_candidate"; package.mkdir()
    shutil.copy2(Path(__file__).resolve().parent / "engine.py", package / "engine.py")
    shutil.copy2(Path(__file__).resolve().parent / "validate_frozen.py", package / "validate_frozen.py")
    shutil.copy2(inputs / "frozen_models/event_model.joblib", package / "event_model.joblib")
    shutil.copy2(inputs / "frozen_models/stop_risk_model.joblib", package / "stop_risk_model.joblib")
    write_json(package / "candidate.json", frozen_config)
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    except Exception as exc:
        freeze = f"pip-freeze-unavailable: {exc}\n"
    (package / "environment.lock.txt").write_text(freeze, encoding="utf-8")
    env = {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__,
           "sklearn_runtime": sklearn.__version__, "sklearn_model_source": "1.9.0", "model_load_warnings": model_meta["warnings"],
           "environment_lock_sha256": sha256_file(package / "environment.lock.txt")}
    write_json(package / "environment.json", env)
    files = {p.name: sha256_file(p) for p in sorted(package.iterdir()) if p.is_file()}
    package_manifest = {"schema": 1, "candidate_config_sha256": freeze_hash_before_confirmation, "files": files,
                        "source_run": {"input_manifest_sha256": manifest_hash, "metrics_sha256": sha256_file(out / "development_metrics.json")}}
    write_json(package / "PACKAGE_MANIFEST.json", package_manifest)
    package_hash = sha256_file(package / "PACKAGE_MANIFEST.json")
    write_json(out / "FREEZE_RECORD.json", {"candidate": selected, "candidate_config_sha256": freeze_hash_before_confirmation,
                                             "package_manifest_sha256": package_hash, "package": str(package),
                                             "source_hashes": {"engine.py": sha256_file(Path(__file__).resolve().parent / "engine.py"), "run_development.py": sha256_file(Path(__file__).resolve())},
                                             "input_manifest_sha256": manifest_hash, "environment_sha256": env["environment_lock_sha256"]})
    print(json.dumps({"candidate": selected, "package": str(package), "package_manifest_sha256": package_hash}, ensure_ascii=False))


if __name__ == "__main__":
    main()

