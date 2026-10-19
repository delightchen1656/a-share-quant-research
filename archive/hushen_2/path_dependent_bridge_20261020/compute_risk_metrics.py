from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
STRATEGY = HERE.parent
ROOT = STRATEGY.parents[1]
SOURCE = (
    ROOT
    / "archive"
    / "hushen_2"
    / "pre_registration_research_20261020"
    / "results"
    / "holdout_restricted"
    / "seven_versions_four_extra_rows"
    / "posterior_old_new"
    / "run_audit.py"
)
RESULTS = STRATEGY / "results"
CANDIDATE = "C04_NEW"
END = pd.Timestamp("2026-10-19")
LAST_SIGNAL = END - pd.Timedelta(days=37)
INITIAL_CASH = 100_000.0
SLOTS = 5


def load_module():
    spec = importlib.util.spec_from_file_location("hushen2_audit_source", SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def aggregate_parts() -> None:
    parts = RESULTS / "parts"
    metric_files = sorted(parts.glob("metrics_*.csv"))
    curve_files = sorted(parts.glob("curves_*.parquet"))
    metrics = pd.concat([pd.read_csv(path) for path in metric_files], ignore_index=True).sort_values("start_ordinal")
    all_curves = pd.concat([pd.read_parquet(path) for path in curve_files], ignore_index=True)
    if metrics.start_ordinal.tolist() != list(range(1, 59)):
        raise RuntimeError(f"incomplete or duplicate metric parts: {metrics.start_ordinal.tolist()}")
    earliest = metrics.iloc[0]
    summary = {
        "status": "complete", "strategy": "沪深2", "candidate": CANDIDATE, "slots": SLOTS,
        "window": {"start_population": "all 58 Shanghai Composite Q1-2020 sessions", "end": str(END.date())},
        "definitions": {
            "maximum_drawdown": "minimum of daily close equity / prior daily close equity peak - 1",
            "sharpe": "sqrt(252) * mean(daily account return) / population_std(daily account return), risk_free_rate=0",
            "annualized_return": "(ending_equity/100000)^(365/calendar_days)-1",
        },
        "all_start_mean": {
            "annualized_return": float(metrics.annualized_return.mean()),
            "maximum_drawdown": float(metrics.maximum_drawdown.mean()),
            "sharpe": float(metrics.sharpe_zero_rf_252_ddof0.mean()),
        },
        "all_start_median": {
            "annualized_return": float(metrics.annualized_return.median()),
            "maximum_drawdown": float(metrics.maximum_drawdown.median()),
            "sharpe": float(metrics.sharpe_zero_rf_252_ddof0.median()),
        },
        "earliest_start": {
            "start_date": str(earliest.start_date), "annualized_return": float(earliest.annualized_return),
            "maximum_drawdown": float(earliest.maximum_drawdown), "sharpe": float(earliest.sharpe_zero_rf_252_ddof0),
        },
        "assertions": {
            "runs_58": len(metrics) == 58,
            "all_terminal_empty": bool(metrics.open_positions_at_end.eq(0).all() and metrics.pending_orders_at_end.eq(0).all()),
            "action_coverage_complete": bool(metrics.action_gap_count.eq(0).all()),
        },
    }
    if not all(summary["assertions"].values()):
        raise RuntimeError(f"aggregate audit failure: {summary['assertions']}")
    metrics.to_csv(RESULTS / "RISK_METRICS_2020Q1_STARTS_TO_20261019.csv", index=False, encoding="utf-8-sig")
    all_curves.to_parquet(RESULTS / "EQUITY_CURVES_2020Q1_STARTS_TO_20261019.parquet", index=False)
    (RESULTS / "RISK_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-from", type=int, default=1)
    parser.add_argument("--start-to", type=int, default=58)
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    if args.aggregate_only:
        aggregate_parts()
        return
    if not (1 <= args.start_from <= args.start_to <= 58):
        raise ValueError("chunk bounds must satisfy 1 <= start-from <= start-to <= 58")
    audit = load_module()
    expected = audit.validate_sources()
    item = expected[CANDIDATE]
    signals = audit.candidate_signals(CANDIDATE, item)
    bars, calendar, raw = audit.load_raw(set(signals.symbol.astype(str)))
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    signals = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if signals.raw_close.isna().any():
        raise RuntimeError("raw close gap")
    signals = signals.rename(columns={"raw_close": "close"})
    actions, known, _ = audit.load_actions()
    delistings = audit.load_delistings()
    index = pd.read_parquet(audit.INDEX_PATH)
    index["date"] = pd.to_datetime(index.date).dt.normalize()
    all_starts = index.loc[index.date.between(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-03-31")), "date"].drop_duplicates().tolist()
    if len(all_starts) != 58:
        raise RuntimeError(f"start population changed: {len(all_starts)}")
    starts = list(enumerate(all_starts, 1))[args.start_from - 1:args.start_to]

    rows, curves, all_gaps = [], [], set()
    selected_all = signals[signals.date.le(LAST_SIGNAL)].copy()
    for ordinal, start_value in starts:
        start = pd.Timestamp(start_value)
        selected = selected_all[selected_all.date.ge(start)].copy()
        curve_sink: list[dict] = []
        gaps: set[str] = set()
        old = (audit.core.EVAL_START, audit.core.HARD_MAX_DATE, audit.core.LAST_SIGNAL_DATE, audit.core.YEARS)
        try:
            audit.core.EVAL_START, audit.core.HARD_MAX_DATE, audit.core.LAST_SIGNAL_DATE = start, END, LAST_SIGNAL
            audit.core.YEARS = list(range(2020, END.year + 1))
            run, _ = audit.core.simulate(
                selected, bars, calendar, CANDIDATE, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
                actions=actions, known_action_keys=known, coverage_sink=gaps,
                delist_dates=delistings, slots=SLOTS, equity_curve_sink=curve_sink,
            )
        finally:
            audit.core.EVAL_START, audit.core.HARD_MAX_DATE, audit.core.LAST_SIGNAL_DATE, audit.core.YEARS = old
        all_gaps.update(gaps)
        curve = pd.DataFrame(curve_sink)
        if curve.empty or curve.date.iloc[0] != start or curve.date.iloc[-1] != END:
            raise RuntimeError(f"curve boundary mismatch: {start.date()}")
        equity = curve.equity.astype(float)
        daily_returns = equity.pct_change().fillna(equity.iloc[0] / INITIAL_CASH - 1.0)
        daily_std = float(daily_returns.std(ddof=0))
        sharpe = float(np.sqrt(252.0) * daily_returns.mean() / daily_std) if daily_std > 0 else math.nan
        drawdown = equity / equity.cummax() - 1.0
        day_span = int((END - start).days)
        cumulative = float(equity.iloc[-1] / INITIAL_CASH - 1.0)
        annualized = float((1.0 + cumulative) ** (365.0 / day_span) - 1.0)
        rows.append({
            "start_ordinal": ordinal, "start_date": str(start.date()), "end_date": str(END.date()),
            "calendar_day_span": day_span, "trading_days": int(len(curve)),
            "cumulative_return": cumulative, "annualized_return": annualized,
            "maximum_drawdown": float(drawdown.min()), "sharpe_zero_rf_252_ddof0": sharpe,
            "completed_trades": int(run["completed_trades"]),
            "open_positions_at_end": int(run["open_positions_at_end"]),
            "pending_orders_at_end": int(run["pending_orders_at_end"]),
            "action_gap_count": len(gaps),
        })
        curve["start_ordinal"] = ordinal
        curve["start_date"] = str(start.date())
        curve["daily_return"] = daily_returns.to_numpy()
        curve["drawdown"] = drawdown.to_numpy()
        curves.append(curve)
        print(f"risk path {ordinal}/58", flush=True)

    metrics = pd.DataFrame(rows)
    all_curves = pd.concat(curves, ignore_index=True)
    if all_gaps or not metrics.open_positions_at_end.eq(0).all() or not metrics.pending_orders_at_end.eq(0).all():
        raise RuntimeError(f"audit failure: gaps={sorted(all_gaps)}")
    parts = RESULTS / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    suffix = f"{args.start_from:02d}_{args.start_to:02d}"
    metrics.to_csv(parts / f"metrics_{suffix}.csv", index=False, encoding="utf-8-sig")
    all_curves.to_parquet(parts / f"curves_{suffix}.parquet", index=False)
    print(json.dumps({"status": "chunk_complete", "from": args.start_from, "to": args.start_to, "runs": len(metrics)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
