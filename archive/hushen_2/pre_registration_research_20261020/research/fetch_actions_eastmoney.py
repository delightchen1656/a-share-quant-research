"""Fill an explicit pre-2025 stock-year action gap list from Eastmoney via AkShare."""
from __future__ import annotations

import json
import argparse
from pathlib import Path

import akshare as ak
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORT_DATES = [
    "20191231", "20200331", "20200630", "20200930", "20201231",
    "20210331", "20210630", "20210930", "20211231",
    "20220331", "20220630", "20220930", "20221231",
    "20230331", "20230630", "20230930", "20231231",
    "20240331", "20240630", "20240930",
]


def num(value) -> float:
    x = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return 0.0 if pd.isna(x) else float(x)


def date_text(value) -> str:
    x = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(x) else x.strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch",
        choices=[
            "batch_002", "batch_003", "batch_004_pre2025_factor_tuning",
            "batch_005_pre2025_signal_filters", "batch_006_pre2025_active_objectives",
            "batch_007_pre2025_start_robustness",
        ],
        default="batch_002",
    )
    args = parser.parse_args()
    audit = ROOT / "沪深智能1" / "results" / args.batch / "audit"
    gaps_path = audit / "action_gaps.json"
    output_path = audit / "eastmoney_actions.json"
    gaps = json.loads(gaps_path.read_text(encoding="utf-8"))
    wanted = {f"{symbol}/{year}" for symbol, year in gaps}
    result = {key: [] for key in wanted}
    prior_records = {}
    if output_path.exists():
        prior_records = json.loads(output_path.read_text(encoding="utf-8")).get("records", {})
    receipts = []
    for report_date in REPORT_DATES:
        frame = ak.stock_fhps_em(report_date)
        receipts.append({"report_date": report_date, "rows": int(len(frame))})
        if frame.empty:
            continue
        for row in frame.itertuples(index=False, name=None):
            code = str(row[0]).zfill(6)
            symbol = code + (".SH" if code.startswith(("5", "6", "9")) else ".SZ")
            ex_date = date_text(row[15])
            if not ex_date:
                continue
            year = int(ex_date[:4])
            key = f"{symbol}/{year}"
            if key not in wanted:
                continue
            cash_per_share = num(row[5]) / 10.0
            bonus_per_share = num(row[3]) / 10.0
            transfer_per_share = num(row[4]) / 10.0
            record = {
                "code": symbol[-2:].lower() + "." + code,
                "dividRegistDate": date_text(row[14]),
                "dividOperateDate": ex_date,
                "dividPayDate": ex_date,
                "dividStockMarketDate": ex_date,
                "dividCashPsBeforeTax": str(cash_per_share),
                "dividCashPsAfterTax": "",
                "dividStocksPs": str(bonus_per_share),
                "dividReserveToStockPs": str(transfer_per_share),
                "source_report_date": report_date,
                "source": "Eastmoney stock_fhps_em via AkShare",
            }
            identity = (record["dividOperateDate"], record["dividCashPsBeforeTax"], record["dividStocksPs"], record["dividReserveToStockPs"])
            existing = {
                (x["dividOperateDate"], x["dividCashPsBeforeTax"], x["dividStocksPs"], x["dividReserveToStockPs"])
                for x in result[key]
            }
            if identity not in existing:
                result[key].append(record)
    merged_records = dict(prior_records)
    merged_records.update(result)
    payload = {
        "cutoff": "2024-12-31",
        "requested_keys": len(wanted),
        "successful_empty_keys": sum(not rows for rows in result.values()),
        "keys_with_events": sum(bool(rows) for rows in result.values()),
        "report_receipts": receipts,
        "records": merged_records,
        "limitations": [
            "The public table supplies record and ex-right dates but not separate cash-payment or bonus-share listing dates in this endpoint.",
            "Payment and release dates are conservatively set to the ex-right date; this must be disclosed in the final audit.",
        ],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ["requested_keys", "successful_empty_keys", "keys_with_events"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
