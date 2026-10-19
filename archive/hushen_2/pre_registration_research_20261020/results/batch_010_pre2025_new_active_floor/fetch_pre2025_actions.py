"""Fetch only the seven frozen Batch010 champion pre-2025 action-coverage gaps."""
from __future__ import annotations

import json
from pathlib import Path

import akshare as ak
import pandas as pd


HERE = Path(__file__).resolve().parent
REPORT_DATES = [
    "20191231", "20200331", "20200630", "20200930", "20201231",
    "20210331", "20210630", "20210930", "20211231",
    "20220331", "20220630", "20220930", "20221231",
    "20230331", "20230630", "20230930", "20231231",
    "20240331", "20240630", "20240930",
]


def number(value) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(parsed) else float(parsed)


def date_text(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


gaps = json.loads((HERE / "audit" / "action_gaps.json").read_text(encoding="utf-8"))
wanted = {f"{symbol}/{year}" for symbol, year in gaps}
records = {key: [] for key in wanted}
receipts = []
for report_date in REPORT_DATES:
    frame = ak.stock_fhps_em(report_date)
    receipts.append({"report_date": report_date, "rows": int(len(frame))})
    for row in frame.itertuples(index=False, name=None):
        code = str(row[0]).zfill(6)
        symbol = code + (".SH" if code.startswith(("5", "6", "9")) else ".SZ")
        ex_date = date_text(row[15])
        key = f"{symbol}/{ex_date[:4]}" if ex_date else ""
        if key not in wanted or ex_date > "2024-12-31":
            continue
        item = {
            "code": symbol[-2:].lower() + "." + code,
            "dividRegistDate": date_text(row[14]), "dividOperateDate": ex_date,
            "dividPayDate": ex_date, "dividStockMarketDate": ex_date,
            "dividCashPsBeforeTax": str(number(row[5]) / 10.0), "dividCashPsAfterTax": "",
            "dividStocksPs": str(number(row[3]) / 10.0),
            "dividReserveToStockPs": str(number(row[4]) / 10.0),
            "source_report_date": report_date, "source": "Eastmoney stock_fhps_em via AkShare",
        }
        identity = (item["dividOperateDate"], item["dividCashPsBeforeTax"], item["dividStocksPs"], item["dividReserveToStockPs"])
        prior = {(x["dividOperateDate"], x["dividCashPsBeforeTax"], x["dividStocksPs"], x["dividReserveToStockPs"]) for x in records[key]}
        if identity not in prior:
            records[key].append(item)
payload = {
    "cutoff": "2024-12-31", "requested_keys": len(wanted),
    "successful_empty_keys": sum(not value for value in records.values()),
    "keys_with_events": sum(bool(value) for value in records.values()),
    "report_receipts": receipts, "records": records,
    "limitations": ["Payment and share-release dates are conservatively set to the public ex-right date."],
}
(HERE / "audit" / "eastmoney_actions.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: payload[key] for key in ["requested_keys", "successful_empty_keys", "keys_with_events"]}, ensure_ascii=False))
