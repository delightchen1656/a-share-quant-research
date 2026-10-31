"""Combine historical event sources, retaining all unsupported/conflicting cases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from collect_action_bulk import parse_plan

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/corporate_actions_reconciled_v1"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def date(value):
    value = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(value) else str(value.date())


def num(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def one(values):
    unique = {v for v in values if v is not None}
    return next(iter(unique)) if len(unique) == 1 else None


def main(allow_partial):
    source_root = ROOT / "datasets/corporate_actions_baostock_v1"
    kline_manifest = json.loads((ROOT / "inputs_pre2025/kline_v1/manifest.json").read_text(encoding="utf-8"))
    query_rows, detail_rows, raw_files = [], [], []
    for symbol in [r["symbol"] for r in kline_manifest["files"]]:
        for year in range(2018, 2025):
            p = source_root / "raw" / symbol / f"{year}.json"
            if not p.exists():
                query_rows.append({"symbol": symbol, "year": year, "status": "not_collected", "events": None})
                continue
            content = p.read_bytes()
            response = json.loads(content)
            raw_files.append({"file": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest()})
            query_rows.append({"symbol": symbol, "year": year, "status": response["status"], "events": len(response.get("rows", []))})
            if not response["status"].startswith("returned_"):
                continue
            for index, raw_row in enumerate(response.get("rows", [])):
                raw = dict(zip(response["fields"], raw_row))
                if raw.get("code") != symbol[-2:].lower() + "." + symbol[:6]:
                    raise RuntimeError("Detailed action security identifier mismatch: " + str(p))
                if not f"{year}-01-01" <= raw.get("dividOperateDate", "") <= f"{year}-12-31":
                    raise RuntimeError("Detailed action year mismatch: " + str(p))
                plan = parse_plan(raw.get("dividCashStock"))
                values = None if plan is None else [float(plan[k] / 10) for k in ("派", "送", "转")]
                issues = []
                for position, field in enumerate(["dividCashPsBeforeTax", "dividStocksPs", "dividReserveToStockPs"]):
                    value = raw.get(field, "")
                    numeric = num(value)
                    if value and numeric is None:
                        issues.append("non_numeric_" + field)
                    if values is not None and numeric is not None and abs(numeric - values[position]) > 0.0000011:
                        issues.append("plan_field_disagreement_" + field)
                if plan is None:
                    issues.append("plan_grammar_not_supported")
                detail_rows.append({"symbol": symbol, "year": year, "ex_date": date(raw.get("dividOperateDate")),
                                    "register_date": date(raw.get("dividRegistDate")),
                                    "cash_payment_date": date(raw.get("dividPayDate")),
                                    "bonus_listing_date": date(raw.get("dividStockMarketDate")),
                                    "notice_date": date(raw.get("dividPlanDate")),
                                    "cash_per_share": values[0] if values else None,
                                    "bonus_per_share": values[1] if values else None,
                                    "transfer_per_share": values[2] if values else None,
                                    "normalized": values is not None and not issues,
                                    "raw_after_tax": raw.get("dividCashPsAfterTax"), "raw_plan": raw.get("dividCashStock"),
                                    "source_file": str(p.relative_to(ROOT)), "source_row": index,
                                    "issues": json.dumps(issues), "approved_for_economic_labels": False})
    coverage = pd.DataFrame(query_rows)
    successful = coverage.status.str.startswith("returned_")
    if not allow_partial and not successful.all():
        raise RuntimeError("Detailed query coverage is not complete; use explicit --allow-partial only for input diagnostics.")
    OUT.mkdir(parents=True, exist_ok=True)
    coverage.to_parquet(OUT / "symbol_year_query_coverage.parquet", index=False)
    detail = pd.DataFrame(detail_rows)
    detail.to_parquet(OUT / "detail_rows_normalized.parquet", index=False)
    east = pd.read_parquet(ROOT / "datasets/corporate_actions_eastmoney_v1/scope_events_normalized_provisional.parquet")
    east["ex_date"] = east.ex_date.dt.strftime("%Y-%m-%d")
    east["register_date"] = east.register_date.dt.strftime("%Y-%m-%d")
    override_path = ROOT / "datasets/manual_action_overrides_v1/overrides.json"
    overrides = json.loads(override_path.read_text(encoding="utf-8"))
    overrides = {(r["symbol"], r["ex_date"]): r for r in overrides}
    for value in overrides.values():
        if hashlib.sha256((ROOT / value["source_file"]).read_bytes()).hexdigest() != value["source_sha256"]:
            raise RuntimeError("Issuer override source hash mismatch.")
    bg = {(s, d): g for (s, d), g in detail.groupby(["symbol", "ex_date"])}
    eg = {(s, d): g for (s, d), g in east.groupby(["symbol", "ex_date"])}
    ledger = []
    for event_key in sorted(set(bg) | set(eg)):
        b, e = bg.get(event_key), eg.get(event_key)
        issues, canonical = [], None
        override = overrides.get(event_key)
        original_b_count = 0 if b is None else len(b)
        redundant_detail_rows = 0
        if b is not None and len(b) > 1 and e is not None and len(e) == 1 and b.normalized.all() and e.amounts_normalized.all():
            economic_columns = ["cash_per_share", "bonus_per_share", "transfer_per_share", "register_date", "cash_payment_date", "bonus_listing_date", "notice_date"]
            unique = b.drop_duplicates(economic_columns)
            if len(unique) == 1:
                bv = unique[["cash_per_share", "bonus_per_share", "transfer_per_share"]].iloc[0].tolist()
                ev = e[["cash_per_share", "bonus_per_share", "transfer_per_share"]].iloc[0].tolist()
                if max(abs(x-y) for x,y in zip(bv, ev)) <= 0.0000011:
                    redundant_detail_rows = len(b) - 1
                    b = unique
        b_values = b[["cash_per_share", "bonus_per_share", "transfer_per_share"]].sum().tolist() if b is not None and b.normalized.all() else None
        e_values = e[["cash_per_share", "bonus_per_share", "transfer_per_share"]].sum().tolist() if e is not None and e.amounts_normalized.all() else None
        multiple = (b is not None and len(b) > 1) or (e is not None and len(e) > 1)
        if override:
            canonical = [override[k] for k in ("cash_per_share", "bonus_per_share", "transfer_per_share")]
        elif multiple:
            issues.append("multiple_event_components_without_verified_issuer_aggregation")
        elif b_values is not None and e_values is not None:
            if max(abs(x - y) for x, y in zip(b_values, e_values)) > 0.0000011:
                issues.append("provider_amount_disagreement")
            else:
                canonical = e_values
        elif b_values is not None:
            canonical = b_values
            issues.append("single_provider_amounts")
        elif e_values is not None:
            canonical = e_values
            issues.append("single_provider_amounts")
        else:
            issues.append("amounts_unresolved")
        reg_b = one(b.register_date.tolist()) if b is not None else None
        reg_e = one(e.register_date.dropna().tolist()) if e is not None else None
        if reg_b and reg_e and reg_b != reg_e:
            issues.append("provider_registration_date_disagreement")
        reg = override["register_date"] if override else (reg_b or reg_e)
        if not reg or reg >= event_key[1]:
            issues.append("registration_date_missing_or_invalid")
        pay = override["cash_payment_date"] if override else (one(b.cash_payment_date.tolist()) if b is not None else None)
        listing = one(b.bonus_listing_date.tolist()) if b is not None else None
        if canonical is not None:
            if canonical[0] > 0 and (pay is None or pay < event_key[1]):
                issues.append("payment_date_missing_or_invalid")
            if canonical[1] + canonical[2] > 0 and (listing is None or listing < event_key[1]):
                issues.append("share_listing_date_missing_or_invalid")
        else:
            issues.append("cannot_determine_required_payment_or_share_dates")
        blocking = [i for i in issues if i != "single_provider_amounts"]
        ledger.append({"symbol": event_key[0], "ex_date": pd.Timestamp(event_key[1]),
                       "register_date": pd.to_datetime(reg), "cash_payment_date": pd.to_datetime(pay),
                       "bonus_listing_date": pd.to_datetime(listing),
                       "cash_per_share": canonical[0] if canonical is not None else None,
                       "bonus_per_share": canonical[1] if canonical is not None else None,
                       "transfer_per_share": canonical[2] if canonical is not None else None,
                       "eastmoney_components": 0 if e is None else len(e), "baostock_components": original_b_count,
                       "baostock_effective_components": 0 if b is None else len(b),
                       "equivalent_detail_rows_collapsed_with_independent_single_event_confirmation": redundant_detail_rows,
                       "manual_issuer_override": override is not None,
                       "quote_reference_special": bool(override and override["quote_reference_may_differ_from_public_shareholder_cash"]),
                       "provider_amounts_agree": b_values is not None and e_values is not None and max(abs(x-y) for x,y in zip(b_values,e_values)) <= 0.0000011,
                       "issues": json.dumps(issues), "event_fields_complete": not blocking,
                       "approved_for_economic_labels": False})
    ledger = pd.DataFrame(ledger)
    ledger.to_parquet(OUT / "dividend_event_ledger_provisional.parquet", index=False)
    ledger.loc[~ledger.event_fields_complete].to_parquet(OUT / "unresolved_event_fields.parquet", index=False)
    breaks = pd.read_parquet(ROOT / "audits/semantics_v1/breaks.parquet")
    pairs = set(zip(ledger.symbol, ledger.ex_date))
    breaks["event_on_same_date"] = [(s, d) in pairs for s, d in zip(breaks.symbol, breaks.date)]
    breaks.loc[~breaks.event_on_same_date].to_parquet(OUT / "reference_breaks_no_exact_date_dividend.parquet", index=False)
    issues_count = {}
    for encoded in ledger.issues:
        for issue in json.loads(encoded):
            issues_count[issue] = issues_count.get(issue, 0) + 1
    report = {"planned_symbol_years": len(coverage), "successful_symbol_year_queries": int(successful.sum()),
              "missing_queries": int(coverage.status.eq("not_collected").sum()), "failed_queries": int(coverage.status.eq("failed").sum()),
              "all_planned_queries_successful": bool(successful.all()),
              "raw_detailed_event_rows": len(detail), "eastmoney_event_rows": len(east),
              "merged_event_groups": len(ledger), "event_groups_with_complete_amounts_and_required_dates": int(ledger.event_fields_complete.sum()),
              "issuer_overrides_applied": int(ledger.manual_issuer_override.sum()),
              "equivalent_detail_duplicate_rows_collapsed": int(ledger.equivalent_detail_rows_collapsed_with_independent_single_event_confirmation.sum()),
              "exact_date_matched_reference_breaks": int(breaks.event_on_same_date.sum()),
              "reference_breaks_not_exact_date_matched": int((~breaks.event_on_same_date).sum()),
              "issue_counts": issues_count, "raw_files": raw_files,
              "rights_issues_and_other_non_dividend_actions_included": False,
              "complete_corporate_action_ledger": False, "economic_labels_ready": False,
              "note": "Exact-date misses can include events during suspension; interval reconciliation follows separately."}
    write_json(OUT / "manifest.json", report)
    write_json(ROOT / "audits/corporate_action_reconciliation.json", {k:v for k,v in report.items() if k != "raw_files"})
    print(json.dumps({k:v for k,v in report.items() if k != "raw_files"}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    main(args.allow_partial)
