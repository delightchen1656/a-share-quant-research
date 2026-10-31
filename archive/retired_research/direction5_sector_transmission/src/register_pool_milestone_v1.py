"""Register causal entry-rule flags and a bounded additional issuer event."""
from __future__ import annotations

import ast
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def save(path, data):
    (ROOT / path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    previous = read("audits/data_revision_v3_registration.json")
    for record in previous["files"]:
        assert sha(record["path"]) == record["sha256"], record["path"]
    snapshot = "inputs_pre2025/eligibility_observed_dev_v1"
    panel = read(snapshot + "/manifest.json")
    assert panel["end"] == "2023-12-31" and panel["rules_panel_ready"]
    for record in panel["files"]:
        assert sha(snapshot + "/" + record["file"]) == record["sha256"]
    assert sha("src/build_observed_eligibility_v1.py") == panel["code_sha256"]
    source = read("sources/action_evidence_v3/manifest.json")
    assert sha(source["source_file"]) == source["sha256"]
    source.update({"pdf_page_visually_reviewed": 1, "event_fields_verified": True,
                   "cash_currency": "CNY", "amount_not_HKD_announcement_value": True})
    evidence = {**source, "cash_per_share_cny": 1.00699, "register_date": "2022-07-14",
                "ex_date": "2022-07-15", "cash_payment_date": "2022-07-15",
                "bonus_per_share": 0.0, "transfer_per_share": 0.0, "economic_labels_approved": False}
    output = ROOT / "datasets/corporate_actions_reconciled_v3"
    output.mkdir(exist_ok=True)
    ledger = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v2/dividend_event_ledger_provisional.parquet")
    mask = ledger.symbol.eq("600938.SH") & ledger.ex_date.eq("2022-07-15")
    assert not mask.any()
    row = {column: None for column in ledger.columns}
    row.update({"symbol": "600938.SH", "ex_date": pd.Timestamp("2022-07-15"), "register_date": pd.Timestamp("2022-07-14"),
                "cash_payment_date": pd.Timestamp("2022-07-15"), "bonus_listing_date": pd.NaT,
                "cash_per_share": 1.00699, "bonus_per_share": 0.0, "transfer_per_share": 0.0,
                "eastmoney_components": 0, "baostock_components": 0, "baostock_effective_components": 0,
                "equivalent_detail_rows_collapsed_with_independent_single_event_confirmation": 0,
                "manual_issuer_override": True, "quote_reference_special": False, "provider_amounts_agree": False,
                "issues": "[]", "event_fields_complete": True, "approved_for_economic_labels": False,
                "v2_reviewed_fields": True, "v2_source_evidence": json.dumps([evidence], ensure_ascii=False),
                "quote_cash_per_share": float("nan"), "quote_cash_evidence_verified": False,
                "identity_mapping_is_retrospective_audit_only": False})
    ledger = pd.concat([ledger, pd.DataFrame([row])], ignore_index=True).sort_values(["symbol", "ex_date"])
    assert not ledger.duplicated(["symbol", "ex_date"]).any()
    ledger.to_parquet(output / "dividend_event_ledger_provisional.parquet", index=False)
    references = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v2/reference_window_reconciliation.parquet")
    mask = references.symbol.eq("600938.SH") & references.reference_date.eq("2022-07-15")
    assert mask.sum() == 1 and references.loc[mask, "status"].iloc[0] == "no_known_dividend_or_rights_event"
    previous_close = float(references.loc[mask, "previous_active_close"].iloc[0])
    expected = float((Decimal(str(previous_close)) - Decimal("1.00699")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    assert abs(expected - references.loc[mask, "observed_preclose"].iloc[0]) < 1e-10
    references.loc[mask, "dividend_events_in_interval"] = 1
    references.loc[mask, "generic_reference_expected"] = expected
    references.loc[mask, "generic_reference_difference"] = 0.0
    references.loc[mask, "status"] = "generic_reference_matches_at_cent_precision"
    references.to_parquet(output / "reference_window_reconciliation.parquet", index=False)
    ledger.loc[~ledger.event_fields_complete].to_parquet(output / "unresolved_event_fields.parquet", index=False)
    unknown = read("datasets/corporate_actions_reconciled_v2/remaining_unknown_reference_evidence_queue.json")
    unknown = [r for r in unknown if not (r["symbol"] == "600938.SH" and r["reference_date"] == "2022-07-15")]
    save("datasets/corporate_actions_reconciled_v3/remaining_unknown_reference_evidence_queue.json", unknown)
    save("datasets/corporate_actions_reconciled_v3/additional_verified_event.json", evidence)
    corporate = {"parent": "datasets/corporate_actions_reconciled_v2", "additional_issuer_cash_events": 1,
                 "event_groups": len(ledger), "unresolved_event_fields": int((~ledger.event_fields_complete).sum()),
                 "remaining_unknown_reference_events": len(unknown), "unresolved_formula_differences": 812,
                 "reference_status_counts": references.status.value_counts().to_dict(),
                 "rights_and_other_special_reviews_inherited_from_parent": True, "economic_labels_ready": False}
    save("audits/action_followup_v3.json", corporate)
    save("datasets/corporate_actions_reconciled_v3/manifest.json", corporate)
    prior = read("audits/stage8_data_audit_v3.json")
    current = {**prior, "audit_revision": 4, "previous_audit": "audits/stage8_data_audit_v3.json",
               "current_corporate_action_staging": "datasets/corporate_actions_reconciled_v3",
               "current_action_followup": corporate,
               "current_qualification_rules_snapshot": snapshot,
               "qualification_rules_panel_ready": True, "complete_daily_tradable_universe_ready": False,
               "stage_gate_clarification": "research_stage_gates_v1.json",
               "note": "Event repairs and reference reconciliation inherited above describe prior-version audits; current_action_followup supplies the incremental current counts. All return/model gates remain closed."}
    save("audits/stage8_data_audit_v4.json", current)
    config = read("config.json")
    config["data_semantics_audit"] = "audits/stage8_data_audit_v4.json"
    config["corporate_action_staging"] = "datasets/corporate_actions_reconciled_v3"
    config["research_stage_gates"] = "research_stage_gates_v1.json"
    assert not config["model_experiments_enabled"] and not config["execution_returns_ready"]
    save("config.json", config)
    paths = set()
    for folder in (snapshot, "datasets/corporate_actions_reconciled_v3", "sources/action_evidence_v3"):
        paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file())
    paths.update(ROOT / p for p in ["src/build_observed_eligibility_v1.py", "src/register_pool_milestone_v1.py",
                                  "research_stage_gates_v1.json", "audits/eligibility_observed_dev_v1.json",
                                  "audits/eligibility_observed_dev_v1_checks.json", "audits/action_followup_v3.json",
                                  "audits/stage8_data_audit_v4.json"])
    for path in (ROOT / "src").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    registry = {"revision_id": "data_revision_v4", "parent": "audits/data_revision_v3_registration.json",
                "parent_sha256": sha("audits/data_revision_v3_registration.json"),
                "scope": "development_observed_entry_rule_flags_and_additional_input_evidence",
                "original_protocol_sha256": sha("research_protocol_v1.json"),
                "factor_selection_enabled": False, "full_historical_universe_claimed": False,
                "files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p.relative_to(ROOT))} for p in sorted(paths)]}
    target = ROOT / "audits/data_revision_v4_registration.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != registry:
        raise RuntimeError("Existing revision differs; preserve and register a new version.")
    save("audits/data_revision_v4_registration.json", registry)
    print(json.dumps({"pool_rules_panel_ready": True, "observed_rows": panel["observed_rows"],
                      "candidate_rows": panel["candidate_rows"], "unknown_events_remaining": len(unknown),
                      "prior_registered_files_unchanged": len(previous["files"]), "new_registered_files": len(paths),
                      "factor_selection_ready": False}))


if __name__ == "__main__":
    main()
