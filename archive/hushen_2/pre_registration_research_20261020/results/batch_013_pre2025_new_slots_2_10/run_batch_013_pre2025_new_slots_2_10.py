from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


RESULTS = Path(__file__).resolve().parent
PROJECT = RESULTS.parents[1]
RESEARCH = PROJECT / "research"
BATCH012_DIR = PROJECT / "results" / "batch_012_pre2025_new_slot_grid"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(BATCH012_DIR))
import run_batch as core  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import run_batch_007_pre2025 as batch7  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import run_batch_012_pre2025_new_slot_grid as b12  # noqa: E402


PROTOCOL = PROJECT / "protocol" / "BATCH_013_PRE2025_NEW_SLOTS_2_10.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
STARTS_FILE = PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "sampled_start_dates.csv"
SLOTS = list(range(2, 11))
YEARS = [2020, 2021, 2022, 2023, 2024]
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
LAST_SIGNAL_DATE = pd.Timestamp("2024-11-22")


def validate_protocol() -> dict:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p.get("status") != "preregistered_before_batch_013_results":
        raise RuntimeError("Batch013 protocol was not preregistered")
    if p.get("instruction_boundary_version") != "public-pre2025-v1" or not p.get("post_2024_forbidden"):
        raise RuntimeError("Batch013 isolation boundary mismatch")
    if p["slot_grid"]["slots"] != SLOTS or p["slot_grid"]["candidate_count"] != 9:
        raise RuntimeError("Batch013 fixed slots grid changed")
    execution = p["execution"]
    expected = {
        "initial_cash": 100000,
        "maximum_daily_signals": 3,
        "conditional_buy_lifetime_calendar_days": 7,
        "holding_calendar_days": 30,
        "entry_atr": 0.0,
        "take_atr": 4.0,
        "stop_atr": 1.5,
        "daily_volume_capacity_fraction": 0.02,
    }
    for key, value in expected.items():
        if execution.get(key) != value:
            raise RuntimeError(f"Batch013 execution changed: {key}")
    return p


def markdown_report(grid, annual, utilization, q1, selection, audit) -> str:
    grid_lines = []
    for r in grid.sort_values("slots").itertuples(index=False):
        grid_lines.append(
            f"|{r.slots}|{r.strategy_cagr:.2%}|{r.annualized_excess:.2%}|{r.worst_annual_return:.2%}|"
            f"{r.mean_annual_return:.2%}|{r.worst_annual_excess:.2%}|{r.mean_annual_excess:.2%}|"
            f"{r.profitable_years}|{r.outperform_years}|{r.completed_trades}|{r.total_fees:.2f}|{bool(r.hard_gate)}|"
        )
    annual_lines = []
    for r in annual.sort_values(["slots", "year"]).itertuples(index=False):
        annual_lines.append(
            f"|{r.slots}|{r.year}|{r.signal_count}|{r.completed_trades}|{r.strategy_return:.2%}|"
            f"{r.benchmark_return:.2%}|{r.excess_return:.2%}|{r.total_fees:.2f}|{r.mean_fee_per_completed_trade:.2f}|"
        )
    util_lines = []
    for r in utilization.sort_values("slots").itertuples(index=False):
        util_lines.append(
            f"|{r.slots}|{r.total_signals}|{r.skipped_no_free_slot}|{r.skipped_duplicate_symbol}|"
            f"{r.pending_orders_created}|{r.filled_orders}|{r.expired_entry_orders}|{r.average_occupied_slots_eod:.2f}|"
            f"{r.average_slot_occupancy_rate:.2%}|{r.order_creation_rate:.2%}|{r.fill_per_signal_rate:.2%}|"
        )
    q1_lines = []
    for r in q1.sort_values(["slots", "year"]).itertuples(index=False):
        q1_lines.append(
            f"|{r.slots}|{r.year}|{r.mean_strategy_return:.2%}|{r.mean_benchmark_return:.2%}|"
            f"{r.mean_excess_return:.2%}|{r.minimum_excess_return:.2%}|{r.positive_excess_fraction:.0%}|"
            f"{r.minimum_completed_trades}|{r.terminal_empty_fraction:.0%}|"
        )
    raw = audit["raw_summary"]
    return f"""# 沪深智能1 Batch013：冻结 NEW 2—10槽追加网格

## 结论

本批严格只用 2024-12-31 及以前输入，固定测试 `2/3/4/5/6/7/8/9/10` 九档。NEW公式、100% Top3信号、10万元初始资金及所有成交规则均与Batch012一致，没有按结果扩网格。

唯一摘要候选为 `{selection['selected_candidate']}`，选择依据 `{selection['selection_basis']}`。原始OHLC、完整pre-2025公司行动及退市复审状态为 `{audit['status']}`；数据完整性通过 `{audit['data_integrity_pass']}`，原始收益硬门槛通过 `{audit['raw_performance_gate_pass']}`。失败不重选，不修改生产。

## 完整网格

|槽位|CAGR|年化超额|最差年收益|平均年收益|最差年超额|平均年超额|盈利年|跑赢年|交易|总费用|硬门槛|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
{chr(10).join(grid_lines)}

事前硬门槛要求五年逐年超额均为正、最差年度收益为正、五个年度共享Q1平均超额均为正，且完整窗口及全部共享起点终态空仓无挂单。门槛内依次按CAGR、平均年度超额、最差年度超额、最差年度收益、较少槽位排序。

## 逐年收益与费用

|槽位|年度|信号|完成交易|账户收益|上证收益|超额|费用|每笔平均费用|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(annual_lines)}

费用包括佣金及印花税；滑点已反映在成交价中，不重复计入费用列。

## 信号利用率

|槽位|总信号|无槽跳过|同股跳过|创建挂单|成交|7日过期|平均占槽|平均占槽率|信号利用率|信号成交率|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(util_lines)}

主信号利用率为创建挂单/总信号；挂单与持仓均占槽。跳过计数先判同股、再判无空槽，计数不改变成交。

## 共享Q1随机起点

九档复用Batch010事先固定的25个起点，每年5个，共225次。

|槽位|年度|平均收益|平均上证|平均超额|最差超额|正超额比|最少交易|终态空仓比|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(q1_lines)}

## 原始审计与限制

原始审计CAGR `{raw['strategy_cagr']:.2%}`、年化超额 `{raw['annualized_excess']:.2%}`、最差年度收益 `{raw['worst_annual_return']:.2%}`、最差年度超额 `{raw['worst_annual_excess']:.2%}`。审计明细见 `audit/AUDIT_PATHS.md`。

所有结果均属于2020—2024开发证据，不是盲测；没有读取2025年后数据、没有真实委托、没有修改生产或当前登记。
"""


