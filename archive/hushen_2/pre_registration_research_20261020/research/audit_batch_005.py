from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import audit_batch_004 as batch4_audit  # noqa: E402


RESULTS = core.PROJECT / "results" / "batch_005_pre2025_signal_filters"
AUDIT = RESULTS / "audit"
BATCH4_RESULTS = core.PROJECT / "results" / "batch_004_pre2025_factor_tuning"
PROTOCOL = core.PROJECT / "protocol" / "BATCH_005.json"
BATCH5_ACTIONS = AUDIT / "eastmoney_actions.json"


def load_actions():
    actions, known = batch4_audit.load_actions()
    supplement = json.loads(BATCH5_ACTIONS.read_text(encoding="utf-8")).get("records", {})
    merged = defaultdict(list, actions)
    for key, records in supplement.items():
        symbol = key.split("/")[0]
        known.add(key)
        for item in records:
            if not item.get("dividOperateDate"):
                continue
            date = pd.Timestamp(item["dividOperateDate"]).normalize()
            if date > core.HARD_MAX_DATE:
                continue
            merged[(date, symbol)].append({
                "cash": prior_audit.number(item.get("dividCashPsBeforeTax", 0)),
                "stock": prior_audit.number(item.get("dividStocksPs", 0)) + prior_audit.number(item.get("dividReserveToStockPs", 0)),
                "taxable_stock": prior_audit.number(item.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(item.get("dividPayDate") or item["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(item.get("dividStockMarketDate") or item["dividOperateDate"]).normalize(),
                "source": item.get("source", "Eastmoney stock_fhps_em via AkShare"),
            })
    return dict(merged), known


def identical_batch4_count_signals(count_signals: pd.DataFrame) -> bool:
    prior = pd.read_parquet(BATCH4_RESULTS / "champion_signals_screening.parquet")
    columns = ["date", "symbol", "close", "atr_pct", "score"]
    left = count_signals[columns].copy().sort_values(["date", "score", "symbol"], ascending=[True, False, True]).reset_index(drop=True)
    right = prior[columns].copy().sort_values(["date", "score", "symbol"], ascending=[True, False, True]).reset_index(drop=True)
    left["date"] = pd.to_datetime(left.date)
    right["date"] = pd.to_datetime(right.date)
    return left.equals(right)


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    selection = json.loads((RESULTS / "SELECTION.json").read_text(encoding="utf-8"))
    candidates = {
        "count_only": selection["count_only"]["winner"],
        "threshold_only": selection["threshold_only"]["winner"],
    }
    signal_frames = {
        label: pd.read_parquet(RESULTS / f"{label}_champion_signals_screening.parquet")
        for label in candidates
    }
    for signals in signal_frames.values():
        signals["date"] = pd.to_datetime(signals.date)
        if signals.empty or signals.date.max() > pd.Timestamp("2024-11-22"):
            raise RuntimeError("Champion signal boundary failed")
    count_reproduces_batch4 = identical_batch4_count_signals(signal_frames["count_only"])
    if not count_reproduces_batch4:
        raise RuntimeError("Count-only K3 signals do not reproduce the frozen Batch004 champion")

    symbols = set().union(*(set(frame.symbol.astype(str)) for frame in signal_frames.values()))
    bars, calendar, raw = prior_audit.load_raw_bars(symbols)
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Raw audit bars cross 2024-12-31")
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    actions, known_keys = load_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    audited = {}
    for label, candidate in candidates.items():
        signals = signal_frames[label].drop(columns=["close"]).merge(
            raw_close, on=["date", "symbol"], how="left", validate="many_to_one"
        )
        if signals.raw_close.isna().any():
            raise RuntimeError(f"Missing raw signal-date close for {label}")
        signals = signals.rename(columns={"raw_close": "close"})
        row, trades = core.simulate(
            signals, bars, calendar, str(candidate["factor"]),
            0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=True, actions=actions, known_action_keys=known_keys,
            coverage_sink=missing, delist_dates=delistings,
        )
        row["eligible_trade_count"] = all(row[f"trades_{year}"] >= 20 for year in core.YEARS)
        row["eligible_cross_year"] = row["profitable_years"] >= 3
        row["audit_passed"] = bool(row["eligible_trade_count"] and row["eligible_cross_year"] and row["open_positions_at_end"] == 0)
        row["winning_spec"] = selection[label]["winning_spec"]
        audited[label] = row
        trades.to_csv(AUDIT / f"{label}_champion_trades_raw_action_audited.csv", index=False, encoding="utf-8-sig")
    if missing:
        gaps = [[key.split("/")[0], int(key.split("/")[1])] for key in sorted(missing)]
        (AUDIT / "action_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "action_data_required", "gap_count": len(gaps)}, ensure_ascii=False))
        return 2

    all_passed = all(row["audit_passed"] for row in audited.values())
    output = {
        "status": "complete" if all_passed else "audit_failed",
        "separate_experiment_audits": audited,
        "known_action_stock_years": len(known_keys),
        "source_hashes": {
            "audit_batch_005.py": core.sha256(Path(__file__)),
            "run_batch_005.py": core.sha256(HERE / "run_batch_005.py"),
            "run_batch.py": core.sha256(HERE / "run_batch.py"),
            "BATCH_005.json": core.sha256(PROTOCOL),
            "SELECTION.json": core.sha256(RESULTS / "SELECTION.json"),
            "count_only_champion_signals_screening.parquet": core.sha256(RESULTS / "count_only_champion_signals_screening.parquet"),
            "threshold_only_champion_signals_screening.parquet": core.sha256(RESULTS / "threshold_only_champion_signals_screening.parquet"),
            "batch004_champion_signals_screening.parquet": core.sha256(BATCH4_RESULTS / "champion_signals_screening.parquet"),
            "actions_base": core.sha256(prior_audit.ACTIONS_BASE),
            "eastmoney_actions_batch002.json": core.sha256(prior_audit.EASTMONEY_ACTIONS),
            "eastmoney_actions_batch003.json": core.sha256(HERE.parent / "results" / "batch_003" / "audit" / "eastmoney_actions.json"),
            "eastmoney_actions_batch004.json": core.sha256(batch4_audit.EASTMONEY_ACTIONS),
            "eastmoney_actions_batch005.json": core.sha256(BATCH5_ACTIONS),
        },
        "assertions": {
            "post_2024_access": False,
            "maximum_signal_date": str(max(frame.date.max() for frame in signal_frames.values()).date()),
            "maximum_raw_bar_date": str(max(calendar).date()),
            "corporate_action_coverage_complete": True,
            "both_experiment_champions_audited": len(audited) == 2,
            "both_champions_pass_trade_and_profitable_year_eligibility": all_passed,
            "no_open_positions_at_end": all(row["open_positions_at_end"] == 0 for row in audited.values()),
            "count_only_k3_signals_identical_to_batch004": count_reproduces_batch4,
            "grid_expanded": False,
            "production_change": False,
        },
        "notes": [
            "Raw unadjusted OHLC drives fills and exits; QFQ data is used only for causal signal features.",
            "Cash dividends, bonus shares, transfer shares and pre-2025 delistings use the previously audited Batch004 action set.",
            "The 2% daily-volume full-fill approximation, fees, slippage, T+1, stop-first double touch, seven-calendar-day buy lifetime and 30-calendar-day holding horizon are unchanged.",
            "All 2020-2024 results are development results and are not blind or holdout evidence."
        ],
    }
    (AUDIT / "FINAL_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
