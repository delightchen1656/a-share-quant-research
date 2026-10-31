"""Validate schedule-only diagnostics and register the next closed-gate milestone."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def save(path, value):
    (ROOT / path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    previous = read("audits/data_revision_v4_registration.json")
    for record in previous["files"]:
        assert sha(record["path"]) == record["sha256"], record["path"]
    registration = read("audits/label_definition_v1_registration.json")
    assert sha("label_definition_v1.json") == registration["label_definition_sha256"]
    for record in registration["input_manifests"]:
        assert sha(record["path"]) == record["sha256"]
    root = "inputs_pre2025/label_schedule_dev_v1"
    report = read(root + "/manifest.json")
    assert report["schedule_and_guard_audit_passed"] and not report["label_values_computed"]
    assert sha("src/audit_label_schedule_v1.py") == report["code_sha256"]
    yearly, in_window_gaps, observed, rules, plain, purges = [], {2: 0, 8: 0, 32: 0}, 0, 0, 0, {}
    for record in report["files"]:
        path = root + "/" + record["file"]
        assert sha(path) == record["sha256"]
        if not record["file"][:4].isdigit(): continue
        frame = pd.read_parquet(ROOT / path)
        assert not any("return" in c or c in ("entry_open", "exit_open", "target") for c in frame.columns)
        assert not frame.training_label_approved.any()
        selected = frame.loc[frame.signal_rules_pass]
        observed += len(frame); rules += len(selected); plain += int(selected.plain_case_data_candidate.sum())
        inside = selected.loc[selected.scheduled_exit_in_development]
        for bit in in_window_gaps:
            in_window_gaps[bit] += int(((inside.input_audit_bits & bit) != 0).sum())
        if int(record["file"][:4]) in (2020, 2021, 2022):
            cutoff = pd.Timestamp(record["file"][:4] + "-12-31")
            late = selected.loc[selected.scheduled_exit_date.gt(cutoff)]
            assert late.signal_date.nunique() == 6
            purges[str(cutoff.date())] = len(late)
        yearly.append({"year": int(record["file"][:4]), "observed_rows": len(frame), "signal_rule_rows": len(selected),
                       "plain_case_data_candidates": int(selected.plain_case_data_candidate.sum())})
    assert observed == report["observed_signal_rows"] == 4382527
    assert rules == report["signal_rule_rows"] == 3737172
    assert plain == report["plain_case_data_candidates"]
    for fold in report["nominal_training_maturity_purge"]:
        assert purges[fold["training_cutoff"]] == fold["scheduled_exit_after_cutoff"]
    rules_sources = read("sources/label_rules_v1/manifest.json")
    for source in rules_sources:
        if "file" in source:
            assert sha(source["file"]) == source["sha256"]
    checks = {"observed_rows_preserved": observed, "signal_qualification_rows_preserved": rules,
              "plain_candidates_not_training_labels": plain,
              "no_target_values_or_prices_in_schedule_output": True,
              "six_signal_dates_purged_at_each_registered_training_cutoff": True,
              "nominal_maturity_not_promoted_to_actual_verified_maturity": True,
              "in_development_window_gap_flags_on_qualified_signals": in_window_gaps,
              "out_of_development_window_rows_must_not_be_counted_as_supplier_missing_rows": True,
              "parent_registered_files_unchanged": len(previous["files"]),
              "yearly": yearly}
    save("audits/label_schedule_dev_v1_validation.json", checks)
    gates = read("research_stage_gates_v1.json")
    gates["purpose"] = "Label definition and schedule-only missingness audit completed; execution and actual label admission still pending."
    gates["current_stage"] = "10_label_definition_and_11_schedule_availability_audit_complete_return_values_pending"
    gates["gates"]["label_specification_ready"] = True
    gates["gates"]["label_schedule_and_guard_audit_passed"] = True
    gates["gates"]["economic_label_values_materialized"] = False
    gates["gates"]["label_admission_audit_passed"] = False
    gates["gates"]["minimum_execution_audit_passed"] = False
    gates["next_concrete_work"] = ["implement_and_validate_minimum_execution_and_unit_accounting_cases",
                                   "materialize_only_audited_supported_label_values_and_verify_maturity_and_missingness",
                                   "audit_training_window_label_distribution_before_factor_selection"]
    save("research_stage_gates_v2.json", gates)
    config = read("config.json")
    config.update({"label_definition": "label_definition_v1.json",
                   "label_definition_registration": "audits/label_definition_v1_registration.json",
                   "label_schedule_development_snapshot": root,
                   "label_schedule_audit": "audits/label_schedule_dev_v1.json",
                   "label_specification_ready": True, "label_values_computed": False,
                   "label_admission_audit_passed": False,
                   "research_stage_gates": "research_stage_gates_v2.json"})
    assert not config["model_experiments_enabled"] and not config["execution_returns_ready"]
    save("config.json", config)
    paths = set()
    for folder in (root, "sources/label_rules_v1"):
        paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file())
    paths.update(ROOT / p for p in ["label_definition_v1.json", "research_stage_gates_v2.json",
                                  "audits/label_definition_v1_registration.json", "audits/label_schedule_dev_v1.json",
                                  "audits/label_schedule_dev_v1_validation.json", "src/register_label_definition_v1.py",
                                  "src/audit_label_schedule_v1.py", "src/register_label_availability_milestone_v1.py"])
    for path in (ROOT / "src").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    registry = {"revision_id": "data_revision_v5", "parent_registration": "audits/data_revision_v4_registration.json",
                "parent_registration_sha256": sha("audits/data_revision_v4_registration.json"),
                "label_definition_registration_sha256": sha("audits/label_definition_v1_registration.json"),
                "original_protocol_sha256": sha("research_protocol_v1.json"),
                "scope": "registered_label_semantics_and_development_schedule_quality_flags_only",
                "label_values_materialized": False, "factor_experiments_enabled": False,
                "files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p.relative_to(ROOT))} for p in sorted(paths)]}
    target = ROOT / "audits/data_revision_v5_registration.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != registry:
        raise RuntimeError("Existing label schedule registration differs; preserve and register a new version.")
    save("audits/data_revision_v5_registration.json", registry)
    print(json.dumps({"schedule_audit_passed": True, "definition_registered": True,
                      "plain_case_data_candidates": plain, "retained_but_not_plain_candidates": rules - plain,
                      "registered_files": len(paths), "label_values_computed": False,
                      "factor_selection_enabled": False}))


if __name__ == "__main__":
    main()
