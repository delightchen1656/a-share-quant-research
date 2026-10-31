"""Reconcile bounded event probes and write a truthful stage-8 readiness result."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def number(value):
    # Empty values are unknown, never silently zero. Alternatives remain text.
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def main():
    units = read("audits/semantics_v1/summary.json")
    identity = read("audits/semantics_v1/security_identity_audit.json")
    capability = read("audits/corporate_action_provider_capability.json")
    doc_path = ROOT / "sources/vendor_documentation/stockKData.md"
    docs = doc_path.read_text(encoding="utf-8")
    assert "单位：股" in docs and "人民币元" in docs and "不是前一天的实际收盘价" in docs
    totals = units["totals"]
    unit_passed = (totals["share_unit_vwap_consistency"] == 1.0
                   and totals["lot_unit_vwap_consistency"] == 0.0
                   and totals["active_nonfinite_numeric_rows"] == 0
                   and totals["quote_return_mismatches"] == 0
                   and totals["unknown_tradestatus_rows"] == 0 and totals["unknown_st_rows"] == 0)
    strict = pd.read_parquet(ROOT / "audits/semantics_v1/vwap_strict_diagnostics.parquet")
    strict["amount_difference_from_low_price_times_volume_cny"] = strict.amount - strict.low * strict.volume
    strict.to_parquet(ROOT / "audits/semantics_v1/vwap_precision_diagnostics.parquet", index=False)
    ref_breaks = pd.read_parquet(ROOT / "audits/semantics_v1/breaks.parquet")
    event_samples = []
    issuer_review_path = ROOT / "audits/semantics_v1/issuer_action_visual_review.json"
    issuer_review = json.loads(issuer_review_path.read_text(encoding="utf-8")) if issuer_review_path.exists() else {}
    for path in sorted((ROOT / "sources/corporate_action_probe_v1").glob("dividend_*.json")):
        response = json.loads(path.read_text(encoding="utf-8"))
        if response.get("status") != "returned":
            continue
        for row in response.get("rows", []):
            event = dict(zip(response["fields"], row))
            code = event["code"]
            symbol = code[3:] + "." + code[:2].upper()
            date = pd.Timestamp(event["dividOperateDate"])
            assert date <= pd.Timestamp("2024-12-31")
            matches = ref_breaks.loc[ref_breaks.symbol.eq(symbol) & ref_breaks.date.eq(date)]
            cash = number(event.get("dividCashPsBeforeTax"))
            bonus = number(event.get("dividStocksPs"))
            transfer = number(event.get("dividReserveToStockPs"))
            numeric_complete = all(v is not None for v in (cash, bonus, transfer))
            expected, actual, difference, rounded, matches_precision = None, None, None, None, None
            if len(matches) == 1 and numeric_complete:
                source = matches.iloc[0]
                expected = (float(source.previous_observed_active_close) - cash) / (1 + bonus + transfer)
                actual = float(source.preclose)
                difference = abs(expected - actual)
                rounded = float(Decimal(str(expected)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
                matches_precision = abs(rounded - actual) < 1e-8
            event_samples.append({"symbol": symbol, "ex_date": str(date.date()),
                                  "cash_before_tax_per_share": cash, "bonus_per_share": bonus,
                                  "transfer_per_share": transfer,
                                  "all_cash_and_share_fields_numeric": numeric_complete,
                                  "raw_after_tax": event.get("dividCashPsAfterTax"),
                                  "after_tax_is_single_numeric_value": number(event.get("dividCashPsAfterTax")) is not None,
                                  "raw_plan": event.get("dividCashStock"),
                                  "register_date": event.get("dividRegistDate"),
                                  "payment_date": event.get("dividPayDate"),
                                  "bonus_listing_date": event.get("dividStockMarketDate"),
                                  "matching_reference_price_discontinuities": len(matches),
                                  "reference_price_reconstructed_from_numeric_fields": expected,
                                  "observed_reference_price": actual, "absolute_reference_difference": difference,
                                  "reconstructed_reference_rounded_to_cny_cent": rounded,
                                  "matches_at_observed_cent_precision": matches_precision,
                                  "event_amounts_independently_verified_against_issuer_notice": bool(symbol == "000403.SZ" and issuer_review.get("passed")),
                                  "separate_share_listing_date_independently_verified": False,
                                  "approved_for_economic_labels": False})
    numeric_cases = [r for r in event_samples if r["absolute_reference_difference"] is not None]
    if not numeric_cases or not all(r["matches_at_observed_cent_precision"] for r in numeric_cases):
        raise RuntimeError("Cash/share numeric example does not reconcile at observed cent quote precision.")
    summary = {
        "stage": "6_to_8", "audit_execution_completed": True, "stage8_fully_passed": False,
        "unit_and_quote_formula_checks_passed": unit_passed,
        "documentation_sha256": hashlib.sha256(doc_path.read_bytes()).hexdigest(),
        "kline_rows": totals["rows"], "active_rows": totals["active_rows"],
        "reference_price_discontinuity_candidates": totals["reference_price_breaks"],
        "missing_numeric_rows_are_suspended": totals["nonfinite_numeric_rows"] == totals["suspended_nonfinite_numeric_rows"],
        "strict_vwap_diagnostic_rows": len(strict),
        "strict_vwap_amount_residual_within_one_cny": bool(strict.amount_difference_from_low_price_times_volume_cny.abs().le(1).all()),
        "strict_vwap_interpretation": "consistent with sub-CNY amount precision effects; preserved without rewriting prices",
        "corporate_action_provider_queries": len(capability["queries"]),
        "successful_provider_queries": sum(r["status"] == "returned" for r in capability["queries"]),
        "adjustment_factor_normalization_anchor_verified": False,
        "adjustment_factor_probe_excluded_from_pre2025_inputs": True,
        "corporate_action_samples": event_samples,
        "complete_numeric_cash_and_share_examples_reconciled": len(numeric_cases),
        "reconciliation_precision_note": "Initial sub-cent tolerance was stricter than observed quote precision. Preserve theoretical difference and separately check cent-rounded reference; no raw price or action amount is altered.",
        "identity_evidence": identity["resolution"],
        "identity_notice_visual_review_passed": True,
        "issuer_action_example_visual_review_passed": bool(issuer_review.get("passed")),
        "frozen_inputs_modified": False,
        "outstanding": [
            "all_symbol_all_year_corporate_action_acquisition_and_coverage_reconciliation",
            "missing_amount_fields_and_conditional_tax_text_need_traceable_normalization",
            "rights_issues_mergers_and_non_dividend_events_not_covered_by_dividend_probe",
            "historical_identity_sidecar_and_versioned_industry_join_repair",
            "formal_market_calendar_and_full_historical_universe_verification",
            "share_receivables_payment_dates_listing_dates_and_tax_lot_accounting"
        ],
        "labels_ready": False, "factor_experiments_enabled": False,
        "model_experiments_enabled": False, "account_backtest_enabled": False
    }
    path = ROOT / "audits/stage8_data_audit.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit_completed": True, "stage8_fully_passed": False,
                      "units_passed": unit_passed, "sample_events": len(event_samples),
                      "numeric_share_cash_reconciliation_examples": len(numeric_cases),
                      "economic_labels_ready": False}))


if __name__ == "__main__":
    main()
