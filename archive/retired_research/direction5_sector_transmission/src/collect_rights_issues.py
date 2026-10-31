"""Historical rights-issue source for event classification; no assumed subscription."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "datasets/rights_issues_eastmoney_v1"
FIELDS = ["FINANCE_CODE", "SECUCODE", "SECURITY_CODE", "PLACING_RATIO", "ISSUE_PRICE", "TOTAL_SHARES_BEFORE",
          "ISSUE_NUM", "TOTAL_SHARES_AFTER", "EQUITY_RECORD_DATE", "PAY_START_DATE", "PAY_END_DATE",
          "LISTING_DATE", "EX_DIVIDEND_DATE", "FIRST_NOTICE_DATE"]


def main():
    STORE.mkdir(parents=True, exist_ok=True)
    params = {"reportName": "RPT_IPO_ALLOTMENT", "columns": ",".join(FIELDS), "pageSize": 500, "pageNumber": 1,
              "sortColumns": "EX_DIVIDEND_DATE,SECURITY_CODE", "sortTypes": "1,1",
              "filter": '(EX_DIVIDEND_DATE>=\'2018-01-01\')(EX_DIVIDEND_DATE<=\'2024-12-31\')(FIRST_NOTICE_DATE<=\'2024-12-31\')'}
    path = STORE / "raw.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        response = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get", params=params, timeout=(10, 30))
        response.raise_for_status()
        data = response.json()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if not data.get("success") or data["result"]["pages"] != 1 or len(data["result"]["data"]) != data["result"]["count"]:
        raise RuntimeError("Rights report incomplete or query failed.")
    df = pd.DataFrame(data["result"]["data"])
    if set(df.columns) != set(FIELDS):
        raise RuntimeError("Unexpected rights-event schema.")
    manifest = json.loads((ROOT / "inputs_pre2025/kline_v1/manifest.json").read_text(encoding="utf-8"))
    symbols = {r["symbol"] for r in manifest["files"]}
    frame = df.loc[df.SECUCODE.isin(symbols)].copy()
    frame["ex_date"] = pd.to_datetime(frame.EX_DIVIDEND_DATE)
    if not frame.ex_date.between("2018-01-01", "2024-12-31").all():
        raise RuntimeError("Rights event outside research boundary.")
    frame["event_type"] = "rights_issue_not_free_bonus"
    frame["subscription_assumed"] = False
    frame["approved_for_economic_labels"] = False
    frame.to_parquet(STORE / "scope_rights_issue_events.parquet", index=False)
    report = {"provider_rows": len(df), "scope_rows": len(frame), "server_query_complete": True,
              "request": params, "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "source_page": "https://data.eastmoney.com/xg/pg/",
              "no_subscription_or_free_shares_assumed": True,
              "planned_entitlement_ratio_must_be_distinguished_from_actual_total_share_increase": True,
              "cash_requirements_listing_dates_and_strategy_subscription_policy_pending": True,
              "economic_labels_ready": False}
    (STORE / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "audits/rights_issue_collection.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"historical_rights_events": len(frame), "subscription_assumed": False}))


if __name__ == "__main__":
    main()
