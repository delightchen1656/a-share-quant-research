"""Count stocks by independent 10-trading-day / 50% rally frequency, 2018-2023."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
EVENT_FILE = OUT / "event_details.csv"
STOCK_FILE = OUT / "stock_event_counts.csv"
START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2023-12-31")
THRESHOLDS = (1, 3, 5, 10)


def main() -> None:
    if not EVENT_FILE.exists() or not STOCK_FILE.exists():
        raise FileNotFoundError(
            "请先运行 screen_events.py，生成 event_details.csv 和 stock_event_counts.csv"
        )

    events = pd.read_csv(EVENT_FILE, parse_dates=["start_date", "end_date"])
    stocks = pd.read_csv(STOCK_FILE, usecols=["market", "symbol"])
    stocks = stocks.drop_duplicates("symbol")

    # A qualifying episode must be wholly contained in the requested interval.
    selected = events[
        (events["start_date"] >= START) & (events["end_date"] <= END)
    ].copy()

    counts = (
        selected.groupby(["market", "symbol"], as_index=False)
        .size()
        .rename(columns={"size": "independent_event_count_2018_2023"})
    )
    per_stock = stocks.merge(counts, on=["market", "symbol"], how="left")
    per_stock["independent_event_count_2018_2023"] = (
        per_stock["independent_event_count_2018_2023"].fillna(0).astype(int)
    )
    per_stock = per_stock.sort_values(
        ["independent_event_count_2018_2023", "symbol"], ascending=[False, True]
    )

    summary_rows = []
    for threshold in THRESHOLDS:
        mask = per_stock["independent_event_count_2018_2023"] >= threshold
        row = {
            "threshold": f">={threshold}",
            "all_stocks": int(mask.sum()),
        }
        for market in sorted(per_stock["market"].unique()):
            row[market] = int((mask & (per_stock["market"] == market)).sum())
        summary_rows.append(row)
        per_stock.loc[mask].to_csv(
            OUT / f"stocks_with_at_least_{threshold}_events_2018_2023.csv",
            index=False,
            encoding="utf-8-sig",
        )

    summary = pd.DataFrame(summary_rows)
    per_stock.to_csv(
        OUT / "stock_event_frequency_2018_2023.csv", index=False, encoding="utf-8-sig"
    )
    summary.to_csv(
        OUT / "frequency_threshold_summary_2018_2023.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("口径：独立行情；行情起止均位于2018-01-01至2023-12-31")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
