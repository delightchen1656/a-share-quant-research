"""Acquire only historical event fields; exclude price-performance/current-value columns."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import time
from decimal import Decimal
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "datasets/corporate_actions_eastmoney_v1"
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
FIELDS = ["SECUCODE", "SECURITY_CODE", "ORG_CODE", "BONUS_IT_RATIO", "BONUS_RATIO", "IT_RATIO",
          "PRETAX_BONUS_RMB", "PLAN_NOTICE_DATE", "EQUITY_RECORD_DATE", "EX_DIVIDEND_DATE",
          "REPORT_DATE", "ASSIGN_PROGRESS", "IMPL_PLAN_PROFILE", "NOTICE_DATE", "PUBLISH_DATE"]
FILTER = '(EX_DIVIDEND_DATE>=\'2018-01-01\')(EX_DIVIDEND_DATE<=\'2024-12-31\')(NOTICE_DATE<=\'2024-12-31\')(ASSIGN_PROGRESS="实施分配")'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page(number):
    path = STORE / "raw" / f"page_{number:04d}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("success") and data.get("result"):
            return number, data
    params = {"reportName": "RPT_SHAREBONUS_DET", "columns": ",".join(FIELDS), "pageSize": 500,
              "pageNumber": number, "sortColumns": "EX_DIVIDEND_DATE,SECURITY_CODE,REPORT_DATE", "sortTypes": "1,1,1", "filter": FILTER}
    error = None
    for attempt in range(3):
        try:
            response = requests.get(URL, params=params, timeout=(10, 30))
            response.raise_for_status()
            data = response.json()
            if not data.get("success") or not data.get("result"):
                raise RuntimeError(str(data.get("message")))
            for row in data["result"]["data"]:
                if set(row) != set(FIELDS):
                    raise RuntimeError("Provider returned unrequested fields or changed schema.")
                date = pd.Timestamp(row["EX_DIVIDEND_DATE"])
                notice = pd.Timestamp(row["NOTICE_DATE"])
                if not pd.Timestamp("2018-01-01") <= date <= pd.Timestamp("2024-12-31") or notice > pd.Timestamp("2024-12-31"):
                    raise RuntimeError("Historical filter violated.")
            save(path, data)
            return number, data
        except Exception as exc:
            error = str(exc)
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    save(STORE / "failures" / f"page_{number:04d}.json", {"page": number, "error": error})
    raise RuntimeError(f"Historical page {number} failed: {error}")


def parse_plan(text):
    text = re.sub(r"\s+", "", str(text or ""))
    # Only a complete leading ten-share distribution segment is recognized.
    match = re.match(r"^10((?:(?:送|转|派)\d+(?:\.\d+)?(?:元|股)?)+)(?=[(（]|$)", text)
    if not match:
        return None
    values = {"送": Decimal(0), "转": Decimal(0), "派": Decimal(0)}
    for kind, value in re.findall(r"(送|转|派)(\d+(?:\.\d+)?)", match.group(1)):
        values[kind] += Decimal(value)
    return values


def main():
    STORE.mkdir(parents=True, exist_ok=True)
    request = {"provider": "Eastmoney Choice historical distribution report", "source_page": "https://data.eastmoney.com/yjfp/",
               "endpoint": URL, "reportName": "RPT_SHAREBONUS_DET", "columns": FIELDS, "filter": FILTER,
               "pageSize": 500, "no_price_performance_columns_requested": True,
               "meaning": "historically dated vendor reconstruction; not guaranteed original-vintage revisions"}
    config_path = STORE / "request.json"
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != request:
        raise RuntimeError("Existing request contract differs. Use a new dataset version.")
    save(config_path, request)
    _, first = page(1)
    expected_count, expected_pages = first["result"]["count"], first["result"]["pages"]
    records, files = list(first["result"]["data"]), []
    pages = {1: first}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(page, n) for n in range(2, expected_pages + 1)]
        for future in concurrent.futures.as_completed(futures):
            n, response = future.result()
            if response["result"]["count"] != expected_count or response["result"]["pages"] != expected_pages:
                raise RuntimeError("Provider result set changed during pagination; do not promote.")
            pages[n] = response
            records.extend(response["result"]["data"])
            if len(pages) % 10 == 0:
                print(json.dumps({"downloaded_pages": len(pages), "expected_pages": expected_pages}), flush=True)
    if len(records) != expected_count:
        raise RuntimeError("Pagination row count does not match provider count.")
    for n in sorted(pages):
        p = STORE / "raw" / f"page_{n:04d}.json"
        files.append({"file": str(p.relative_to(STORE)), "sha256": digest(p), "rows": len(pages[n]["result"]["data"])})
    frame = pd.DataFrame(records)
    frame.to_parquet(STORE / "historical_all_market_events.parquet", index=False)
    kline_manifest = json.loads((ROOT / "inputs_pre2025/kline_v1/manifest.json").read_text(encoding="utf-8"))
    symbols = {r["symbol"] for r in kline_manifest["files"]}
    frame = frame.loc[frame.SECUCODE.isin(symbols)].copy()
    frame["ex_date"] = pd.to_datetime(frame.EX_DIVIDEND_DATE)
    frame["register_date"] = pd.to_datetime(frame.EQUITY_RECORD_DATE)
    frame["implementation_notice_date"] = pd.to_datetime(frame.NOTICE_DATE)
    normalized, issues = [], []
    for index, row in frame.iterrows():
        plan = parse_plan(row.IMPL_PLAN_PROFILE)
        event = {"symbol": row.SECUCODE, "org_code": row.ORG_CODE, "ex_date": row.ex_date,
                 "register_date": row.register_date, "implementation_notice_date": row.implementation_notice_date,
                 "report_date": row.REPORT_DATE, "raw_plan": row.IMPL_PLAN_PROFILE,
                 "cash_per_share": None, "bonus_per_share": None, "transfer_per_share": None,
                 "cash_payment_date": None, "bonus_listing_date": None,
                 "amounts_normalized": False, "approved_for_economic_labels": False,
                 "raw_row_index": int(index)}
        if plan is not None:
            disagreements = []
            for kind, field, output in (("派", "PRETAX_BONUS_RMB", "cash_per_share"), ("送", "BONUS_RATIO", "bonus_per_share"), ("转", "IT_RATIO", "transfer_per_share")):
                numeric = row[field]
                if pd.notna(numeric) and abs(Decimal(str(numeric)) - plan[kind]) > Decimal("0.00001"):
                    disagreements.append(field)
                event[output] = float(plan[kind] / Decimal(10))
            event["zero_basis"] = "explicitly_absent_component_in_complete_ten_share_plan_not_blank_numeric_field"
            event["amounts_normalized"] = not disagreements
            if disagreements:
                issues.append({"symbol": row.SECUCODE, "ex_date": str(row.ex_date.date()), "type": "plan_numeric_disagreement", "fields": disagreements})
        else:
            event["zero_basis"] = None
            issues.append({"symbol": row.SECUCODE, "ex_date": str(row.ex_date.date()), "type": "plan_grammar_not_supported", "plan": row.IMPL_PLAN_PROFILE})
        normalized.append(event)
    normalized = pd.DataFrame(normalized)
    normalized.to_parquet(STORE / "scope_events_normalized_provisional.parquet", index=False)
    duplicates = normalized.loc[normalized.duplicated(["symbol", "ex_date", "register_date"], keep=False)].copy()
    duplicates.to_parquet(STORE / "duplicate_event_keys.parquet", index=False)
    coverage = []
    for symbol in sorted(symbols):
        subset = normalized.loc[normalized.symbol.eq(symbol)]
        for year in range(2018, 2025):
            selected = subset.loc[subset.ex_date.dt.year.eq(year)]
            coverage.append({"symbol": symbol, "year": year, "provider_events": len(selected),
                             "status": "bulk_query_returned_events" if len(selected) else "bulk_query_no_matching_event_not_proof_of_no_event",
                             "individual_symbol_year_queried": False, "provider_pagination_complete": True,
                             "payment_and_listing_dates_complete": False})
    pd.DataFrame(coverage).to_parquet(STORE / "symbol_year_coverage.parquet", index=False)
    audit = {"server_query_complete": True, "provider_matching_rows_all_markets": expected_count,
             "pages": expected_pages, "scope_symbols": len(symbols), "scope_events": len(normalized),
             "scope_symbol_year_combinations": len(coverage), "normalized_amount_rows": int(normalized.amounts_normalized.sum()),
             "duplicate_event_key_rows": len(duplicates), "normalization_issues": issues,
             "missing_payment_dates": len(normalized), "missing_bonus_listing_dates": int(normalized.eval("bonus_per_share > 0 or transfer_per_share > 0").sum()),
             "cash_and_listing_dates_require_supplement": True,
             "complete_corporate_action_ledger": False, "approved_for_economic_labels": False,
             "raw_files": files, "request_contract_sha256": digest(config_path)}
    save(STORE / "manifest.json", audit)
    save(ROOT / "audits/corporate_action_bulk_collection.json", {k: v for k, v in audit.items() if k not in ("raw_files", "normalization_issues")})
    print(json.dumps({k: v for k, v in audit.items() if k not in ("raw_files", "normalization_issues")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
