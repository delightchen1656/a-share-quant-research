from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("batch9", HERE / "run_batch_009_pre2025_cagr_excess.py")
b9 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(b9)

selection_path = HERE / "SELECTION.json"
selection = json.loads(selection_path.read_text(encoding="utf-8"))
champion = selection["champion"]
protocol = b9.validate_protocol()
if champion != "C05_M25" or selection["status"] != "unique_champion_frozen_pending_independent_raw_audit":
    raise RuntimeError("Frozen Batch009 champion/status changed; re-audit refuses to select")

panel = pd.read_parquet(b9.BASE_PANEL)
panel["date"] = pd.to_datetime(panel.date)
signals = b9.build_signals(panel, champion, protocol["candidates"][champion])
starts = pd.read_csv(HERE / "sampled_start_dates.csv", dtype={"start_date": str})
if len(starts) != 25:
    raise RuntimeError("Frozen Batch009 starts changed")

audit_dir = HERE / "audit"
raw_bars, raw_calendar, raw_all, raw_manifest = b9.batch7.load_raw_pre2025(set(signals.symbol.astype(str)))
raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
raw_signals = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
if raw_signals.raw_close.isna().any():
    raise RuntimeError("Raw audit signal close missing")
raw_signals = raw_signals.rename(columns={"raw_close": "close"})
actions, known = b9.load_audit_actions()
delistings = b9.prior_audit.load_delistings()
benchmark, _ = b9.batch6.load_benchmark()
missing: set[str] = set()
audit_row, audit_trades = b9.core.simulate(raw_signals, raw_bars, raw_calendar, champion, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5, keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing, delist_dates=delistings)
audit_row.update(b9.batch6.active_metrics(audit_row, benchmark))
audit_trades.to_csv(audit_dir / "champion_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")

start_rows, trade_rows = [], []
for start in starts.itertuples(index=False):
    row, trades = b9.run_window(raw_signals, raw_bars, raw_calendar, champion, int(start.year), pd.Timestamp(start.start_date), raw=True, actions=actions, known=known, coverage=missing, delistings=delistings, keep_trades=True)
    start_rows.append({"candidate": champion, "year": int(start.year), "start_rank": int(start.start_rank), "start_date": start.start_date, "return_value": float(row[f"return_{start.year}"]), "completed_trades": int(row["completed_trades"]), "open_positions_at_end": int(row["open_positions_at_end"]), "pending_orders_at_end": int(row["pending_orders_at_end"])})
    if not trades.empty:
        trades = trades.copy(); trades.insert(0, "run_start_date", start.start_date); trade_rows.append(trades)
raw_starts = pd.DataFrame(start_rows)
raw_starts.to_csv(audit_dir / "champion_shared_q1_random_start_audit_25.csv", index=False, encoding="utf-8-sig")
pd.concat(trade_rows, ignore_index=True).to_csv(audit_dir / "champion_shared_q1_random_start_trades_raw.csv", index=False, encoding="utf-8-sig")
raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
signal_counts = raw_signals.groupby(raw_signals.date.dt.year).size().reindex(b9.YEARS, fill_value=0).to_dict()
metrics = b9.base_gate_metrics(audit_row, raw_starts, signal_counts, benchmark)
passed = bool(not missing and metrics["base_gate"] and audit_row["open_positions_at_end"] == 0 and audit_row["pending_orders_at_end"] == 0 and raw_all.date.max() <= b9.HARD_MAX_DATE and max(raw_calendar) <= b9.HARD_MAX_DATE)
out = {
    "status": "complete" if passed else "audit_failed",
    "champion_frozen_before_audit": champion,
    "audit_did_not_trigger_reselection": True,
    "initial_audit_failure_retained_at": "audit/FINAL_AUDIT.json",
    "supplemental_query_scope": sorted(json.loads((audit_dir / "eastmoney_actions.json").read_text(encoding="utf-8"))["records"]),
    "audited_champion": audit_row,
    "raw_hard_gate_metrics": metrics,
    "missing_corporate_action_keys": sorted(missing),
    "assertions": {"pre2025_boundary_passed": raw_all.date.max() <= b9.HARD_MAX_DATE and max(raw_calendar) <= b9.HARD_MAX_DATE, "corporate_action_coverage_complete": not missing, "raw_hard_gates_passed": metrics["base_gate"], "full_window_terminal_empty": audit_row["open_positions_at_end"] == 0 and audit_row["pending_orders_at_end"] == 0, "random_start_run_count_exact_25": len(raw_starts) == 25, "production_change": False},
    "source_hashes": {"protocol": b9.sha256(b9.PROTOCOL), "selection": b9.sha256(selection_path), "runner": b9.sha256(HERE / "run_batch_009_pre2025_cagr_excess.py"), "supplemental_actions": b9.sha256(audit_dir / "eastmoney_actions.json")},
}
(audit_dir / "FINAL_AUDIT_RECHECK.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps({"champion": champion, "status": out["status"], "missing": sorted(missing)}, ensure_ascii=False))
raise SystemExit(0 if passed else 1)
