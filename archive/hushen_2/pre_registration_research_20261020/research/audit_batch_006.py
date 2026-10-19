from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import audit_batch_003 as batch3_audit  # noqa: E402
import audit_batch_004 as batch4_audit  # noqa: E402


RESULTS = core.PROJECT / "results" / "batch_006_pre2025_active_objectives"
AUDIT = RESULTS / "audit"
EASTMONEY_ACTIONS = AUDIT / "eastmoney_actions.json"


def load_actions():
    actions, known = batch4_audit.load_actions()
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


def audited_eligibility(row: dict, objective: str) -> dict:
    trade_ok = all(int(row[f"trades_{year}"]) >= 20 for year in core.YEARS)
    profitable_ok = int(row["profitable_years"]) >= 3
    common = trade_ok and profitable_ok
    if objective == "defense_maximin":
        objective_ok = common
    elif objective == "stability_min_std":
        objective_ok = common and float(row["active_mean"]) > 0.0 and int(row["positive_active_years"]) >= 3
    else:
        raise ValueError(objective)
    return {
        "eligible_trade_count": bool(trade_ok),
        "eligible_profitable_strategy_years": bool(profitable_ok),
        "eligible_objective": bool(objective_ok),
        "no_open_positions_at_end": int(row["open_positions_at_end"]) == 0,
        "audit_passed": bool(objective_ok and int(row["open_positions_at_end"]) == 0),
    }


def annual_table(row: dict, benchmark_returns: dict[int, float]) -> list[dict]:
    return [{
        "year": year,
        "strategy_return": float(row[f"return_{year}"]),
        "benchmark_price_return": float(benchmark_returns[year]),
        "active_return": float(row[f"active_return_{year}"]),
        "completed_trades": int(row[f"trades_{year}"]),
    } for year in core.YEARS]


