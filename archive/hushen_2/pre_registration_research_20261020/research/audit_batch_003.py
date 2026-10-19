from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import audit_champion as prior_audit  # noqa: E402


PROJECT = core.PROJECT
RESULTS = PROJECT / "results" / "batch_003"
AUDIT = RESULTS / "audit"
EASTMONEY_ACTIONS = AUDIT / "eastmoney_actions.json"


def cross_time(row: dict) -> dict:
    returns = [float(row[f"return_{year}"]) for year in [2022, 2023, 2024]]
    growth = math.prod(1.0 + value for value in returns)
    return {
        "cumulative_2022_2024": growth - 1.0,
        "cagr_2022_2024": growth ** (1.0 / 3.0) - 1.0,
        "profitable_years_2022_2024": sum(value > 0 for value in returns),
    }


def load_actions():
    actions, known = prior_audit.load_actions()
    if not EASTMONEY_ACTIONS.exists():
        return actions, known
    supplement = json.loads(EASTMONEY_ACTIONS.read_text(encoding="utf-8")).get("records", {})
    merged = defaultdict(list, actions)
    for key, records in supplement.items():
        symbol = key.split("/")[0]
        known.add(key)
        for row in records:
            if not row.get("dividOperateDate"):
                continue
            date = pd.Timestamp(row["dividOperateDate"]).normalize()
            if date > core.HARD_MAX_DATE:
                continue
            merged[(date, symbol)].append({
                "cash": prior_audit.number(row.get("dividCashPsBeforeTax", 0)),
                "stock": prior_audit.number(row.get("dividStocksPs", 0)) + prior_audit.number(row.get("dividReserveToStockPs", 0)),
                "taxable_stock": prior_audit.number(row.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(row.get("dividPayDate") or row["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(row.get("dividStockMarketDate") or row["dividOperateDate"]).normalize(),
                "source": row.get("source", "Eastmoney stock_fhps_em via AkShare"),
            })
    return dict(merged), known


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    selection = json.loads((RESULTS / "SELECTION.json").read_text(encoding="utf-8"))
    candidates = [(label, value) for label, value in selection["winners"].items()]
    signals = pd.read_parquet(RESULTS / "signals_factor_grid.parquet")
    signals["date"] = pd.to_datetime(signals.date)
    factors = {str(candidate["factor"]) for _, candidate in candidates}
    signals = signals[signals.factor.isin(factors)].copy()
    bars, calendar, raw = prior_audit.load_raw_bars(set(signals.symbol.astype(str)))
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    signals = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if signals.raw_close.isna().any():
        raise RuntimeError("Missing raw signal-date close")
    signals = signals.rename(columns={"raw_close": "close"})
    actions, known_keys = load_actions()
    delistings = prior_audit.load_delistings()
    missing = set()
    audited = {}
    for label, candidate in candidates:
        row, trades = core.simulate(
            signals, bars, calendar, str(candidate["factor"]),
            float(candidate["entry_offset_atr"]), int(candidate["hold_calendar_days"]),
            str(candidate["exit_set"]), float(candidate["take_atr"]), float(candidate["stop_atr"]),
            keep_trades=True, actions=actions, known_action_keys=known_keys,
            coverage_sink=missing, delist_dates=delistings,
        )
        row["eligible_trade_count"] = all(row[f"trades_{year}"] >= 20 for year in core.YEARS)
        row["eligible_cross_year"] = row["profitable_years"] >= 3
        row["audit_passed"] = bool(row["eligible_trade_count"] and row["eligible_cross_year"] and row["open_positions_at_end"] == 0)
        row["cross_time"] = cross_time(row)
        row["formula"] = candidate["formula"]
        audited[label] = row
        trades.to_csv(AUDIT / f"trades_{label}_raw_action_audited.csv", index=False, encoding="utf-8-sig")
    if missing:
        gaps = [[key.split("/")[0], int(key.split("/")[1])] for key in sorted(missing)]
        (AUDIT / "action_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "action_data_required", "gap_count": len(gaps)}, ensure_ascii=False))
        return 2
    output = {
        "status": "complete",
        "separate_horizon_audits": audited,
        "known_action_stock_years": len(known_keys),
        "source_hashes": {
            "audit_batch_003.py": core.sha256(Path(__file__)),
            "run_batch.py": core.sha256(HERE / "run_batch.py"),
            "run_batch_003.py": core.sha256(HERE / "run_batch_003.py"),
            "BATCH_003.json": core.sha256(PROJECT / "protocol" / "BATCH_003.json"),
            "eastmoney_actions_batch002.json": core.sha256(prior_audit.EASTMONEY_ACTIONS),
            "eastmoney_actions_batch003.json": core.sha256(EASTMONEY_ACTIONS),
        },
        "post_2024_access": False,
        "production_change": False,
        "notes": [
            "Raw unadjusted OHLC drives fills and exits; QFQ data is used only for causal signal features.",
            "Corporate actions use the previously audited Baostock/Eastmoney stock-year response set.",
            "Historical level-2 depth is unavailable; orders not above 2% of daily volume are assumed fully filled with 0.2% one-side slippage.",
            "The H component is a Hushen-1 formula transplant into the Smart-1 eligible pool, not a replay of the Hushen-1 account.",
        ],
    }
    (AUDIT / "FINAL_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
