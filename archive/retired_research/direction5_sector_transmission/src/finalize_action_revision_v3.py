"""Validate and register the second event-audit version; keep research gates closed."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd

from build_action_revision_v2 import read, save, sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/corporate_actions_reconciled_v2"


def main():
    parent = read("audits/data_revision_v2_registration.json")
    for record in parent["files"]:
        assert sha(record["path"]) == record["sha256"], record["path"]
    ledger = pd.read_parquet(OUT / "dividend_event_ledger_provisional.parquet")
    references = pd.read_parquet(OUT / "reference_window_reconciliation.parquet")
    repair = read("audits/action_revision_v2.json")
    reference_audit = read("audits/reference_window_reconciliation_v2.json")
    for symbol, wrong, correct in [("000042.SZ", "2018-06-28", "2018-06-22"), ("002727.SZ", "2019-04-02", "2019-04-03")]:
        assert not (ledger.symbol.eq(symbol) & ledger.ex_date.eq(wrong)).any()
        assert (ledger.symbol.eq(symbol) & ledger.ex_date.eq(correct)).sum() == 1
    def event(symbol, day):
        return ledger.loc[ledger.symbol.eq(symbol) & ledger.ex_date.eq(day)].iloc[0]
    assert abs(event("002601.SZ", "2018-10-25").cash_per_share - 0.6540279) < 1e-10
    assert abs(event("002601.SZ", "2018-10-25").quote_cash_per_share - 0.65) < 1e-10
    assert abs(event("600989.SH", "2021-05-20").cash_per_share - 0.32091) < 1e-10
    assert abs(event("600989.SH", "2021-05-20").quote_cash_per_share - 0.28) < 1e-10
    unresolved = ledger.loc[~ledger.event_fields_complete]
    assert len(unresolved) == 1 and unresolved.iloc[0].symbol == "002335.SZ"
    assert unresolved.iloc[0].cash_payment_date == pd.Timestamp("2018-05-15")
    assert event("000756.SZ", "2018-01-26").cash_per_share == 0.03
    resumed = references.loc[references.symbol.eq("000756.SZ") & references.reference_date.eq("2018-02-14")].iloc[0]
    assert resumed.dividend_events_in_interval == 1 and resumed.status == "generic_reference_matches_at_cent_precision"
    assert not ledger.approved_for_economic_labels.any()
    assert not ledger.duplicated(["symbol", "ex_date"]).any()
    assert len(references) == reference_audit["reference_candidates"] == 15913
    assert sum(reference_audit["status_counts"].values()) == len(references)
    assert ledger.ex_date.between(pd.Timestamp("2018-01-01"), pd.Timestamp("2024-12-31")).all()
    # Compile the remaining evidence queue from historical announcement metadata.
    queue = []
    for row in references.loc[references.status.eq("no_known_dividend_or_rights_event")].itertuples():
        directory = ROOT / f"sources/action_issuer_mirror_v2/{row.symbol}_{row.reference_date.date()}"
        candidates = []
        for path in sorted(directory.glob("query_*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))["data"]
            for item in data["list"]:
                if re.search(r"除权|转增.*股本|重整.*实施|特别.*分红|临时.*权益|权益分派.*实施", item["title"]):
                    candidates.append({"title": item["title"], "article_code": item["art_code"],
                                       "publication_date": item["notice_date"][:10],
                                       "metadata_source": str(path.relative_to(ROOT)), "source_sha256": sha(path.relative_to(ROOT))})
        queue.append({"symbol": row.symbol, "reference_date": str(row.reference_date.date()),
                      "previous_active_date": str(row.previous_active_date.date()),
                      "observed_preclose": row.observed_preclose,
                      "candidate_category": "capital_action_disclosure_located_details_pending" if candidates else "no_matched_action_disclosure_yet",
                      "candidates": candidates, "business_cause_verified": False,
                      "not_a_historical_pool_exclusion_rule": True})
    save(OUT / "remaining_unknown_reference_evidence_queue.json", queue)
    validation = {"parent_registered_file_hashes_unchanged": len(parent["files"]),
                  "misdated_duplicates_do_not_create_double_dividend_entitlements": True,
                  "public_cash_and_weighted_reference_cash_separate": True,
                  "suspension_interval_event_date_not_moved_to_resumption": True,
                  "unresolved_issuer_contradiction_preserved": True,
                  "full_reference_cross_section_count_preserved": True,
                  "all_economic_label_approval_flags_false": True,
                  "identity_audit_does_not_modify_frozen_industry_links": True}
    save(ROOT / "audits/action_revision_v3_validation.json", validation)
    previous = read("audits/stage8_data_audit_v2.json")
    current = {"stage": "6_to_8", "audit_revision": 3, "audit_execution_completed": True,
               "stage8_fully_passed": False, "previous_audit": "audits/stage8_data_audit_v2.json",
               "unit_and_quote_formula_checks_passed": previous["unit_and_quote_formula_checks_passed"],
               "current_corporate_action_staging": "datasets/corporate_actions_reconciled_v2",
               "event_repairs": repair, "reference_reconciliation": reference_audit,
               "outstanding": ["one_issuer_payment_date_contradiction_unresolved",
                               "remaining_unknown_reference_events_need_evidence",
                               "weighted_ex_reference_capital_base_for_812_formula_differences_not_fully_audited",
                               "rights_and_special_capital_actions_require_investor_entitlement_and_execution_accounting",
                               "full_historical_kline_universe_and_security_master_unverified",
                               "tax_lot_receivables_share_listing_and_transaction_cost_rules_not_implemented",
                               "industry_identity_links_and_transition_warmup_require_asof_validation"],
               "labels_ready": False, "factor_experiments_enabled": False, "model_experiments_enabled": False,
               "account_backtest_enabled": False, "original_registered_inputs_unchanged": True}
    save(ROOT / "audits/stage8_data_audit_v3.json", current)
    config = read("config.json")
    config["data_semantics_audit"] = "audits/stage8_data_audit_v3.json"
    config["corporate_action_staging"] = "datasets/corporate_actions_reconciled_v2"
    assert not config["execution_returns_ready"] and not config["model_experiments_enabled"]
    save(ROOT / "config.json", config)
    paths = set()
    for folder in ("datasets/corporate_actions_reconciled_v2", "sources/action_issuer_mirror_v2", "sources/action_evidence_v2", "sources/action_identity_evidence_v2"):
        paths.update(p for p in (ROOT / folder).rglob("*") if p.is_file())
    paths.update(ROOT / p for p in ["audits/action_revision_v2.json", "audits/reference_window_reconciliation_v2.json",
                                  "audits/action_revision_v3_validation.json", "audits/stage8_data_audit_v3.json",
                                  "src/collect_unresolved_evidence_v2.py", "src/collect_issuer_mirror_v2.py",
                                  "src/build_action_revision_v2.py", "src/audit_reference_revision_v2.py",
                                  "src/finalize_action_revision_v3.py"])
    for path in (ROOT / "src").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    registry = {"revision_id": "data_revision_v3", "cutoff": "2024-12-31",
                "parent_registration": "audits/data_revision_v2_registration.json",
                "parent_registration_sha256": sha("audits/data_revision_v2_registration.json"),
                "original_protocol_sha256": parent["original_protocol_sha256"],
                "scope": "issuer_evidence_input_repairs_and_reference_audit_only",
                "corporate_actions_approved_for_labels": False,
                "files": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p.relative_to(ROOT))} for p in sorted(paths)]}
    target = ROOT / "audits/data_revision_v3_registration.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != registry:
        raise RuntimeError("Existing v3 registration differs; preserve and create a new revision.")
    save(target, registry)
    print(json.dumps({"validation_passed": True, "registered_files": len(paths),
                      "unresolved_dividend_fields": len(unresolved), "unknown_reference_events": len(queue),
                      "candidate_disclosure_located": sum(bool(r["candidates"]) for r in queue),
                      "economic_labels_ready": False}))


if __name__ == "__main__":
    main()