def markdown_report(selection: dict, audited: dict, benchmark_returns: dict[int, float], reused: bool) -> str:
    sections = []
    for objective in batch6.OBJECTIVES:
        frozen = selection["champions"][objective]
        screening = frozen["screening_champion"]
        audit = audited[objective]
        spec = frozen["champion_spec"]
        rows = "\n".join(
            f"| {year} | {audit[f'return_{year}']:.4%} | {benchmark_returns[year]:.4%} | "
            f"{audit[f'active_return_{year}']:.4%} | {int(audit[f'trades_{year}'])} |"
            for year in core.YEARS
        )
        sections.append(f"""## {objective}

- Screening champion: `{screening['candidate']}`
- M internal (utility, pen025, pen100): `{spec['M_internal']}`
- T internal (+mom120, +close/high60, +mom20, -vol60): `{spec['T_internal']}`
- H internal (-size, -vol60, +overnight, -intraday): `{spec['H_internal']}`
- Outer (M, T, H): `{spec['outer']}`
- Screening active min / mean / std(ddof=0): {screening['active_min']:.4%} / {screening['active_mean']:.4%} / {screening['active_std_ddof0']:.4%}
- Audited active min / mean / std(ddof=0): {audit['active_min']:.4%} / {audit['active_mean']:.4%} / {audit['active_std_ddof0']:.4%}
- Audited active variance check: {audit['active_variance_check']:.10f} (recorded only; never selected on variance)
- Audited CAGR / final equity: {audit['cagr']:.4%} / {audit['final_equity']:.2f}
- Positive active years: {audit['positive_active_years']}
- Boundary flags: `{frozen['boundary_flags']}`
- Signal frequency: `{frozen['signal_frequency']}`

| Development year | Strategy return | Shanghai Composite price return | Active return | Completed trades |
|---:|---:|---:|---:|---:|
{rows}
""")
    reuse_note = "The two objectives froze the same effective signal specification, so one raw execution audit was reused." if reused else "The two champions were audited independently because their effective specifications differed."
    objective_sections = "\n".join(sections)
    return f"""# Batch 006 pre-2025 active-return objectives

This preregistered batch ran two independent four-stage paths of 151 candidates each (302 total). All 2020-2024 results are development evidence, not blind or holdout evidence. No grid expansion or production change occurred.

The benchmark is the Eastmoney/AkShare `sh000001` Shanghai Composite ordinary price index (`000001.SH`). Its annual return is the final trading close of each calendar year divided by the prior calendar year's final trading close minus one. The price index excludes dividends, while the audited strategy account includes corporate-action cash dividends; active returns therefore have that comparison limitation.

The prior unidentified `strategies/hushen/backtest/data/benchmark.parquet` was rejected because its fields and parquet metadata did not establish instrument identity and it was not used to calculate returns.

{reuse_note} Audit results did not trigger reselection.

{objective_sections}
"""


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    selection = json.loads((RESULTS / "SELECTION.json").read_text(encoding="utf-8"))
    benchmark_returns, benchmark_audit = batch6.load_benchmark()
    if selection.get("completed_screening_runs") != 302:
        raise RuntimeError("Screening selection does not contain exactly 302 runs")

    champions = selection["champions"]
    signal_frames = {}
    specs = {}
    symbols = set()
    for objective in batch6.OBJECTIVES:
        path = RESULTS / f"{objective}_champion_signals_screening.parquet"
        signals = pd.read_parquet(path)
        signals["date"] = pd.to_datetime(signals.date)
        if signals.empty or signals.date.max() > pd.Timestamp("2024-11-22"):
            raise RuntimeError(f"{objective} champion signals violate pre-2025 boundary")
        signal_frames[objective] = signals
        specs[objective] = json.dumps(champions[objective]["champion_spec"], sort_keys=True)
        symbols.update(signals.symbol.astype(str))

    by_symbol, calendar, raw = prior_audit.load_raw_bars(symbols)
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Raw audit bars cross 2024-12-31")
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    actions, known_keys = load_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    audited = {}
    executed_by_spec = {}
    reused = False

    for objective in batch6.OBJECTIVES:
        signals = signal_frames[objective].drop(columns=["close"]).merge(
            raw_close, on=["date", "symbol"], how="left", validate="many_to_one"
        )
        if signals.raw_close.isna().any():
            raise RuntimeError(f"Missing raw signal-date close for {objective}")
        signals = signals.rename(columns={"raw_close": "close"})
        spec_key = specs[objective]
        if spec_key in executed_by_spec:
            base_row, base_trades = executed_by_spec[spec_key]
            row = dict(base_row)
            trades = base_trades.copy()
            reused = True
        else:
            candidate = champions[objective]["screening_champion"]
            row, trades = core.simulate(
                signals, by_symbol, calendar, str(candidate["candidate"]),
                0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
                keep_trades=True, actions=actions, known_action_keys=known_keys,
                coverage_sink=missing, delist_dates=delistings,
            )
            executed_by_spec[spec_key] = (dict(row), trades.copy())
        row.update(batch6.active_metrics(row, benchmark_returns))
        row.update(audited_eligibility(row, objective))
        row["objective"] = objective
        row["screening_candidate"] = champions[objective]["screening_champion"]["candidate"]
        row["annual"] = annual_table(row, benchmark_returns)
        audited[objective] = row
        trades.to_csv(AUDIT / f"{objective}_champion_trades_raw_action_audited.csv", index=False, encoding="utf-8-sig")

    if missing:
        gaps = [[key.split("/")[0], int(key.split("/")[1])] for key in sorted(missing)]
        (AUDIT / "action_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "action_data_required", "gap_count": len(gaps)}, ensure_ascii=False))
        return 2

    source_paths = {
        "audit_batch_006.py": Path(__file__),
        "run_batch_006.py": HERE / "run_batch_006.py",
        "run_batch.py": HERE / "run_batch.py",
        "audit_batch_004.py": HERE / "audit_batch_004.py",
        "fetch_actions_eastmoney.py": HERE / "fetch_actions_eastmoney.py",
        "BATCH_006.json": batch6.PROTOCOL,
        "SELECTION.json": RESULTS / "SELECTION.json",
        "actions_base": prior_audit.ACTIONS_BASE,
        "eastmoney_actions_batch002.json": prior_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch003.json": batch3_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch004.json": batch4_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch006.json": EASTMONEY_ACTIONS,
        "sh000001_eastmoney_pre2025.parquet": batch6.BENCHMARK,
        "sh000001_eastmoney_pre2025.metadata.json": batch6.BENCHMARK_META,
    }
    source_hashes = {name: batch6.sha256(path) for name, path in source_paths.items() if path.exists()}
    all_passed = all(bool(row["audit_passed"]) for row in audited.values())
    output = {
        "status": "complete" if all_passed else "audit_failed",
        "screening_champions_frozen_before_audit": {
            objective: champions[objective]["screening_champion"]["candidate"] for objective in batch6.OBJECTIVES
        },
        "audit_did_not_trigger_reselection": True,
        "same_effective_spec_audit_reused": reused,
        "audited_champions": audited,
        "benchmark": benchmark_audit,
        "known_action_stock_years": len(known_keys),
        "source_hashes": source_hashes,
        "assertions": {
            "screening_run_count_exact_302": selection["assertions"]["screening_run_count_exact_302"],
            "maximum_signal_date": max(str(frame.date.max().date()) for frame in signal_frames.values()),
            "maximum_signal_date_at_or_before_2024_11_22": all(frame.date.max() <= pd.Timestamp("2024-11-22") for frame in signal_frames.values()),
            "maximum_raw_execution_date": str(max(calendar).date()),
            "maximum_execution_date_at_or_before_2024_12_31": max(calendar) <= core.HARD_MAX_DATE,
            "corporate_action_coverage_complete": True,
            "post_2024_access": False,
            "grid_expanded": False,
            "production_change": False,
        },
        "comparison_limitation": "Shanghai Composite is an ordinary price index excluding dividends; audited strategy returns include corporate-action cash dividends.",
        "development_note": "All 2020-2024 results are development evidence and are not blind or holdout evidence.",
    }
    (AUDIT / "FINAL_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RESULTS / "REPORT.md").write_text(markdown_report(selection, audited, benchmark_returns, reused), encoding="utf-8")
    print(json.dumps({"status": output["status"], "assertions": output["assertions"]}, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
