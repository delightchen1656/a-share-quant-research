"""Validate and register research design without computing factors or outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    path = ROOT / "research_protocol_v1.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    cutoff = pd.Timestamp(spec["cutoff"])
    assert cutoff <= pd.Timestamp("2024-12-31")
    folds = spec["validation"]["development_folds"]
    holdout = spec["validation"]["final_holdout"]
    schedule = []
    previous_validation_end = None
    for fold in folds:
        train_start, train_end, start, end = [pd.Timestamp(fold[key]) for key in
                                            ("train_start", "train_end", "validation_start", "validation_end")]
        assert train_start <= train_end < start <= end < pd.Timestamp(holdout["start"]) <= cutoff
        if previous_validation_end is not None:
            assert previous_validation_end < start
        previous_validation_end = end
        schedule.append({**fold, "training_label_maturity_required": True,
                         "returns_or_factors_computed": False})
    assert pd.Timestamp(holdout["start"]) <= pd.Timestamp(holdout["end"]) <= cutoff
    assert spec["timing"]["holding_market_session_intervals"] >= 1
    assert spec["portfolio_prototype"]["maximum_positions"] * spec["portfolio_prototype"]["target_weight_per_position"] <= 1.0
    for key in ("factor_experiments_enabled", "model_experiments_enabled", "account_backtest_enabled"):
        assert spec["gates"][key] is False
    assert spec["scope"]["no_exclusion_based_on_future_delisting"]
    assert spec["industry_policy"]["no_current_membership_backfill"]
    assert spec["validation"]["split_unit"] == "entire_signal_date_cross_section"
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    inputs = [ROOT / config["snapshot"] / "manifest.json", ROOT / config["industry_snapshot"] / "manifest.json"]
    report = {
        "protocol_id": spec["protocol_id"], "protocol_sha256": digest(path),
        "readable_spec_sha256": digest(ROOT / "RESEARCH_SPEC_V1.md"),
        "input_manifests": [{"path": str(p.relative_to(ROOT)), "sha256": digest(p)} for p in inputs],
        "schema_and_time_order_checks_passed": True,
        "settings_origin": spec["settings_origin"],
        "development_schedule": schedule, "final_holdout": holdout,
        "registration_scope": "design only; no targets, factors, model scores, or strategy returns computed",
        "unresolved_gates": [key for key, value in spec["gates"].items() if value is False],
        "change_policy": spec["versioning"]
    }
    output = ROOT / "audits/protocol_v1_registration.json"
    if output.exists():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous != report:
            raise RuntimeError("Existing registration differs. Preserve v1 and create a new protocol version.")
        print(json.dumps({"registration_verified": True, "protocol_sha256": report["protocol_sha256"]}))
        return
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"registered": True, "protocol_sha256": report["protocol_sha256"],
                      "development_folds": len(schedule), "model_training_started": False}))


if __name__ == "__main__":
    main()
