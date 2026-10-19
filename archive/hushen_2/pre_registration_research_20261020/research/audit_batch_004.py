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
import run_batch_004 as batch4  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import audit_batch_003 as batch3_audit  # noqa: E402


RESULTS = core.PROJECT / "results" / "batch_004_pre2025_factor_tuning"
AUDIT = RESULTS / "audit"
EASTMONEY_ACTIONS = AUDIT / "eastmoney_actions.json"


def subperiod(row: dict) -> dict:
    values = [float(row[f"return_{year}"]) for year in [2022, 2023, 2024]]
    growth = math.prod(1.0 + value for value in values)
    return {
        "cumulative_return_2022_2024": growth - 1.0,
        "cagr_2022_2024": growth ** (1.0 / 3.0) - 1.0,
        "profitable_years_2022_2024": sum(value > 0 for value in values),
    }


def load_actions():
    actions, known = batch3_audit.load_actions()
    if not EASTMONEY_ACTIONS.exists():
        return actions, known
    supplement = json.loads(EASTMONEY_ACTIONS.read_text(encoding="utf-8")).get("records", {})
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


def report(selection: dict, audited: dict) -> str:
    spec = selection["champion_spec"]
    annual = "\n".join(
        f"| {year} | {audited[f'return_{year}']:.4%} | {int(audited[f'trades_{year}'])} |"
        for year in core.YEARS
    )
    boundary = selection["champion_on_grid_boundary"]
    return f"""# Batch 004 pre-2025 factor tuning

This was a preregistered 151-run sequential development batch. All 2020-2024 results, including 2022-2024, are development results rather than blind or holdout evidence. No grid was expanded and no production selection was changed.

## Audited champion

- Candidate: `{selection['champion']['candidate']}`
- M internal weights (utility, pen025, pen100): `{spec['M_internal']}`
- T internal weights (+mom120, +close/high60, +mom20, -vol60): `{spec['T_internal']}`
- H internal weights (-size, -vol60, +overnight, -intraday): `{spec['H_internal']}`
- Outer weights (M, T, H): `{spec['outer']}`
- CAGR: {audited['cagr']:.4%}
- Final equity: {audited['final_equity']:.2f}
- Worst annual return: {audited['worst_annual_return']:.4%}
- Profitable years: {audited['profitable_years']}
- Completed trades: {audited['completed_trades']}
- 2022-2024 development CAGR: {audited['subperiod_2022_2024']['cagr_2022_2024']:.4%}
- Grid-boundary flags (reported only; no expansion): `{boundary}`

| Development year | Audited return | Completed trades |
|---:|---:|---:|
{annual}

The audit used raw unadjusted OHLC for fills/exits and applied the existing pre-2025 corporate-action and delisting records. The 2% daily-volume full-fill approximation, fees, slippage, T+1 rule, stop-first double-touch rule, seven-calendar-day buy lifetime, and 30-calendar-day holding horizon remained unchanged.
"""


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    selection = json.loads((RESULTS / "SELECTION.json").read_text(encoding="utf-8"))
    champion = selection["champion"]
    signals = pd.read_parquet(RESULTS / "champion_signals_screening.parquet")
    signals["date"] = pd.to_datetime(signals.date)
    if signals.date.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Champion signals cross the pre-2025 outcome boundary")
    by_symbol, calendar, raw = prior_audit.load_raw_bars(set(signals.symbol.astype(str)))
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Raw audit bars cross 2024-12-31")
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    signals = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if signals.raw_close.isna().any():
        raise RuntimeError("Missing raw signal-date close")
    signals = signals.rename(columns={"raw_close": "close"})
    actions, known_keys = load_actions()
    missing: set[str] = set()
    row, trades = core.simulate(
        signals, by_symbol, calendar, str(champion["candidate"]),
        0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known_keys,
        coverage_sink=missing, delist_dates=prior_audit.load_delistings(),
    )
    if missing:
        gaps = [[key.split("/")[0], int(key.split("/")[1])] for key in sorted(missing)]
        (AUDIT / "action_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "action_data_required", "gap_count": len(gaps)}, ensure_ascii=False))
        return 2
    row["eligible_trade_count"] = all(row[f"trades_{year}"] >= 20 for year in core.YEARS)
    row["eligible_cross_year"] = row["profitable_years"] >= 3
    row["audit_passed"] = bool(row["eligible_trade_count"] and row["eligible_cross_year"] and row["open_positions_at_end"] == 0)
    row["subperiod_2022_2024"] = subperiod(row)
    trades.to_csv(AUDIT / "champion_trades_raw_action_audited.csv", index=False, encoding="utf-8-sig")
    hashes = {
        "audit_batch_004.py": core.sha256(Path(__file__)),
        "run_batch_004.py": core.sha256(HERE / "run_batch_004.py"),
        "run_batch.py": core.sha256(HERE / "run_batch.py"),
        "fetch_actions_eastmoney.py": core.sha256(HERE / "fetch_actions_eastmoney.py"),
        "BATCH_004.json": core.sha256(core.PROJECT / "protocol" / "BATCH_004.json"),
        "SELECTION.json": core.sha256(RESULTS / "SELECTION.json"),
        "champion_signals_screening.parquet": core.sha256(RESULTS / "champion_signals_screening.parquet"),
        "actions_base": core.sha256(prior_audit.ACTIONS_BASE),
        "eastmoney_actions_batch002.json": core.sha256(prior_audit.EASTMONEY_ACTIONS),
        "eastmoney_actions_batch003.json": core.sha256(batch3_audit.EASTMONEY_ACTIONS),
        "eastmoney_actions_batch004.json": core.sha256(EASTMONEY_ACTIONS),
        "action_gaps_requested.json": core.sha256(AUDIT / "action_gaps.json"),
    }
    output = {
        "status": "complete" if row["audit_passed"] else "audit_failed",
        "champion_spec": selection["champion_spec"],
        "audited_champion": row,
        "known_action_stock_years": len(known_keys),
        "source_hashes": hashes,
        "assertions": {
            "post_2024_access": False,
            "maximum_signal_date": str(signals.date.max().date()),
            "maximum_raw_bar_date": str(max(calendar).date()),
            "corporate_action_coverage_complete": True,
            "all_years_at_least_20_trades": bool(row["eligible_trade_count"]),
            "at_least_3_profitable_years": bool(row["eligible_cross_year"]),
            "no_open_positions_at_end": row["open_positions_at_end"] == 0,
            "grid_expanded": False,
            "production_change": False,
        },
        "development_note": "2022-2024 is part of the 2020-2024 development period and is not blind or holdout evidence.",
    }
    (AUDIT / "FINAL_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RESULTS / "REPORT.md").write_text(report(selection, row), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0 if row["audit_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
