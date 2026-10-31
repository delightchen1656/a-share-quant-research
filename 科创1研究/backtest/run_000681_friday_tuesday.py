"""Close-to-close timing study for 000681.SH.

Rule: buy at an observed Friday close and sell at the first available close on
or after the following calendar Tuesday.  While a position is open no second
entry is allowed.  This is an index timing study, not an executable product
backtest, and deliberately excludes fees and tracking error.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
INPUT = (
    ROOT
    / "archive/legacy_layout/strategies"
    / "kechuang"
    / "backtest"
    / "data"
    / "benchmark"
    / "000681.SH.parquet"
)
OUTPUT = (
    ROOT
    / "archive/legacy_layout/strategies"
    / "kechuang"
    / "results"
    / "000681_friday_close_to_tuesday_close"
)


def build_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DatetimeIndex(frame["date"])
    rows: list[dict] = []
    last_exit = pd.Timestamp.min
    for entry in dates[dates.weekday == 4]:
        if entry <= last_exit:
            continue
        target_tuesday = entry + pd.Timedelta(days=4)
        eligible = dates[dates >= target_tuesday]
        if eligible.empty:
            continue
        exit_date = eligible[0]
        rows.append({"entry_date": entry, "exit_date": exit_date})
        last_exit = exit_date
    return pd.DataFrame(rows)


def max_drawdown(values: pd.Series, opening_value: float) -> float:
    path = pd.concat(
        [pd.Series([opening_value], index=[values.index.min() - pd.Timedelta(days=1)]), values]
    )
    return float((path / path.cummax() - 1.0).min())


def main() -> None:
    frame = pd.read_parquet(INPUT).sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    schedule = build_schedule(frame.reset_index())

    position_for_return = pd.Series(0.0, index=frame.index)
    trade_rows: list[dict] = []
    for row in schedule.itertuples(index=False):
        mask = (frame.index > row.entry_date) & (frame.index <= row.exit_date)
        position_for_return.loc[mask] = 1.0
        entry_close = float(frame.at[row.entry_date, "close"])
        exit_close = float(frame.at[row.exit_date, "close"])
        trade_rows.append(
            {
                "entry_date": row.entry_date,
                "exit_date": row.exit_date,
                "entry_close": entry_close,
                "exit_close": exit_close,
                "return": exit_close / entry_close - 1.0,
                "holding_calendar_days": int((row.exit_date - row.entry_date).days),
            }
        )

    close_return = frame["close"].pct_change().fillna(0.0)
    strategy_return = close_return * position_for_return
    equity = (1.0 + strategy_return).cumprod()
    daily = pd.DataFrame(
        {
            "close": frame["close"],
            "position_for_return": position_for_return,
            "strategy_return": strategy_return,
            "equity": equity,
        }
    )
    trades = pd.DataFrame(trade_rows)

    annual_rows: list[dict] = []
    for year, group in daily.groupby(daily.index.year):
        first_date = group.index.min()
        prior = daily.loc[daily.index < first_date, "equity"]
        opening = float(prior.iloc[-1]) if not prior.empty else 1.0
        annual_return = float(group["equity"].iloc[-1] / opening - 1.0)
        annual_trades = trades[pd.to_datetime(trades["entry_date"]).dt.year == year]
        annual_rows.append(
            {
                "year": int(year),
                "start_date": str(first_date.date()),
                "end_date": str(group.index.max().date()),
                "return": annual_return,
                "max_drawdown": max_drawdown(group["equity"], opening),
                "trades": int(len(annual_trades)),
                "win_rate": float((annual_trades["return"] > 0).mean())
                if not annual_trades.empty
                else np.nan,
            }
        )

    annual = pd.DataFrame(annual_rows)
    total_return = float(equity.iloc[-1] - 1.0)
    total_mdd = float((equity / equity.cummax() - 1.0).min())
    years = (daily.index.max() - daily.index.min()).days / 365.25
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0)
    summary = {
        "index": "000681.SH",
        "rule": "Friday close buy; first available close on/after next Tuesday sell",
        "costs": "none",
        "start": str(daily.index.min().date()),
        "end": str(daily.index.max().date()),
        "trades": int(len(trades)),
        "win_rate": float((trades["return"] > 0).mean()),
        "total_return": total_return,
        "cagr": cagr,
        "max_drawdown": total_mdd,
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    annual.to_csv(OUTPUT / "annual_metrics.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(OUTPUT / "trades.csv", index=False, encoding="utf-8-sig")
    daily.reset_index().to_parquet(OUTPUT / "daily_equity.parquet", index=False)
    (OUTPUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(annual.to_string(index=False))


if __name__ == "__main__":
    main()
