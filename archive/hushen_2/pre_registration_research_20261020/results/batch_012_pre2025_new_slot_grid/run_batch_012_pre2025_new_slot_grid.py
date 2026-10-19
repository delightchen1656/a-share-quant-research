from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


RESULTS = Path(__file__).resolve().parent
PROJECT = RESULTS.parents[1]
RESEARCH = PROJECT / "research"
BATCH011_DIR = PROJECT / "results" / "batch_011_pre2025_new_threshold_grid"
sys.path.insert(0, str(RESEARCH))
sys.path.insert(0, str(BATCH011_DIR))
import run_batch as core  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import run_batch_007_pre2025 as batch7  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import run_batch_011_pre2025_new_threshold_grid as b11  # noqa: E402


PROTOCOL = PROJECT / "protocol" / "BATCH_012_PRE2025_NEW_SLOT_GRID.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
STARTS_FILE = PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "sampled_start_dates.csv"
SLOTS = [10, 15, 20, 25, 30, 40, 50]
YEARS = [2020, 2021, 2022, 2023, 2024]
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
LAST_SIGNAL_DATE = pd.Timestamp("2024-11-22")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def geometric(values) -> float:
    a = np.asarray(list(values), dtype=float)
    if np.any(a <= -1.0):
        return -1.0
    return float(np.prod(1.0 + a) ** (1.0 / len(a)) - 1.0)


def validate_protocol() -> dict:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p.get("status") != "preregistered_before_batch_012_results":
        raise RuntimeError("Batch012 protocol was not preregistered")
    if p.get("instruction_boundary_version") != "public-pre2025-v1" or not p.get("post_2024_forbidden"):
        raise RuntimeError("Batch012 isolation boundary mismatch")
    if p["slot_grid"]["slots"] != SLOTS or p["slot_grid"]["candidate_count"] != 7:
        raise RuntimeError("Batch012 fixed slot grid changed")
    execution = p["execution"]
    required = {
        "initial_cash": 100000,
        "maximum_daily_signals": 3,
        "conditional_buy_lifetime_calendar_days": 7,
        "holding_calendar_days": 30,
        "entry_atr": 0.0,
        "take_atr": 4.0,
        "stop_atr": 1.5,
        "daily_volume_capacity_fraction": 0.02,
    }
    for key, expected in required.items():
        if execution.get(key) != expected:
            raise RuntimeError(f"Batch012 execution changed: {key}")
    return p