def main() -> int:
    protocol = validate_protocol()
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.min() < pd.Timestamp("2020-01-01") or panel.date.max() > LAST_SIGNAL_DATE:
        raise RuntimeError("Batch013 panel boundary violation")
    signals = b12.b11.build_top3(panel).copy()
    signals["factor"] = "FROZEN_NEW"
    if signals.groupby("date").size().ne(3).any():
        raise RuntimeError("Batch013 is not exact frozen NEW Top3")
    bars, calendar = core.load_execution_bars(set(signals.symbol.astype(str)), force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch013 execution data crossed pre-2025 boundary")
    benchmark, _ = batch6.load_benchmark()
    starts = b12.b11.load_starts()
    benchmark_starts = b12.b11.benchmark_start_returns(starts)

    grid_rows, annual_rows, utilization_rows, random_rows = [], [], [], []
    for index, slots in enumerate(SLOTS, 1):
        run, trades = core.simulate(
            signals, bars, calendar, "FROZEN_NEW", 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=True, slots=slots,
        )
        yearly, summary = b12.annual_and_summary(slots, signals, run, trades, benchmark)
        annual_rows.extend(yearly)
        grid_rows.append(summary)
        utilization_rows.append(b12.utilization_row(slots, run))
        for item in starts.itertuples(index=False):
            start = pd.Timestamp(item.start_date)
            window, _ = b12.run_window(signals, bars, calendar, "FROZEN_NEW", slots, int(item.year), start)
            strategy_return = float(window[f"return_{int(item.year)}"])
            benchmark_return = benchmark_starts[(int(item.year), start)]
            random_rows.append({
                "slots": slots, "year": int(item.year), "start_rank": int(item.start_rank),
                "start_date": str(start.date()), "strategy_return": strategy_return,
                "benchmark_return": benchmark_return, "excess_return": strategy_return - benchmark_return,
                "completed_trades": int(window["completed_trades"]),
                "open_positions_at_end": int(window["open_positions_at_end"]),
                "pending_orders_at_end": int(window["pending_orders_at_end"]),
            })
        print(f"batch013 screening {index}/9 slots={slots}", flush=True)

    grid = pd.DataFrame(grid_rows)
    annual = pd.DataFrame(annual_rows)
    utilization = pd.DataFrame(utilization_rows)
    random_runs = pd.DataFrame(random_rows)
    if len(grid) != 9 or len(annual) != 45 or len(random_runs) != 225:
        raise RuntimeError("Batch013 output cardinality mismatch")
    q1 = random_runs.groupby(["slots", "year"], as_index=False).agg(
        mean_strategy_return=("strategy_return", "mean"), mean_benchmark_return=("benchmark_return", "mean"),
        mean_excess_return=("excess_return", "mean"), minimum_excess_return=("excess_return", "min"),
        positive_excess_fraction=("excess_return", lambda x: float((x > 0).mean())),
        minimum_completed_trades=("completed_trades", "min"),
        terminal_empty_fraction=("open_positions_at_end", lambda x: float((x == 0).mean())),
        pending_empty_fraction=("pending_orders_at_end", lambda x: float((x == 0).mean())),
    )
    gate = []
    for row in grid.itertuples(index=False):
        ann = annual[annual.slots.eq(row.slots)]
        starts_group = q1[q1.slots.eq(row.slots)]
        gate.append(bool(
            ann.excess_return.gt(0).all() and row.worst_annual_return > 0
            and starts_group.mean_excess_return.gt(0).all()
            and starts_group.terminal_empty_fraction.eq(1.0).all()
            and starts_group.pending_empty_fraction.eq(1.0).all()
            and row.open_positions_at_end == 0 and row.pending_orders_at_end == 0
        ))
    grid["hard_gate"] = gate
    eligible = grid[grid.hard_gate].copy()
    if not eligible.empty:
        selected = eligible.sort_values(
            ["strategy_cagr", "mean_annual_excess", "worst_annual_excess", "worst_annual_return", "slots"],
            ascending=[False, False, False, False, True], kind="stable",
        ).iloc[0]
        basis = "hard_gate_then_cagr_mean_excess"
    else:
        selected = grid.sort_values(
            ["outperform_years", "profitable_years", "worst_annual_excess", "worst_annual_return", "strategy_cagr", "mean_annual_excess", "slots"],
            ascending=[False, False, False, False, False, False, True], kind="stable",
        ).iloc[0]
        basis = "preregistered_fallback_no_hard_gate_candidate"
    selected_slots = int(selected.slots)
    selected_candidate = str(selected.candidate)

    grid.sort_values("slots").to_csv(RESULTS / "full_slot_grid.csv", index=False, encoding="utf-8-sig")
    annual.sort_values(["slots", "year"]).to_csv(RESULTS / "annual_metrics.csv", index=False, encoding="utf-8-sig")
    utilization.sort_values("slots").to_csv(RESULTS / "signal_utilization.csv", index=False, encoding="utf-8-sig")
    random_runs.sort_values(["slots", "year", "start_rank"]).to_csv(RESULTS / "shared_q1_random_start_runs_225.csv", index=False, encoding="utf-8-sig")
    q1.sort_values(["slots", "year"]).to_csv(RESULTS / "shared_q1_summary.csv", index=False, encoding="utf-8-sig")

    selection = {
        "status": "unique_summary_candidate_frozen_pending_pre2025_raw_audit",
        "protocol_id": protocol["protocol_id"], "selected_candidate": selected_candidate,
        "selected_slots": selected_slots, "selection_basis": basis,
        "hard_gate_count": int(grid.hard_gate.sum()), "candidate_count": 9, "shared_q1_run_count": 225,
        "assertions": {
            "instruction_boundary_version": "public-pre2025-v1", "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()), "maximum_execution_date": str(max(calendar).date()),
            "exact_frozen_new_top3_100_percent": True, "all_slot_candidates_retained": True,
            "production_change": False,
        },
        "source_hashes": {
            "protocol": b12.sha256(PROTOCOL), "base_panel": b12.sha256(BASE_PANEL),
            "benchmark": b12.sha256(batch6.BENCHMARK), "starts": b12.sha256(STARTS_FILE),
            "core_engine": b12.sha256(RESEARCH / "run_batch.py"), "runner": b12.sha256(Path(__file__)),
        },
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_dir = RESULTS / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(signals.symbol.astype(str)))
    if raw_all.date.max() > HARD_MAX_DATE or max(raw_calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch013 raw audit crossed pre-2025 boundary")
    raw_frame = b12.raw_signals(signals, raw_all)
    actions, known = b12.b11.load_verified_pre2025_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    raw_run, raw_trades = core.simulate(
        raw_frame, raw_bars, raw_calendar, "FROZEN_NEW", 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing,
        delist_dates=delistings, slots=selected_slots,
    )
    raw_yearly, raw_summary = b12.annual_and_summary(selected_slots, raw_frame, raw_run, raw_trades, benchmark)
    raw_trades.to_csv(audit_dir / "selected_candidate_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(raw_yearly).to_csv(audit_dir / "selected_candidate_annual_metrics_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([b12.utilization_row(selected_slots, raw_run)]).to_csv(audit_dir / "selected_candidate_signal_utilization_raw.csv", index=False, encoding="utf-8-sig")
    raw_start_rows = []
    for item in starts.itertuples(index=False):
        start = pd.Timestamp(item.start_date)
        window, _ = b12.run_window(
            raw_frame, raw_bars, raw_calendar, "FROZEN_NEW", selected_slots, int(item.year), start,
            raw=True, actions=actions, known=known, coverage=missing, delistings=delistings,
        )
        strategy_return = float(window[f"return_{int(item.year)}"])
        benchmark_return = benchmark_starts[(int(item.year), start)]
        raw_start_rows.append({
            "slots": selected_slots, "year": int(item.year), "start_rank": int(item.start_rank),
            "start_date": str(start.date()), "strategy_return": strategy_return,
            "benchmark_return": benchmark_return, "excess_return": strategy_return - benchmark_return,
            "completed_trades": int(window["completed_trades"]),
            "open_positions_at_end": int(window["open_positions_at_end"]),
            "pending_orders_at_end": int(window["pending_orders_at_end"]),
        })
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(audit_dir / "selected_candidate_shared_q1_raw_25.csv", index=False, encoding="utf-8-sig")
    data_integrity = bool(
        not missing and raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE
        and raw_run["open_positions_at_end"] == 0 and raw_run["pending_orders_at_end"] == 0
        and raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()
    )
    raw_annual_frame = pd.DataFrame(raw_yearly)
    raw_q1_year_mean = raw_starts.groupby("year").excess_return.mean()
    raw_performance = bool(
        raw_annual_frame.excess_return.gt(0).all() and float(raw_summary["worst_annual_return"]) > 0
        and raw_q1_year_mean.gt(0).all()
    )
    audit_pass = bool(data_integrity and raw_performance)
    audit = {
        "status": "complete" if audit_pass else "audit_failed_no_reselection",
        "audited_candidate": selected_candidate, "audited_slots": selected_slots,
        "selection_basis": basis, "audit_did_not_trigger_reselection": True,
        "data_integrity_pass": data_integrity, "raw_performance_gate_pass": raw_performance,
        "raw_summary": raw_summary, "raw_signal_utilization": b12.utilization_row(selected_slots, raw_run),
        "missing_corporate_action_keys": sorted(missing),
        "raw_q1": {
            "run_count": int(len(raw_starts)), "positive_excess_fraction": float((raw_starts.excess_return > 0).mean()),
            "minimum_excess": float(raw_starts.excess_return.min()),
            "mean_excess_by_year": {str(int(y)): float(v) for y, v in raw_q1_year_mean.items()},
            "all_terminal_empty": bool(raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()),
        },
        "assertions": {
            "maximum_raw_date": str(raw_all.date.max().date()), "maximum_execution_date": str(max(raw_calendar).date()),
            "pre2025_boundary_passed": True, "corporate_action_coverage_complete": not missing,
            "delisting_rules_loaded": bool(delistings), "production_change": False,
        },
        "source_hashes": {
            "protocol": b12.sha256(PROTOCOL), "selection": b12.sha256(RESULTS / "SELECTION.json"),
            "runner": b12.sha256(Path(__file__)), "base_actions": b12.sha256(prior_audit.ACTIONS_BASE),
            "batch006_actions": b12.sha256(b12.b11.audit6.EASTMONEY_ACTIONS),
            "batch007_actions": b12.sha256(PROJECT / "results" / "batch_007_pre2025_start_robustness" / "audit" / "eastmoney_actions.json"),
            "batch010_actions": b12.sha256(PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "audit" / "eastmoney_actions.json"),
            "delisting_metadata": b12.sha256(prior_audit.METADATA),
        },
    }
    (audit_dir / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    final = {**selection, "status": "complete_research_only_no_production_change" if audit_pass else "complete_screening_raw_audit_failed_no_reselection", "audit_status": audit["status"]}
    (RESULTS / "FINAL_SELECTION.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "REPORT.md").write_text(markdown_report(grid, annual, utilization, q1, selection, audit), encoding="utf-8")
    print(json.dumps({"selected": selected_candidate, "hard_gate_count": int(grid.hard_gate.sum()), "audit": audit["status"]}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
