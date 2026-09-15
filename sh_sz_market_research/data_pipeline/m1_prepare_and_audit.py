"""M1: download auxiliary data and audit all main-board daily files."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "outputs" / "m1_data_quality"
INDEX_CODES = {
    "000300.SH": "sh.000300", "000905.SH": "sh.000905",
    "000852.SH": "sh.000852", "000001.SH": "sh.000001",
    "399001.SZ": "sz.399001",
}


def result_frame(rs) -> pd.DataFrame:
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if rs.error_code != "0":
        raise RuntimeError(f"BaoStock {rs.error_code}: {rs.error_msg}")
    return pd.DataFrame(rows, columns=rs.fields)


def download_auxiliary(start: str, end: str) -> dict:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    summary = {"indices": {}, "industry_rows": 0}
    try:
        index_dir = DATA / "indices"
        index_dir.mkdir(parents=True, exist_ok=True)
        fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
        for symbol, code in INDEX_CODES.items():
            last_error = None
            for attempt in range(3):
                try:
                    frame = result_frame(bs.query_history_k_data_plus(
                        code, fields, start_date=start, end_date=end,
                        frequency="d", adjustflag="3"))
                    numeric = ["open", "high", "low", "close", "preclose", "volume", "amount", "pctChg"]
                    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
                    frame["date"] = pd.to_datetime(frame.date)
                    frame["symbol"] = symbol
                    frame.to_parquet(index_dir / f"{symbol}.parquet", index=False)
                    summary["indices"][symbol] = int(len(frame))
                    break
                except Exception as exc:
                    last_error = exc
                    time.sleep(1 + attempt)
            else:
                raise RuntimeError(f"index {symbol} failed: {last_error}")

        industry = result_frame(bs.query_stock_industry())
        if not industry.empty:
            industry["symbol"] = industry.code.map(
                lambda x: x.split(".")[1] + "." + x.split(".")[0].upper())
            universe = pd.read_csv(DATA / "metadata" / "historical_mainboard_universe.csv",
                                   dtype=str, encoding="utf-8-sig")
            industry = industry[industry.symbol.isin(set(universe.symbol))].copy()
            industry.to_csv(DATA / "metadata" / "current_industry_map.csv",
                            index=False, encoding="utf-8-sig")
            summary["industry_rows"] = int(len(industry))
            summary["industry_update_dates"] = sorted(industry.updateDate.dropna().unique().tolist())
    finally:
        bs.logout()
    return summary


def audit_symbol(task):
    symbol, active_at_end, expected_end = task
    exchange = symbol[-2:]
    paths = {kind: DATA / kind / exchange / f"{symbol}.parquet" for kind in ("raw", "qfq")}
    result = {"symbol": symbol, "exchange": exchange, "raw_exists": paths["raw"].exists(),
              "qfq_exists": paths["qfq"].exists(), "issues": []}
    frames = {}
    for kind, path in paths.items():
        if not path.exists():
            result["issues"].append(f"missing_{kind}")
            continue
        try:
            frame = pd.read_parquet(path, columns=[
                "date", "open", "high", "low", "close", "volume",
                "amount", "tradestatus", "isST"])
            frame["date"] = pd.to_datetime(frame.date)
            frames[kind] = frame
            result[f"{kind}_rows"] = int(len(frame))
            result[f"{kind}_first"] = str(frame.date.min().date()) if len(frame) else ""
            result[f"{kind}_last"] = str(frame.date.max().date()) if len(frame) else ""
            if frame.empty:
                result["issues"].append(f"empty_{kind}")
                continue
            if active_at_end and frame.date.max() < pd.Timestamp(expected_end):
                result["issues"].append(f"stale_end_{kind}")
            if frame.date.duplicated().any(): result["issues"].append(f"duplicate_date_{kind}")
            if not frame.date.is_monotonic_increasing: result["issues"].append(f"unsorted_date_{kind}")
            prices = frame[["open", "high", "low", "close"]]
            if prices.isna().any().any(): result["issues"].append(f"missing_price_{kind}")
            bad_ohlc = (frame.high < prices[["open", "close", "low"]].max(axis=1)) | (frame.low > prices[["open", "close", "high"]].min(axis=1))
            if bad_ohlc.any(): result["issues"].append(f"bad_ohlc_{kind}")
            if (frame.volume < 0).any() or (frame.amount < 0).any(): result["issues"].append(f"negative_volume_{kind}")
        except Exception as exc:
            result["issues"].append(f"read_{kind}:{type(exc).__name__}")
    if "raw" in frames and "qfq" in frames:
        if not frames["raw"].date.reset_index(drop=True).equals(frames["qfq"].date.reset_index(drop=True)):
            result["issues"].append("raw_qfq_date_mismatch")
        result["trade_days"] = int(len(frames["raw"]))
        result["suspended_days"] = int((frames["raw"].tradestatus.astype(str) != "1").sum())
        result["st_days"] = int((frames["raw"].isST.astype(str) == "1").sum())
    result["issue_count"] = len(result["issues"])
    result["issues"] = "|".join(result["issues"])
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    universe = pd.read_csv(DATA / "metadata" / "historical_mainboard_universe.csv",
                           dtype=str, encoding="utf-8-sig")
    universe = universe.drop_duplicates("symbol").sort_values("symbol")
    end_date = "2026-09-11"
    out_dates = pd.to_datetime(universe.outDate, errors="coerce")
    tasks = [(row.symbol, pd.isna(out_date) or out_date >= pd.Timestamp(end_date), end_date)
             for row, out_date in zip(universe.itertuples(index=False), out_dates)]
    symbols = [task[0] for task in tasks]
    print(f"M1 audit: {len(symbols)} stocks", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(audit_symbol, tasks))
    quality = pd.DataFrame(rows)
    quality.to_csv(OUT / "stock_quality.csv", index=False, encoding="utf-8-sig")
    auxiliary = download_auxiliary(cfg["start_date"], "2026-09-11")
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "range": [cfg["start_date"], "2026-09-11"],
        "stocks": len(symbols), "raw_files": int(quality.raw_exists.sum()),
        "qfq_files": int(quality.qfq_exists.sum()),
        "clean_stocks": int(quality.issue_count.eq(0).sum()),
        "stocks_with_issues": int(quality.issue_count.gt(0).sum()),
        "issue_counts": quality.loc[quality.issues.ne(""), "issues"].str.split("|").explode().value_counts().to_dict(),
        **auxiliary,
        "industry_limitation": "BaoStock classification is current/as-published, not complete point-in-time history",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    sample = quality.groupby("exchange", group_keys=False).apply(
        lambda x: x.sample(min(15, len(x)), random_state=20260914), include_groups=False)
    sample.to_csv(OUT / "ths_manual_check_sample_30.csv", index=False, encoding="utf-8-sig")
    report = f"""# M1 数据质量验收报告

生成时间：{summary['generated_at']}
数据区间：{summary['range'][0]} 至 {summary['range'][1]}

| 项目 | 结果 |
|---|---:|
| 历史主板股票 | {summary['stocks']} |
| 不复权文件 | {summary['raw_files']} |
| 前复权文件 | {summary['qfq_files']} |
| 自动质检无异常 | {summary['clean_stocks']} |
| 存在异常 | {summary['stocks_with_issues']} |
| 指数文件 | {len(summary['indices'])} |
| 当前行业映射 | {summary['industry_rows']} |

行业字段来自BaoStock当前/公布口径，不具备完整历史行业变更链。它可用于M2分层描述和基准2-2功能验证；在取得历史时点行业数据前，不宣称基准2-2已消除行业幸存偏差。

`ths_manual_check_sample_30.csv`是30只同花顺人工抽样核对清单，自动检查不能替代第三方页面核对。
"""
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
