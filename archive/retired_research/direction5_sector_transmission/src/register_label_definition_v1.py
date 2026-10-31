"""Freeze label semantics before inspecting any label values or availability counts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    spec = json.loads((ROOT / "label_definition_v1.json").read_text(encoding="utf-8"))
    original = json.loads((ROOT / "audits/protocol_v1_registration.json").read_text(encoding="utf-8"))
    assert sha(ROOT / "research_protocol_v1.json") == original["protocol_sha256"]
    assert spec["development_end"] == "2023-12-31"
    assert not spec["current_audit_scope"]["write_label_values"]
    assert spec["primary_prediction_label"]["holding_market_session_intervals"] == 5
    assert not spec["gates"]["economic_label_materialization_enabled"]
    inputs = ["inputs_pre2025/kline_v1/manifest.json", "inputs_pre2025/eligibility_observed_dev_v1/manifest.json",
              "inputs_pre2025/trading_calendar_v1/manifest.json", "audits/data_revision_v4_registration.json"]
    report = {"label_definition_sha256": sha(ROOT / "label_definition_v1.json"),
              "parent_protocol_sha256": original["protocol_sha256"],
              "input_manifests": [{"path": p, "sha256": sha(ROOT / p)} for p in inputs],
              "registered_before_availability_audit": True, "label_values_computed": False,
              "primary_acceptance_and_validation_split_unchanged": True}
    target = ROOT / "audits/label_definition_v1_registration.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != report:
        raise RuntimeError("Existing label definition differs; preserve it and register a new version.")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