def run_window(signals, bars, calendar, factor, slots, year, start, *, raw=False, actions=None, known=None, coverage=None, delistings=None):
    last_session = max(date for date in calendar if date.year == year)
    cutoff = pd.Timestamp(f"{year}-12-31") - pd.Timedelta(days=37)
    selected = signals[signals.date.between(start, cutoff)].copy()
    old = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = start, last_session, cutoff, [year]
        return core.simulate(
            selected, bars, calendar, factor, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            actions=actions if raw else None,
            known_action_keys=known if raw else None,
            coverage_sink=coverage if raw else None,
            delist_dates=delistings if raw else None,
            slots=slots,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old


def annual_and_summary(slots: int, signals: pd.DataFrame, run: dict, trades: pd.DataFrame, benchmark: dict[int, float]) -> tuple[list[dict], dict]:
    annual = []
    returns = []
    excesses = []
    signal_counts = []
    for year in YEARS:
        part = signals[signals.date.dt.year.eq(year)]
        count = int(len(part))
        days = int(part.date.nunique())
        strategy = float(run[f"return_{year}"])
        bench = float(benchmark[year])
        excess = strategy - bench
        year_trades = trades[trades.entry_year.eq(year)] if not trades.empty else trades
        entry_fees = float(year_trades.entry_fee.sum()) if not year_trades.empty else 0.0
        exit_fees = float(year_trades.exit_fee_and_tax.sum()) if not year_trades.empty else 0.0
        gross_pnl = float(year_trades.gross_trade_pnl_before_fees.sum()) if not year_trades.empty else 0.0
        net_pnl = float(year_trades.pnl.sum()) if not year_trades.empty else 0.0
        completed = int(run[f"trades_{year}"])
        annual.append({
            "slots": slots,
            "year": year,
            "signal_count": count,
            "signal_days": days,
            "mean_signals_per_signal_day": float(count / days) if days else 0.0,
            "completed_trades": completed,
            "strategy_return": strategy,
            "benchmark_return": bench,
            "excess_return": excess,
            "total_entry_fees": entry_fees,
            "total_exit_fees_and_tax": exit_fees,
            "total_fees": entry_fees + exit_fees,
            "mean_fee_per_completed_trade": float((entry_fees + exit_fees) / completed) if completed else 0.0,
            "gross_completed_trade_pnl_before_fees": gross_pnl,
            "net_completed_trade_pnl_after_fees": net_pnl,
        })
        returns.append(strategy)
        excesses.append(excess)
        signal_counts.append(count)
    count_array = np.asarray(signal_counts, dtype=float)
    summary = {
        "candidate": f"SLOTS_{slots:02d}",
        "slots": slots,
        "signal_count_total": int(len(signals)),
        "strategy_cagr": float(run["cagr"]),
        "benchmark_cagr": geometric(benchmark[y] for y in YEARS),
        "annualized_excess": float(run["cagr"]) - geometric(benchmark[y] for y in YEARS),
        "worst_annual_return": float(min(returns)),
        "mean_annual_return": float(np.mean(returns)),
        "worst_annual_excess": float(min(excesses)),
        "mean_annual_excess": float(np.mean(excesses)),
        "profitable_years": int(sum(x > 0 for x in returns)),
        "outperform_years": int(sum(x > 0 for x in excesses)),
        "annual_signal_frequency_cv_ddof0": float(count_array.std(ddof=0) / count_array.mean()) if count_array.mean() else math.inf,
        "completed_trades": int(run["completed_trades"]),
        "trade_count_cv_ddof0": float(run["trade_count_cv"]),
        "total_entry_fees": float(run["total_entry_fees"]),
        "total_exit_fees_and_tax": float(run["total_exit_fees_and_tax"]),
        "total_fees": float(run["total_fees"]),
        "mean_fee_per_completed_trade": float(run["total_fees"] / run["completed_trades"]) if run["completed_trades"] else 0.0,
        "gross_trade_pnl_before_fees": float(run["gross_trade_pnl_before_fees"]),
        "net_trade_pnl_after_fees": float(run["net_trade_pnl_after_fees"]),
        "final_equity": float(run["final_equity"]),
        "open_positions_at_end": int(run["open_positions_at_end"]),
        "pending_orders_at_end": int(run["pending_orders_at_end"]),
    }
    return annual, summary


def utilization_row(slots: int, run: dict) -> dict:
    fields = [
        "total_signals", "skipped_no_free_slot", "skipped_duplicate_symbol",
        "pending_orders_created", "filled_orders", "expired_entry_orders",
        "capacity_limited_orders", "cash_limited_orders", "below_100_share_orders",
        "average_occupied_slots_eod", "peak_occupied_slots_eod",
        "order_creation_rate", "fill_per_signal_rate", "fill_per_created_order_rate",
    ]
    row = {"slots": slots}
    row.update({key: run[key] for key in fields})
    row["average_slot_occupancy_rate"] = float(run["average_occupied_slots_eod"] / slots)
    return row


def raw_signals(signals: pd.DataFrame, raw_all: pd.DataFrame) -> pd.DataFrame:
    raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    out = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if out.raw_close.isna().any():
        raise RuntimeError("Raw audit signal close missing")
    return out.rename(columns={"raw_close": "close"})


def report(grid: pd.DataFrame, annual: pd.DataFrame, utilization: pd.DataFrame, q1: pd.DataFrame, selection: dict, audit: dict) -> str:
    grid_lines = []
    for r in grid.sort_values("slots").itertuples(index=False):
        grid_lines.append(
            f"|{r.slots}|{r.strategy_cagr:.2%}|{r.annualized_excess:.2%}|{r.worst_annual_return:.2%}|"
            f"{r.mean_annual_return:.2%}|{r.worst_annual_excess:.2%}|{r.mean_annual_excess:.2%}|"
            f"{r.profitable_years}|{r.outperform_years}|{r.completed_trades}|{r.trade_count_cv_ddof0:.3f}|{r.total_fees:.2f}|{bool(r.hard_gate)}|"
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
            f"{r.pending_orders_created}|{r.filled_orders}|{r.expired_entry_orders}|{r.capacity_limited_orders}|"
            f"{r.cash_limited_orders}|{r.below_100_share_orders}|{r.average_occupied_slots_eod:.2f}|"
            f"{r.average_slot_occupancy_rate:.2%}|{r.order_creation_rate:.2%}|{r.fill_per_signal_rate:.2%}|"
        )
    q1_lines = []
    for r in q1.sort_values(["slots", "year"]).itertuples(index=False):
        q1_lines.append(
            f"|{r.slots}|{r.year}|{r.mean_strategy_return:.2%}|{r.mean_benchmark_return:.2%}|"
            f"{r.mean_excess_return:.2%}|{r.minimum_excess_return:.2%}|{r.positive_excess_fraction:.0%}|"
            f"{r.minimum_completed_trades}|{r.terminal_empty_fraction:.0%}|"
        )
    return f"""# 沪深智能1 Batch012：冻结 NEW 槽位数量网格

## 结论

本批严格只用 2024-12-31 及以前输入。NEW 公式、100% Top3 信号和所有成交规则冻结，只改变账户槽位数。预注册七档 `10/15/20/25/30/40/50` 全部保留，未按结果扩网格。

唯一摘要候选为 `{selection['selected_candidate']}`（{selection['selection_basis']}）。唯一原始 OHLC、完整 pre-2025 公司行动及退市复审状态为 `{audit['status']}`；数据完整性通过为 `{audit['data_integrity_pass']}`，原始口径收益硬门槛通过为 `{audit['raw_performance_gate_pass']}`。失败不重选。这些是 2020—2024 开发证据，不是盲测，不自动修改 NEW 或生产入口，也不下真实委托。

## 完整槽位网格

|槽位|CAGR|年化超额|最差年收益|平均年收益|最差年超额|平均年超额|盈利年|跑赢年|交易|交易频率CV|总费用|硬门槛|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
{chr(10).join(grid_lines)}

硬门槛按事前协议：五年逐年超额均为正、最差年度账户收益为正、各年共享Q1平均超额为正，并且完整窗口及全部共享Q1运行终态空仓且无挂单。硬门槛内依次按 CAGR、平均年度超额、最差年度超额、最差年度收益、较少槽位排序；若无人达标才使用预注册失败回退排序。

## 逐年收益、频率与费用

|槽位|年度|信号|完成交易|账户收益|上证收益|超额|费用|每笔平均费用|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(annual_lines)}

费用含买卖佣金与卖出印花税；滑点已进入实际成交价，因此不重复计入费用列。完成交易的毛/净损益另见 CSV；年度收益仍以账户逐年年末权益计算。

## 信号利用率

|槽位|总信号|无空槽跳过|同股跳过|创建挂单|成交|7日过期|容量限制|现金限制|不足100股|平均占槽|平均占槽率|信号利用率|信号成交率|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(util_lines)}

主信号利用率定义为“创建挂单/总信号”。计数只观察原执行状态，不改变成交；跳过分类先判同股，再判无空槽。平均占槽按每个评价交易日收盘、创建当日新挂单后采样，挂单与持仓均占槽。容量、现金和100股限制计数允许重叠。

## 共享 Q1 随机起点稳健性

复用 Batch010 固定的25个Q1起点，每年5个，七档共享，总计175次。

|槽位|年度|平均收益|平均上证|平均超额|最差超额|正超额比|最少交易|终态空仓比|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(q1_lines)}

## 文件与限制

- `full_slot_grid.csv`：完整七档综合结果；`annual_metrics.csv`：逐年结果；`signal_utilization.csv`：执行计数和信号利用率。
- `shared_q1_random_start_runs_175.csv` 与 `shared_q1_summary.csv`：固定共享起点明细与汇总。
- `SELECTION.json` 在原始审计前冻结唯一候选；`audit/FINAL_AUDIT.json` 记录原始OHLC、公司行动和退市覆盖。
- 上证综指是价格指数、不含股息；原始审计策略账户含已核验公司行动现金，比较口径局限保留。
- 原始审计账户 CAGR 为 `{audit['raw_summary']['strategy_cagr']:.2%}`、年化超额 `{audit['raw_summary']['annualized_excess']:.2%}`、最差年度收益 `{audit['raw_summary']['worst_annual_return']:.2%}`、最差年度超额 `{audit['raw_summary']['worst_annual_excess']:.2%}`。若原始口径破坏任一事前收益硬门槛，审计即记失败且不改选下一档。
"""


def main() -> int:
    protocol = validate_protocol()
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.min() < pd.Timestamp("2020-01-01") or panel.date.max() > LAST_SIGNAL_DATE:
        raise RuntimeError("Batch012 panel boundary violation")
    signals = b11.build_top3(panel).copy()
    signals["factor"] = "FROZEN_NEW"
    if signals.groupby("date").size().ne(3).any():
        raise RuntimeError("Batch012 is not exact frozen NEW Top3")

    bars, calendar = core.load_execution_bars(set(signals.symbol.astype(str)), force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch012 execution data crossed pre-2025 boundary")
    benchmark, benchmark_audit = batch6.load_benchmark()
    starts = b11.load_starts()
    benchmark_starts = b11.benchmark_start_returns(starts)

    grid_rows, annual_rows, utilization_rows, random_rows = [], [], [], []
    for index, slots in enumerate(SLOTS, 1):
        run, trades = core.simulate(
            signals, bars, calendar, "FROZEN_NEW", 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=True, slots=slots,
        )
        annual, summary = annual_and_summary(slots, signals, run, trades, benchmark)
        annual_rows.extend(annual)
        grid_rows.append(summary)
        utilization_rows.append(utilization_row(slots, run))
        for item in starts.itertuples(index=False):
            start = pd.Timestamp(item.start_date)
            window, _ = run_window(signals, bars, calendar, "FROZEN_NEW", slots, int(item.year), start)
            strategy_return = float(window[f"return_{int(item.year)}"])
            benchmark_return = benchmark_starts[(int(item.year), start)]
            random_rows.append({
                "slots": slots,
                "year": int(item.year),
                "start_rank": int(item.start_rank),
                "start_date": str(start.date()),
                "strategy_return": strategy_return,
                "benchmark_return": benchmark_return,
                "excess_return": strategy_return - benchmark_return,
                "completed_trades": int(window["completed_trades"]),
                "open_positions_at_end": int(window["open_positions_at_end"]),
                "pending_orders_at_end": int(window["pending_orders_at_end"]),
            })
        print(f"batch012 screening {index}/7 slots={slots}", flush=True)

    grid = pd.DataFrame(grid_rows)
    annual = pd.DataFrame(annual_rows)
    utilization = pd.DataFrame(utilization_rows)
    random_runs = pd.DataFrame(random_rows)
    if len(grid) != 7 or len(annual) != 35 or len(random_runs) != 175:
        raise RuntimeError("Batch012 output cardinality mismatch")
    q1 = random_runs.groupby(["slots", "year"], as_index=False).agg(
        mean_strategy_return=("strategy_return", "mean"),
        mean_benchmark_return=("benchmark_return", "mean"),
        mean_excess_return=("excess_return", "mean"),
        minimum_excess_return=("excess_return", "min"),
        positive_excess_fraction=("excess_return", lambda x: float((x > 0).mean())),
        minimum_completed_trades=("completed_trades", "min"),
        terminal_empty_fraction=("open_positions_at_end", lambda x: float((x == 0).mean())),
        pending_empty_fraction=("pending_orders_at_end", lambda x: float((x == 0).mean())),
    )
    hard_gate = []
    for row in grid.itertuples(index=False):
        ann = annual[annual.slots.eq(row.slots)]
        starts_group = q1[q1.slots.eq(row.slots)]
        hard_gate.append(bool(
            ann.excess_return.gt(0).all()
            and row.worst_annual_return > 0
            and starts_group.mean_excess_return.gt(0).all()
            and starts_group.terminal_empty_fraction.eq(1.0).all()
            and starts_group.pending_empty_fraction.eq(1.0).all()
            and row.open_positions_at_end == 0
            and row.pending_orders_at_end == 0
        ))
    grid["hard_gate"] = hard_gate
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
    random_runs.sort_values(["slots", "year", "start_rank"]).to_csv(RESULTS / "shared_q1_random_start_runs_175.csv", index=False, encoding="utf-8-sig")
    q1.sort_values(["slots", "year"]).to_csv(RESULTS / "shared_q1_summary.csv", index=False, encoding="utf-8-sig")

    selection = {
        "status": "unique_summary_candidate_frozen_pending_pre2025_raw_audit",
        "protocol_id": protocol["protocol_id"],
        "selected_candidate": selected_candidate,
        "selected_slots": selected_slots,
        "selection_basis": basis,
        "hard_gate_count": int(grid.hard_gate.sum()),
        "candidate_count": 7,
        "shared_q1_run_count": 175,
        "assertions": {
            "instruction_boundary_version": "public-pre2025-v1",
            "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()),
            "maximum_execution_date": str(max(calendar).date()),
            "exact_frozen_new_top3_100_percent": True,
            "all_slot_candidates_retained": True,
            "production_change": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL),
            "base_panel": sha256(BASE_PANEL),
            "benchmark": sha256(batch6.BENCHMARK),
            "starts": sha256(STARTS_FILE),
            "core_engine": sha256(RESEARCH / "run_batch.py"),
            "runner": sha256(Path(__file__)),
        },
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_dir = RESULTS / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(signals.symbol.astype(str)))
    if raw_all.date.max() > HARD_MAX_DATE or max(raw_calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch012 raw audit crossed pre-2025 boundary")
    raw_frame = raw_signals(signals, raw_all)
    actions, known = b11.load_verified_pre2025_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    raw_run, raw_trades = core.simulate(
        raw_frame, raw_bars, raw_calendar, "FROZEN_NEW", 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing,
        delist_dates=delistings, slots=selected_slots,
    )
    raw_trades.to_csv(audit_dir / "selected_candidate_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
    raw_annual, raw_summary = annual_and_summary(selected_slots, raw_frame, raw_run, raw_trades, benchmark)
    pd.DataFrame(raw_annual).to_csv(audit_dir / "selected_candidate_annual_metrics_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([utilization_row(selected_slots, raw_run)]).to_csv(audit_dir / "selected_candidate_signal_utilization_raw.csv", index=False, encoding="utf-8-sig")

    raw_start_rows = []
    for item in starts.itertuples(index=False):
        start = pd.Timestamp(item.start_date)
        window, _ = run_window(
            raw_frame, raw_bars, raw_calendar, "FROZEN_NEW", selected_slots, int(item.year), start,
            raw=True, actions=actions, known=known, coverage=missing, delistings=delistings,
        )
        strategy_return = float(window[f"return_{int(item.year)}"])
        benchmark_return = benchmark_starts[(int(item.year), start)]
        raw_start_rows.append({
            "slots": selected_slots,
            "year": int(item.year),
            "start_rank": int(item.start_rank),
            "start_date": str(start.date()),
            "strategy_return": strategy_return,
            "benchmark_return": benchmark_return,
            "excess_return": strategy_return - benchmark_return,
            "completed_trades": int(window["completed_trades"]),
            "open_positions_at_end": int(window["open_positions_at_end"]),
            "pending_orders_at_end": int(window["pending_orders_at_end"]),
        })
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(audit_dir / "selected_candidate_shared_q1_raw_25.csv", index=False, encoding="utf-8-sig")
    data_integrity_pass = bool(
        not missing
        and raw_all.date.max() <= HARD_MAX_DATE
        and max(raw_calendar) <= HARD_MAX_DATE
        and raw_run["open_positions_at_end"] == 0
        and raw_run["pending_orders_at_end"] == 0
        and raw_starts.open_positions_at_end.eq(0).all()
        and raw_starts.pending_orders_at_end.eq(0).all()
    )
    raw_annual_frame = pd.DataFrame(raw_annual)
    raw_q1_year_mean = raw_starts.groupby("year").excess_return.mean()
    raw_performance_gate_pass = bool(
        raw_annual_frame.excess_return.gt(0).all()
        and float(raw_summary["worst_annual_return"]) > 0
        and raw_q1_year_mean.gt(0).all()
    )
    audit_pass = bool(data_integrity_pass and raw_performance_gate_pass)
    audit = {
        "status": "complete" if audit_pass else "audit_failed_no_reselection",
        "audited_candidate": selected_candidate,
        "audited_slots": selected_slots,
        "selection_basis": basis,
        "audit_did_not_trigger_reselection": True,
        "data_integrity_pass": data_integrity_pass,
        "raw_performance_gate_pass": raw_performance_gate_pass,
        "raw_summary": raw_summary,
        "raw_signal_utilization": utilization_row(selected_slots, raw_run),
        "missing_corporate_action_keys": sorted(missing),
        "raw_q1": {
            "run_count": int(len(raw_starts)),
            "positive_excess_fraction": float((raw_starts.excess_return > 0).mean()),
            "minimum_excess": float(raw_starts.excess_return.min()),
            "mean_excess_by_year": {str(int(year)): float(value) for year, value in raw_q1_year_mean.items()},
            "all_terminal_empty": bool(raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()),
        },
        "assertions": {
            "maximum_raw_date": str(raw_all.date.max().date()),
            "maximum_execution_date": str(max(raw_calendar).date()),
            "pre2025_boundary_passed": True,
            "corporate_action_coverage_complete": not missing,
            "delisting_rules_loaded": bool(delistings),
            "production_change": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL),
            "selection": sha256(RESULTS / "SELECTION.json"),
            "runner": sha256(Path(__file__)),
            "base_actions": sha256(prior_audit.ACTIONS_BASE),
            "batch006_actions": sha256(b11.audit6.EASTMONEY_ACTIONS),
            "batch007_actions": sha256(PROJECT / "results" / "batch_007_pre2025_start_robustness" / "audit" / "eastmoney_actions.json"),
            "batch010_actions": sha256(PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "audit" / "eastmoney_actions.json"),
            "delisting_metadata": sha256(prior_audit.METADATA),
        },
    }
    (audit_dir / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    final = {
        **selection,
        "status": "complete_research_only_no_production_change" if audit_pass else "complete_screening_raw_audit_failed_no_reselection",
        "audit_status": audit["status"],
    }
    (RESULTS / "FINAL_SELECTION.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "REPORT.md").write_text(report(grid, annual, utilization, q1, selection, audit), encoding="utf-8")
    print(json.dumps({"selected": selected_candidate, "hard_gate_count": int(grid.hard_gate.sum()), "audit": audit["status"]}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
