"""M2: build point-in-time Pool A/B/C membership from technical data only."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "outputs" / "m2_pools"
DERIVED = DATA / "derived" / "pools"


def build_one(symbol: str):
    exchange = symbol[-2:]
    source = DATA / "qfq" / exchange / f"{symbol}.parquet"
    frame = pd.read_parquet(source).sort_values("date").reset_index(drop=True)
    close, volume = frame.close.astype(float), frame.volume.astype(float)
    returns = close.pct_change(fill_method=None)
    frame["listing_days"] = np.arange(1, len(frame) + 1)
    frame["ret5"] = close.pct_change(5, fill_method=None)
    frame["ret20"] = close.pct_change(20, fill_method=None)
    frame["amount20"] = frame.amount.astype(float).rolling(20).mean()
    frame["turn20"] = frame.turn.astype(float).rolling(20).mean()
    frame["valid60"] = frame.tradestatus.astype(str).eq("1").rolling(60).sum()
    frame["vol60"] = returns.rolling(60).std()
    low60 = frame.low.astype(float).rolling(60).min()
    high60 = frame.high.astype(float).rolling(60).max()
    frame["range60"] = high60 / low60 - 1
    frame["rise_from_low60"] = close / low60 - 1
    frame["volume_spike"] = volume / volume.rolling(20).mean()
    pool_a = frame.tradestatus.astype(str).eq("1") & frame.isST.astype(str).ne("1")
    pool_b = (pool_a & frame.listing_days.ge(120) & frame.amount20.ge(100_000_000)
              & frame.turn20.ge(1.0) & frame.valid60.ge(55)
              & frame.vol60.between(.015, .055) & frame.range60.ge(.18)
              & frame.ret5.le(.12) & frame.ret20.le(.20)
              & frame.rise_from_low60.le(.30) & frame.pctChg.astype(float).lt(9.5)
              & frame.volume_spike.le(5))
    number = symbol[:6]
    pool_c_prefix = number.startswith(("002", "003", "603", "605"))
    frame["pool_a"], frame["pool_b"], frame["pool_c"] = pool_a, pool_b, pool_b & pool_c_prefix
    target = DERIVED / exchange / f"{symbol}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame[["date", "symbol", "pool_a", "pool_b", "pool_c", "listing_days",
           "amount20", "turn20", "valid60", "vol60", "range60", "ret5",
           "ret20", "rise_from_low60", "volume_spike"]].to_parquet(target, index=False)
    daily = frame[["date", "pool_a", "pool_b", "pool_c"]].copy()
    daily[["pool_a", "pool_b", "pool_c"]] = daily[["pool_a", "pool_b", "pool_c"]].astype("int8")
    return symbol, daily, int(pool_a.sum()), int(pool_b.sum()), int((pool_b & pool_c_prefix).sum())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(DATA / "metadata" / "historical_mainboard_universe.csv",
                           dtype=str, encoding="utf-8-sig")
    symbols = universe.symbol.drop_duplicates().sort_values().tolist()
    print(f"M2 pools: {len(symbols)} stocks", flush=True)
    daily_parts, stock_rows = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (symbol, daily, count_a, count_b, count_c) in enumerate(pool.map(build_one, symbols), 1):
            daily_parts.append(daily)
            stock_rows.append({"symbol": symbol, "pool_a_days": count_a,
                               "pool_b_days": count_b, "pool_c_days": count_c})
            if i % 250 == 0:
                print(f"[{i}/{len(symbols)}] {i/len(symbols):.1%}", flush=True)
    daily = pd.concat(daily_parts, ignore_index=True).groupby("date")[["pool_a", "pool_b", "pool_c"]].sum().reset_index()
    daily.to_parquet(OUT / "daily_pool_counts.parquet", index=False)
    daily.to_csv(OUT / "daily_pool_counts.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(stock_rows).to_csv(OUT / "stock_pool_days.csv", index=False, encoding="utf-8-sig")
    annual = daily.assign(year=pd.to_datetime(daily.date).dt.year).groupby("year")[["pool_a", "pool_b", "pool_c"]].agg(["mean", "min", "max"])
    annual.columns = [f"{pool_name}_{stat}" for pool_name, stat in annual.columns]
    annual.reset_index().to_csv(OUT / "annual_pool_counts.csv", index=False, encoding="utf-8-sig")
    latest = daily.sort_values("date").iloc[-1]
    summary = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "stocks": len(symbols), "first_date": str(pd.Timestamp(daily.date.min()).date()),
               "last_date": str(pd.Timestamp(daily.date.max()).date()),
               "latest_counts": {k: int(latest[k]) for k in ("pool_a", "pool_b", "pool_c")},
               "rules_frozen_for_m3": True}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "REPORT.md").write_text(
        "# M2 三层股票池报告\n\n"
        f"生成时间：{summary['generated_at']}  \n"
        f"覆盖：{summary['first_date']} 至 {summary['last_date']}  \n\n"
        "| 股票池 | 最新交易日数量 |\n|---|---:|\n"
        f"| Pool A 全部可交易主板 | {summary['latest_counts']['pool_a']} |\n"
        f"| Pool B 活跃主板 | {summary['latest_counts']['pool_b']} |\n"
        f"| Pool C 中小活跃主板 | {summary['latest_counts']['pool_c']} |\n\n"
        "Pool B/C阈值按开发计划初值冻结，M3不得根据2025—2026/7标签修改。\n",
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
