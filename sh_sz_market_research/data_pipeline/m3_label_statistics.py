"""M3: compute 40/60 trading-day +30% labels without fitting any model."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "outputs" / "m3_labels"
LABEL_DIR = DATA / "derived" / "labels"


def future_max(series: pd.Series, horizon: int) -> pd.Series:
    return series.shift(-1).iloc[::-1].rolling(horizon, min_periods=horizon).max().iloc[::-1]


def one_symbol(symbol: str):
    exchange = symbol[-2:]
    qfq = pd.read_parquet(DATA / "qfq" / exchange / f"{symbol}.parquet",
                          columns=["date", "close", "high"])
    raw = pd.read_parquet(DATA / "raw" / exchange / f"{symbol}.parquet",
                          columns=["date", "high", "low", "pctChg", "tradestatus"])
    pools = pd.read_parquet(DATA / "derived" / "pools" / exchange / f"{symbol}.parquet",
                            columns=["date", "pool_a", "pool_b", "pool_c"])
    qfq = qfq.sort_values("date").reset_index(drop=True)
    raw = raw.sort_values("date").reset_index(drop=True)
    frame = qfq.merge(pools, on="date", how="left").merge(
        raw.rename(columns={"high": "raw_high", "low": "raw_low", "pctChg": "raw_pctChg",
                            "tradestatus": "raw_tradestatus"}), on="date", how="left")
    for horizon in (40, 60):
        highest = future_max(frame.high.astype(float), horizon)
        frame[f"label{horizon}"] = np.where(highest.notna(), highest / frame.close.astype(float) - 1 >= .30, np.nan)
    next_status = frame.raw_tradestatus.shift(-1).astype(str)
    next_one_price_up = (frame.raw_high.shift(-1).eq(frame.raw_low.shift(-1)) &
                         frame.raw_pctChg.shift(-1).astype(float).ge(9.5))
    frame["t1_buyable"] = next_status.eq("1") & ~next_one_price_up
    frame["symbol"], frame["exchange"] = symbol, exchange
    target = LABEL_DIR / exchange / f"{symbol}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    keep = ["date", "symbol", "exchange", "label40", "label60", "t1_buyable",
            "pool_a", "pool_b", "pool_c"]
    frame[keep].to_parquet(target, index=False)
    stats = []
    frame["year"] = pd.to_datetime(frame.date).dt.year
    for pool_name in ("pool_a", "pool_b", "pool_c"):
        selected = frame[frame[pool_name].fillna(False)]
        for horizon in (40, 60):
            label = f"label{horizon}"
            valid = selected.dropna(subset=[label])
            for year, part in valid.groupby("year"):
                positives = part[label].astype(bool)
                stats.append({"year": int(year), "exchange": exchange, "pool": pool_name,
                              "horizon": horizon, "samples": int(len(part)),
                              "positives": int(positives.sum()),
                              "positive_unbuyable": int((positives & ~part.t1_buyable).sum())})
    return stats


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(DATA / "metadata" / "historical_mainboard_universe.csv",
                           dtype=str, encoding="utf-8-sig")
    symbols = universe.symbol.drop_duplicates().sort_values().tolist()
    rows = []
    print(f"M3 labels: {len(symbols)} stocks", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, stats in enumerate(pool.map(one_symbol, symbols), 1):
            rows.extend(stats)
            if i % 250 == 0:
                print(f"[{i}/{len(symbols)}] {i/len(symbols):.1%}", flush=True)
    detail = pd.DataFrame(rows)
    grouped = detail.groupby(["year", "exchange", "pool", "horizon"], as_index=False).sum(numeric_only=True)
    grouped["positive_rate"] = grouped.positives / grouped.samples
    grouped["positive_unbuyable_rate"] = grouped.positive_unbuyable / grouped.positives.replace(0, np.nan)
    grouped.to_csv(OUT / "year_exchange_pool_labels.csv", index=False, encoding="utf-8-sig")
    total = grouped.groupby(["pool", "horizon"], as_index=False)[["samples", "positives", "positive_unbuyable"]].sum()
    total["positive_rate"] = total.positives / total.samples
    total["positive_unbuyable_rate"] = total.positive_unbuyable / total.positives.replace(0, np.nan)
    total.to_csv(OUT / "overall_label_statistics.csv", index=False, encoding="utf-8-sig")
    summary = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "stocks": len(symbols), "rows": total.to_dict("records"),
               "test_period_not_used_for_selection": True}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# M3 暴涨标签统计", "", "未来40/60个交易日最高价相对信号日收盘上涨至少30%。", "",
             "| 股票池 | 期限 | 样本数 | 正样本 | 正样本率 | 正样本T+1不可买 |",
             "|---|---:|---:|---:|---:|---:|"]
    for row in total.itertuples():
        lines.append(f"| {row.pool} | {row.horizon}日 | {row.samples:,} | {row.positives:,} | {row.positive_rate:.2%} | {row.positive_unbuyable_rate:.2%} |")
    lines += ["", "本表是标签描述，不是模型成绩。2025—2026/7标签只用于最终锁定测试，不参与池或阈值选择。"]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(total.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
