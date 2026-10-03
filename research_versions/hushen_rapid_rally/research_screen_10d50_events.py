"""Screen per-stock episodes where a later high rises >=50% from an earlier low
within at most 10 trading sessions.  This is descriptive labeling, not trading.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
# Dedicated Shanghai/Shenzhen main-board universe. Each security is counted once.
SOURCE = ROOT / "data_pipeline" / "data" / "qfq"
OUT = Path(__file__).resolve().parent / "outputs"
HORIZON = 10
TARGET = 0.50


def source_files():
    return list(SOURCE.rglob("*.parquet")) if SOURCE.exists() else []


def board_of(symbol: str) -> str:
    code = symbol.split(".")[0]
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    if symbol.endswith(".BJ") or code.startswith(("4", "8")):
        return "北交所"
    return "其他"


def find_candidates(low: np.ndarray, high: np.ndarray):
    """Return every start/end pair, using the earliest qualifying end per start."""
    hits = []
    n = len(low)
    for start in range(n):
        base = low[start]
        if not np.isfinite(base) or base <= 0:
            continue
        end_limit = min(n, start + HORIZON)
        target = base * (1 + TARGET)
        found = np.flatnonzero(high[start:end_limit] >= target)
        if len(found):
            end = start + int(found[0])
            hits.append((start, end, float(high[end] / base - 1)))
    return hits


def merge_overlaps(hits):
    """Merge overlapping qualifying windows into one independent rally episode."""
    if not hits:
        return []
    hits = sorted(hits, key=lambda z: (z[0], z[1]))
    groups = []
    current = [hits[0]]
    current_end = hits[0][1]
    for item in hits[1:]:
        if item[0] <= current_end:
            current.append(item)
            current_end = max(current_end, item[1])
        else:
            groups.append(current)
            current = [item]
            current_end = item[1]
    groups.append(current)
    # Representative is the largest realized rise inside each overlap group.
    return [max(group, key=lambda z: z[2]) for group in groups]


def one(path):
    frame = pd.read_parquet(path, columns=["date", "low", "high", "symbol"])
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame.date)
    low = pd.to_numeric(frame.low, errors="coerce").to_numpy(float)
    high = pd.to_numeric(frame.high, errors="coerce").to_numpy(float)
    candidates = find_candidates(low, high)
    events = merge_overlaps(candidates)
    symbol = str(frame.symbol.iloc[0]) if len(frame) else path.stem
    market = board_of(symbol)
    detail = []
    for event_no, (start, end, rise) in enumerate(events, 1):
        detail.append({
            "market": market, "symbol": symbol, "event_no": event_no,
            "start_date": frame.date.iloc[start], "end_date": frame.date.iloc[end],
            "trading_day_span": end - start + 1, "start_low_qfq": low[start],
            "end_high_qfq": high[end], "rise": rise,
        })
    summary = {
        "market": market, "symbol": symbol, "source_file": str(path), "first_date": frame.date.min(),
        "last_date": frame.date.max(), "bars": len(frame),
        "qualifying_window_count": len(candidates),
        "independent_event_count": len(events),
    }
    return summary, detail


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = source_files()
    summaries, details = [], []
    print(f"screening {len(files)} stocks", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (summary, detail) in enumerate(pool.map(one, files), 1):
            summaries.append(summary)
            details.extend(detail)
            if i % 250 == 0:
                print(f"[{i}/{len(files)}] {i/len(files):.1%}", flush=True)
    summary = pd.DataFrame(summaries).sort_values(
        ["independent_event_count", "qualifying_window_count", "symbol"],
        ascending=[False, False, True])
    detail = pd.DataFrame(details)
    summary.to_csv(OUT / "stock_event_counts.csv", index=False, encoding="utf-8-sig")
    detail.to_csv(OUT / "event_details.csv", index=False, encoding="utf-8-sig")
    if len(detail):
        detail.to_parquet(OUT / "event_details.parquet", index=False)
    market_stats = summary.groupby("market").agg(
        stocks=("symbol", "nunique"), stocks_with_event=("independent_event_count", lambda x: int((x > 0).sum())),
        independent_events=("independent_event_count", "sum"), qualifying_windows=("qualifying_window_count", "sum"),
    ).reset_index()
    market_stats["stock_event_rate"] = market_stats.stocks_with_event / market_stats.stocks
    market_stats.to_csv(OUT / "market_summary.csv", index=False, encoding="utf-8-sig")
    meta = {"generated_at": datetime.now().isoformat(timespec="seconds"),
            "stocks": len(summary), "horizon_trading_days": HORIZON,
            "rise_threshold": TARGET, "price_basis": "qfq",
            "universe": "Shanghai/Shenzhen main-board universe",
            "independent_event_definition": "overlapping qualifying windows merged"}
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(market_stats.to_string(index=False), flush=True)
    print("\nTop 30 stocks by independent events", flush=True)
    print(summary.head(30).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
