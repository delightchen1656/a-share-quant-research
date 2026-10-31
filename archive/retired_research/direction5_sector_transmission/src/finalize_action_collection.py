"""Register this input-only collection milestone without enabling outcome research."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def save(path, obj):
    (ROOT / path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    original = read("audits/protocol_v1_registration.json")
    assert sha("research_protocol_v1.json") == original["protocol_sha256"]
    assert sha("RESEARCH_SPEC_V1.md") == original["readable_spec_sha256"]
    for item in original["input_manifests"]:
        assert sha(item["path"]) == item["sha256"]
    actions = read("audits/corporate_action_reconciliation.json")
    windows = read("audits/reference_window_reconciliation.json")
    calendar = read("audits/trading_calendar_crosscheck.json")
    identity = read("audits/security_identity_sidecar.json")
    old = read("audits/stage8_data_audit.json")
    assert actions["all_planned_queries_successful"]
    assert actions["planned_symbol_years"] == actions["successful_symbol_year_queries"] == 3336 * 7
    assert calendar["calendar_and_kline_union_match"]
    calendar_file = "inputs_pre2025/trading_calendar_v1/calendar.parquet"
    assert sha(calendar_file) == calendar["sha256"]
    for record in read("inputs_pre2025/security_identity_v1/manifest.json")["files"]:
        assert sha("inputs_pre2025/security_identity_v1/" + record["file"]) == record["sha256"]
    assert [r["join_key"] for r in identity["boundary_checks"]] == [
        "601360.SH", "issuer_601313_601360", "issuer_601313_601360", "issuer_601313_601360"]
    folder = "datasets/corporate_actions_reconciled_v1/"
    ledger = pd.read_parquet(ROOT / folder / "dividend_event_ledger_provisional.parquet")
    detail = pd.read_parquet(ROOT / folder / "detail_rows_normalized.parquet")
    assert not ledger.duplicated(["symbol", "ex_date"]).any()
    assert len(detail) == actions["raw_detailed_event_rows"]
    assert not ledger.approved_for_economic_labels.any()
    assert ledger.ex_date.le(pd.Timestamp("2024-12-31")).all()
    checked_overrides = []
    for override in read("datasets/manual_action_overrides_v1/overrides.json"):
        assert override["approved_override"]
        assert sha(override["source_file"]) == override["source_sha256"]
        row = ledger.loc[ledger.symbol.eq(override["symbol"]) & ledger.ex_date.eq(override["ex_date"])].iloc[0]
        assert row.manual_issuer_override
        for key in ("cash_per_share", "bonus_per_share", "transfer_per_share"):
            assert abs(row[key] - override[key]) < 1e-10
        assert row.cash_payment_date == pd.Timestamp(override["cash_payment_date"])
        checked_overrides.append({"symbol": override["symbol"], "ex_date": override["ex_date"]})
    collapsed = ledger.loc[ledger.equivalent_detail_rows_collapsed_with_independent_single_event_confirmation.gt(0)]
    for row in collapsed.itertuples():
        subset = detail.loc[detail.symbol.eq(row.symbol) & detail.ex_date.eq(str(row.ex_date.date()))]
        keys = ["cash_per_share", "bonus_per_share", "transfer_per_share", "register_date", "cash_payment_date", "bonus_listing_date", "notice_date"]
        assert len(subset.drop_duplicates(keys)) == 1
        assert row.eastmoney_components == row.baostock_effective_components == 1
        assert row.provider_amounts_agree
    checks = {"original_protocol_and_manifest_hashes_unchanged": True,
              "all_symbol_year_queries_returned": True,
              "unique_symbol_ex_date_ledger_keys": True,
              "issuer_overrides_checked": checked_overrides,
              "equivalent_duplicate_groups_verified": len(collapsed),
              "equivalent_duplicate_rows_not_double_counted": actions["equivalent_detail_duplicate_rows_collapsed"],
              "calendar_hash_and_kline_date_union_verified": True,
              "identity_asof_boundary_checks_verified": True,
              "no_economic_labels_approved": True}
    save("audits/action_collection_validation.json", checks)
    outstanding = [
        "unresolved_dividend_event_fields_and_single_provider_amounts_need_further_evidence",
        "unexplained_reference_windows_and_weighted_ex_reference_capital_base_need_verification",
        "rights_subscription_and_non_dividend_reorganization_accounting_not_defined",
        "full_historical_security_master_and_kline_universe_not_verified",
        "tax_lot_receivables_share_listing_and_execution_accounting_not_implemented",
        "industry_transition_warmup_requires_registered_factor_windows"]
    current = {"stage": "6_to_8", "audit_revision": 2, "audit_execution_completed": True,
               "stage8_fully_passed": False,
               "unit_and_quote_formula_checks_passed": old["unit_and_quote_formula_checks_passed"],
               "previous_audit": "audits/stage8_data_audit.json",
               "dividend_collection_and_reconciliation": actions,
               "quote_reference_interval_reconciliation": windows,
               "rights_issue_events": read("audits/rights_issue_collection.json")["scope_rows"],
               "calendar_trading_days": calendar["trading_days"],
               "historical_identity_exception_sidecar_checked": True,
               "complete_historical_security_master": False,
               "corporate_action_data_location": "datasets/corporate_actions_reconciled_v1",
               "corporate_action_data_status": "staging_not_approved_white_list",
               "outstanding": outstanding, "labels_ready": False,
               "factor_experiments_enabled": False, "model_experiments_enabled": False,
               "account_backtest_enabled": False, "frozen_original_inputs_modified": False}
    save("audits/stage8_data_audit_v2.json", current)
    config = read("config.json")
    config["data_semantics_audit"] = "audits/stage8_data_audit_v2.json"
    config["security_identity_snapshot"] = "inputs_pre2025/security_identity_v1"
    config["trading_calendar_snapshot"] = "inputs_pre2025/trading_calendar_v1"
    config["corporate_action_staging"] = "datasets/corporate_actions_reconciled_v1"
    config["execution_returns_ready"] = False
    config["model_experiments_enabled"] = False
    save("config.json", config)
    files = ["audits/protocol_v1_registration.json", "inputs_pre2025/security_identity_v1/manifest.json",
             "inputs_pre2025/trading_calendar_v1/manifest.json", calendar_file,
             "datasets/corporate_actions_eastmoney_v1/manifest.json",
             "datasets/corporate_actions_baostock_v1/collection_summary.json",
             "datasets/manual_action_overrides_v1/overrides.json",
             "datasets/rights_issues_eastmoney_v1/manifest.json",
             "datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet",
             "audits/action_collection_validation.json", "audits/stage8_data_audit_v2.json",
             "audits/reference_window_reconciliation.json"]
    files.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / folder).glob("*")) if p.is_file())
    files.extend(str(p.relative_to(ROOT)).replace("\\", "/") for p in sorted((ROOT / "src").glob("*.py")))
    registration = {"revision_id": "data_revision_v2", "cutoff": "2024-12-31",
                    "original_protocol_sha256": original["protocol_sha256"],
                    "original_input_manifests": original["input_manifests"],
                    "scope": "supplemental_input_metadata_and_staging_event_audit_only",
                    "corporate_actions_approved_for_labels": False,
                    "files": [{"path": p, "sha256": sha(p)} for p in files]}
    target = ROOT / "audits/data_revision_v2_registration.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != registration:
        raise RuntimeError("Existing supplemental registration differs; preserve it and register a new revision.")
    save("audits/data_revision_v2_registration.json", registration)
    print(json.dumps({"validation_passed": True, "registered_files": len(files),
                      "complete_event_fields": int(ledger.event_fields_complete.sum()),
                      "unresolved_event_groups": int((~ledger.event_fields_complete).sum()),
                      "labels_ready": False}))


if __name__ == "__main__":
    main()
