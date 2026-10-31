"""从冻结日权益曲线独立复算沪深2风险指标。

本脚本不加载归档研究、不生成信号，也不重跑账户。它只验证当前保留的58组
日权益曲线、逐起点指标与汇总JSON相互一致。
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
CURVES_PATH = RESULTS / "EQUITY_CURVES_2020Q1_STARTS_TO_20261019.parquet"
METRICS_PATH = RESULTS / "RISK_METRICS_2020Q1_STARTS_TO_20261019.csv"
SUMMARY_PATH = RESULTS / "RISK_SUMMARY.json"
INITIAL_CASH = 100_000.0
EXPECTED_RUNS = 58


def recompute_metrics(curves: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "equity", "start_ordinal", "start_date"}
    missing = required.difference(curves.columns)
    if missing:
        raise RuntimeError(f"equity curve columns missing: {sorted(missing)}")
    work = curves.copy()
    work["date"] = pd.to_datetime(work.date).dt.normalize()
    rows: list[dict] = []
    for ordinal, frame in work.groupby("start_ordinal", sort=True):
        frame = frame.sort_values("date", kind="stable")
        if frame.date.duplicated().any():
            raise RuntimeError(f"duplicate curve date: start_ordinal={ordinal}")
        start_values = pd.to_datetime(frame.start_date).dt.normalize().unique()
        if len(start_values) != 1:
            raise RuntimeError(f"inconsistent start date: start_ordinal={ordinal}")
        start = pd.Timestamp(start_values[0])
        end = pd.Timestamp(frame.date.iloc[-1])
        if frame.date.iloc[0] != start:
            raise RuntimeError(f"curve does not begin on start date: start_ordinal={ordinal}")
        equity = frame.equity.astype(float)
        if not np.isfinite(equity).all() or equity.le(0).any():
            raise RuntimeError(f"invalid equity: start_ordinal={ordinal}")
        daily_returns = equity.pct_change().fillna(equity.iloc[0] / INITIAL_CASH - 1.0)
        daily_std = float(daily_returns.std(ddof=0))
        sharpe = (
            float(np.sqrt(252.0) * daily_returns.mean() / daily_std)
            if daily_std > 0
            else math.nan
        )
        cumulative = float(equity.iloc[-1] / INITIAL_CASH - 1.0)
        day_span = int((end - start).days)
        annualized = float((1.0 + cumulative) ** (365.0 / day_span) - 1.0)
        rows.append(
            {
                "start_ordinal": int(ordinal),
                "start_date": str(start.date()),
                "end_date": str(end.date()),
                "calendar_day_span": day_span,
                "trading_days": int(len(frame)),
                "cumulative_return": cumulative,
                "annualized_return": annualized,
                "maximum_drawdown": float((equity / equity.cummax() - 1.0).min()),
                "sharpe_zero_rf_252_ddof0": sharpe,
            }
        )
    return pd.DataFrame(rows).sort_values("start_ordinal").reset_index(drop=True)


def verify_metrics(calculated: pd.DataFrame, stored: pd.DataFrame) -> pd.DataFrame:
    stored = stored.sort_values("start_ordinal").reset_index(drop=True)
    expected_ordinals = list(range(1, EXPECTED_RUNS + 1))
    if calculated.start_ordinal.tolist() != expected_ordinals:
        raise RuntimeError("equity curves do not contain exactly 58 ordered starts")
    if stored.start_ordinal.tolist() != expected_ordinals:
        raise RuntimeError("stored metrics do not contain exactly 58 ordered starts")
    exact_columns = ["start_ordinal", "start_date", "end_date", "calendar_day_span", "trading_days"]
    for column in exact_columns:
        if calculated[column].astype(str).tolist() != stored[column].astype(str).tolist():
            raise RuntimeError(f"stored metric mismatch: {column}")
    numeric_columns = [
        "cumulative_return",
        "annualized_return",
        "maximum_drawdown",
        "sharpe_zero_rf_252_ddof0",
    ]
    for column in numeric_columns:
        if not np.allclose(
            calculated[column].to_numpy(float),
            stored[column].to_numpy(float),
            rtol=0.0,
            atol=1e-12,
            equal_nan=True,
        ):
            delta = float(np.nanmax(np.abs(calculated[column] - stored[column])))
            raise RuntimeError(f"stored metric mismatch: {column}, max_delta={delta}")
    operational = ["completed_trades", "open_positions_at_end", "pending_orders_at_end", "action_gap_count"]
    if any(column not in stored for column in operational):
        raise RuntimeError("stored operational audit columns are incomplete")
    return stored


def build_summary(calculated: pd.DataFrame, stored: pd.DataFrame) -> dict:
    earliest = calculated.iloc[0]
    return {
        "status": "complete",
        "strategy": "沪深2",
        "candidate": "C04_NEW",
        "slots": 5,
        "window": {
            "start_population": "all 58 Shanghai Composite Q1-2020 sessions",
            "end": str(calculated.end_date.iloc[-1]),
        },
        "definitions": {
            "maximum_drawdown": "minimum of daily close equity / prior daily close equity peak - 1",
            "sharpe": "sqrt(252) * mean(daily account return) / population_std(daily account return), risk_free_rate=0",
            "annualized_return": "(ending_equity/100000)^(365/calendar_days)-1",
        },
        "all_start_mean": {
            "annualized_return": float(calculated.annualized_return.mean()),
            "maximum_drawdown": float(calculated.maximum_drawdown.mean()),
            "sharpe": float(calculated.sharpe_zero_rf_252_ddof0.mean()),
        },
        "all_start_median": {
            "annualized_return": float(calculated.annualized_return.median()),
            "maximum_drawdown": float(calculated.maximum_drawdown.median()),
            "sharpe": float(calculated.sharpe_zero_rf_252_ddof0.median()),
        },
        "earliest_start": {
            "start_date": str(earliest.start_date),
            "annualized_return": float(earliest.annualized_return),
            "maximum_drawdown": float(earliest.maximum_drawdown),
            "sharpe": float(earliest.sharpe_zero_rf_252_ddof0),
        },
        "assertions": {
            "runs_58": len(calculated) == EXPECTED_RUNS,
            "all_terminal_empty": bool(
                stored.open_positions_at_end.eq(0).all()
                and stored.pending_orders_at_end.eq(0).all()
            ),
            "action_coverage_complete": bool(stored.action_gap_count.eq(0).all()),
        },
    }


def compare_nested(actual, expected, path: str = "root") -> None:
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise RuntimeError(f"summary keys changed at {path}")
        for key, value in expected.items():
            compare_nested(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, float):
        if not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(f"summary value mismatch at {path}")
    elif actual != expected:
        raise RuntimeError(f"summary value mismatch at {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute Hushen 2 risk metrics from frozen equity curves.")
    parser.add_argument("--write-summary", action="store_true")
    args = parser.parse_args()
    curves = pd.read_parquet(CURVES_PATH)
    stored_metrics = pd.read_csv(METRICS_PATH)
    calculated = recompute_metrics(curves)
    stored_metrics = verify_metrics(calculated, stored_metrics)
    summary = build_summary(calculated, stored_metrics)
    if not all(summary["assertions"].values()):
        raise RuntimeError(f"operational audit assertion failed: {summary['assertions']}")
    previous = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    compare_nested(summary, previous)
    if args.write_summary:
        SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"status": "ok", "strategy": "沪深2", "runs": len(calculated), "archive_dependency": False},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
