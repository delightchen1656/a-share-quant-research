from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd


RESULTS = Path(__file__).resolve().parent
PROJECT = RESULTS.parents[1]
RESEARCH = PROJECT / "research"
sys.path.insert(0, str(RESEARCH))
import run_batch as core  # noqa: E402
import run_batch_004 as batch4  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import run_batch_007_pre2025 as batch7  # noqa: E402
import audit_batch_006 as audit6  # noqa: E402
import audit_champion as prior_audit  # noqa: E402


PROTOCOL = PROJECT / "protocol" / "BATCH_011_PRE2025_NEW_THRESHOLD_GRID.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
STARTS_FILE = PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "sampled_start_dates.csv"
YEARS = [2020, 2021, 2022, 2023, 2024]
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
LAST_SIGNAL_DATE = pd.Timestamp("2024-11-22")
NEW_SPEC = {
    "M_internal": [0.5, 0.5, 0.0],
    "T_internal": [0.5, 0.0, 0.5, 0.0],
    "H_internal": [0.25, 0.25, 0.5, 0.0],
    "outer": [0.6, 0.0, 0.4],
}


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
    if p.get("status") != "preregistered_before_batch_011_results":
        raise RuntimeError("Batch011 protocol was not preregistered")
    if p.get("instruction_boundary_version") != "public-pre2025-v1" or not p.get("post_2024_forbidden"):
        raise RuntimeError("Batch011 isolation boundary mismatch")
    grid = p["threshold_grid"]
    if grid["target_retention_percent"] != list(range(100, 0, -10)):
        raise RuntimeError("Batch011 retention grid changed")
    if grid["historical_quantile"] != [x / 10 for x in range(10)]:
        raise RuntimeError("Batch011 quantile grid changed")
    if grid["candidate_count"] != 10 or grid["window_trading_dates"] != 252 or grid["min_prior_trading_dates"] != 20:
        raise RuntimeError("Batch011 threshold protocol changed")
    return p


def build_top3(panel: pd.DataFrame) -> pd.DataFrame:
    out = batch4.candidate_signals(
        panel,
        "FROZEN_NEW",
        batch4.component_m(panel, tuple(NEW_SPEC["M_internal"])),
        batch4.component_t(panel, tuple(NEW_SPEC["T_internal"])),
        batch4.component_h(panel, tuple(NEW_SPEC["H_internal"])),
        tuple(NEW_SPEC["outer"]),
    )
    if out.groupby("date").size().ne(3).any():
        raise RuntimeError("Frozen NEW does not have exactly Top3 on every effective signal date")
    return out


def threshold_candidates(top3: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    candidates: dict[str, list[pd.DataFrame]] = {f"R{r:03d}_Q{100-r:02d}": [] for r in range(100, 0, -10)}
    threshold_rows: list[dict] = []
    history: deque[np.ndarray] = deque(maxlen=252)
    groups = list(top3.groupby("date", sort=True))
    for date_index, (date, today) in enumerate(groups):
        prior = np.concatenate(list(history)) if history else np.array([], dtype=float)
        prior_dates = len(history)
        for retention in range(100, 0, -10):
            candidate = f"R{retention:03d}_Q{100-retention:02d}"
            quantile = (100 - retention) / 100.0
            cold = retention < 100 and prior_dates < 20
            if retention == 100 or cold:
                threshold = -math.inf
                kept = today.copy()
            else:
                threshold = float(np.quantile(prior, quantile, method="linear"))
                kept = today[today.score.ge(threshold)].copy()
            kept["factor"] = candidate
            candidates[candidate].append(kept)
            threshold_rows.append({
                "candidate": candidate,
                "target_retention_percent": retention,
                "historical_quantile": quantile,
                "date": date,
                "prior_distinct_signal_dates": prior_dates,
                "prior_score_observations": int(len(prior)),
                "cold_start_all_retained": bool(cold),
                "threshold": None if not np.isfinite(threshold) else threshold,
                "top3_count": int(len(today)),
                "retained_count": int(len(kept)),
            })
        history.append(today.score.to_numpy(dtype=float))
    frames = {
        key: pd.concat(parts, ignore_index=True).sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")
        for key, parts in candidates.items()
    }
    thresholds = pd.DataFrame(threshold_rows)
    if len(frames) != 10 or len(thresholds) != len(groups) * 10:
        raise RuntimeError("Batch011 fixed threshold grid count mismatch")
    base = frames["R100_Q00"]
    if len(base) != len(top3) or not base[["date", "symbol", "score"]].reset_index(drop=True).equals(top3[["date", "symbol", "score"]].reset_index(drop=True)):
        raise RuntimeError("100% baseline is not identical to frozen NEW Top3")
    return frames, thresholds


def load_starts() -> pd.DataFrame:
    starts = pd.read_csv(STARTS_FILE)
    starts["start_date"] = pd.to_datetime(starts.start_date)
    if len(starts) != 25 or starts.groupby("year").start_date.nunique().ne(5).any() or set(starts.year) != set(YEARS):
        raise RuntimeError("Batch010 fixed Q1 starts invalid")
    if starts.start_date.max() > HARD_MAX_DATE:
        raise RuntimeError("Q1 starts crossed pre-2025 boundary")
    return starts


def benchmark_start_returns(starts: pd.DataFrame) -> dict[tuple[int, pd.Timestamp], float]:
    frame = pd.read_parquet(batch6.BENCHMARK).sort_values("date")
    frame["date"] = pd.to_datetime(frame.date)
    frame["close"] = pd.to_numeric(frame.close, errors="raise")
    if frame.empty or frame.date.max() > HARD_MAX_DATE:
        raise RuntimeError("Benchmark crossed pre-2025 boundary")
    result = {}
    for item in starts.itertuples(index=False):
        start = pd.Timestamp(item.start_date)
        before = frame.loc[frame.date < start, "close"]
        year_end = frame.loc[frame.date.dt.year.eq(int(item.year)), "close"]
        if before.empty or year_end.empty:
            raise RuntimeError(f"Benchmark coverage missing for {start.date()}")
        result[(int(item.year), start)] = float(year_end.iloc[-1] / before.iloc[-1] - 1.0)
    return result


def run_window(signals, bars, calendar, candidate, year, start, *, raw=False, actions=None, known=None, coverage=None, delistings=None):
    last_session = max(date for date in calendar if date.year == year)
    cutoff = pd.Timestamp(f"{year}-12-31") - pd.Timedelta(days=37)
    selected = signals[signals.date.between(start, cutoff)].copy()
    old = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = start, last_session, cutoff, [year]
        return core.simulate(
            selected, bars, calendar, candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            actions=actions if raw else None, known_action_keys=known if raw else None,
            coverage_sink=coverage if raw else None, delist_dates=delistings if raw else None,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old


def annual_and_summary(candidate: str, signals: pd.DataFrame, run: dict, benchmark: dict[int, float]) -> tuple[list[dict], dict]:
    annual = []
    counts = []
    returns = []
    excesses = []
    for year in YEARS:
        part = signals[signals.date.dt.year.eq(year)]
        count = int(len(part))
        days = int(part.date.nunique())
        strategy = float(run[f"return_{year}"])
        excess = strategy - float(benchmark[year])
        counts.append(count)
        returns.append(strategy)
        excesses.append(excess)
        annual.append({
            "candidate": candidate,
            "target_retention_percent": int(candidate[1:4]),
            "year": year,
            "signal_count": count,
            "signal_days": days,
            "mean_signals_per_signal_day": float(count / days) if days else 0.0,
            "completed_trades": int(run[f"trades_{year}"]),
            "strategy_return": strategy,
            "benchmark_return": float(benchmark[year]),
            "excess_return": excess,
        })
    count_array = np.asarray(counts, dtype=float)
    summary = {
        "candidate": candidate,
        "target_retention_percent": int(candidate[1:4]),
        "historical_quantile": (100 - int(candidate[1:4])) / 100.0,
        "signal_count_total": int(sum(counts)),
        "realized_retention_vs_baseline": np.nan,
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
        "open_positions_at_end": int(run["open_positions_at_end"]),
        "pending_orders_at_end": int(run["pending_orders_at_end"]),
        "final_equity": float(run["final_equity"]),
    }
    return annual, summary


def raw_signals(signals: pd.DataFrame, raw_all: pd.DataFrame) -> pd.DataFrame:
    raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    out = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if out.raw_close.isna().any():
        raise RuntimeError("Raw audit signal close missing")
    return out.rename(columns={"raw_close": "close"})


def load_verified_pre2025_actions() -> tuple[dict, set[str]]:
    """Merge the already verified, pre-2025-only action supplements used by prior public batches."""
    actions, known = audit6.load_actions()
    supplements = [
        PROJECT / "results" / "batch_007_pre2025_start_robustness" / "audit" / "eastmoney_actions.json",
        PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "audit" / "eastmoney_actions.json",
    ]
    for path in supplements:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cutoff") != "2024-12-31":
            raise RuntimeError(f"Non-pre2025 corporate-action supplement: {path}")
        for key, records in payload.get("records", {}).items():
            symbol = key.split("/")[0]
            known.add(key)
            for item in records:
                date = pd.Timestamp(item["dividOperateDate"]).normalize()
                if date > HARD_MAX_DATE:
                    raise RuntimeError(f"Corporate-action supplement crossed pre-2025 boundary: {path}")
                event = {
                    "cash": prior_audit.number(item.get("dividCashPsBeforeTax", 0)),
                    "stock": prior_audit.number(item.get("dividStocksPs", 0)) + prior_audit.number(item.get("dividReserveToStockPs", 0)),
                    "taxable_stock": prior_audit.number(item.get("dividStocksPs", 0)),
                    "pay": pd.Timestamp(item.get("dividPayDate") or item["dividOperateDate"]).normalize(),
                    "release": pd.Timestamp(item.get("dividStockMarketDate") or item["dividOperateDate"]).normalize(),
                    "source": item.get("source", "Eastmoney stock_fhps_em via AkShare"),
                }
                identity = (event["cash"], event["stock"], event["taxable_stock"], event["pay"], event["release"])
                existing = actions.setdefault((date, symbol), [])
                existing_ids = {(x.get("cash", 0.0), x.get("stock", 0.0), x.get("taxable_stock", 0.0), x.get("pay", date), x.get("release", date)) for x in existing}
                if identity not in existing_ids:
                    existing.append(event)
    return actions, known


def markdown_report(grid: pd.DataFrame, annual: pd.DataFrame, q1_summary: pd.DataFrame, selection: dict, audit: dict) -> str:
    lines = []
    for row in grid.sort_values("target_retention_percent", ascending=False).itertuples(index=False):
        lines.append(
            f"|{row.target_retention_percent}%|{row.signal_count_total}|{row.realized_retention_vs_baseline:.2%}|"
            f"{row.strategy_cagr:.2%}|{row.annualized_excess:.2%}|{row.worst_annual_return:.2%}|"
            f"{row.mean_annual_return:.2%}|{row.worst_annual_excess:.2%}|{row.mean_annual_excess:.2%}|"
            f"{row.profitable_years}|{row.outperform_years}|{row.annual_signal_frequency_cv_ddof0:.3f}|"
        )
    yearly = []
    for row in annual.sort_values(["target_retention_percent", "year"], ascending=[False, True]).itertuples(index=False):
        yearly.append(
            f"|{row.target_retention_percent}%|{row.year}|{row.signal_count}|{row.signal_days}|"
            f"{row.mean_signals_per_signal_day:.3f}|{row.completed_trades}|{row.strategy_return:.2%}|"
            f"{row.benchmark_return:.2%}|{row.excess_return:.2%}|"
        )
    qlines = []
    for row in q1_summary.sort_values(["target_retention_percent", "year"], ascending=[False, True]).itertuples(index=False):
        qlines.append(
            f"|{row.target_retention_percent}%|{row.year}|{row.mean_strategy_return:.2%}|{row.mean_benchmark_return:.2%}|"
            f"{row.mean_excess_return:.2%}|{row.minimum_excess_return:.2%}|{row.positive_excess_fraction:.0%}|"
            f"{row.minimum_completed_trades}|{row.terminal_empty_fraction:.0%}|"
        )
    migration = selection["migration_priority_candidate"]
    returns = selection["return_priority_candidate"]
    status = audit["status"]
    return f"""# 沪深智能1 Batch011：冻结 NEW 因果动态阈值等频网格

## 结论

本批严格只用 2024-12-31 及以前输入。NEW 公式、每日 Top3 排序及 30 自然日账户执行全部冻结，只更改信号阈值。预注册 10 档目标保留率全部保留，没有看结果扩展网格。

迁移优先候选为 `{migration}`；收益优先候选为 `{returns}`。唯一原始 OHLC/公司行动摘要复审对象为 `{audit['audited_candidate']}`，状态为 `{status}`。这些都是 2020—2024 开发证据，不是盲测，不自动替换 NEW、不修改生产、不下真实委托。

## 因果阈值口径

- 每日先按冻结 NEW 计算并稳定排序 Top3，再对这 3 个 score 用门槛过滤，允许 0—3 信号。
- 门槛只用当日前 252 个信号交易日的 Top3 score 分布，严格 `shift(1)`；分位数为 0%、10%、…、90%，对应目标保留率 100%、90%、…、10%。
- 核验面板无 2020 年以前评分历史，禁止未来回填。预注册冷启动为：前 20 个信号交易日全保留；第 21 日起用全部已有历史，达 252 日后滚动。
- 基准 100% 不计算有限样本最小值门槛，逐行断言与原 NEW Top3 完全一致。

## 完整网格总结

|目标保留|信号|实际保留|CAGR|年化超额|最差年收益|平均年收益|最差年超额|平均年超额|盈利年|跑赢年|频率CV|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

## 逐年结果

|目标保留|年度|信号|信号日|每信号日均值|完成交易|账户收益|上证收益|超额|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(yearly)}

## 共享 Q1 随机起点

复用 Batch010 事先固定的 25 个起点，每年 5 个，所有阈值共享；总计 250 次。

|目标保留|年度|平均收益|平均指数|平均超额|最差超额|正超额比|最少交易|终态空仓比|
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(qlines)}

## 执行、审计与限制

- 账户保持 10 万元、10 槽、7 自然日买单、entry 0 ATR、take 4 ATR、stop 1.5 ATR、30 自然日、T+1、双触止损优先、2% 容量及原费率滑点。
- 指数是上证综指价格指数，不含股息；原始审计策略账户含已核验公司行动现金，比较口径局限保留。
- 原始审计只对预注册唯一摘要候选执行；失败不重选。详见 `audit/FINAL_AUDIT.json`。
- 完整数据见 `full_threshold_grid.csv`、`annual_metrics.csv`、`daily_thresholds.csv`、`shared_q1_random_start_runs_250.csv` 和 `shared_q1_summary.csv`。
"""


def main() -> int:
    protocol = validate_protocol()
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.min() < pd.Timestamp("2020-01-01") or panel.date.max() > LAST_SIGNAL_DATE:
        raise RuntimeError("Batch011 panel boundary violation")
    top3 = build_top3(panel)
    signals, thresholds = threshold_candidates(top3)
    thresholds.to_csv(RESULTS / "daily_thresholds.csv", index=False, encoding="utf-8-sig")

    symbols = set(top3.symbol.astype(str))
    bars, calendar = core.load_execution_bars(symbols, force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch011 execution data crossed pre-2025 boundary")
    benchmark, benchmark_audit = batch6.load_benchmark()
    starts = load_starts()
    benchmark_starts = benchmark_start_returns(starts)

    grid_rows, annual_rows, random_rows = [], [], []
    for i, (candidate, frame) in enumerate(signals.items(), 1):
        run, _ = core.simulate(frame, bars, calendar, candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5)
        annual, summary = annual_and_summary(candidate, frame, run, benchmark)
        annual_rows.extend(annual)
        grid_rows.append(summary)
        for item in starts.itertuples(index=False):
            start = pd.Timestamp(item.start_date)
            window, _ = run_window(frame, bars, calendar, candidate, int(item.year), start)
            strategy_return = float(window[f"return_{int(item.year)}"])
            benchmark_return = benchmark_starts[(int(item.year), start)]
            random_rows.append({
                "candidate": candidate,
                "target_retention_percent": int(candidate[1:4]),
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
        print(f"batch011 screening {i}/10 {candidate}", flush=True)

    grid = pd.DataFrame(grid_rows)
    annual = pd.DataFrame(annual_rows)
    random_runs = pd.DataFrame(random_rows)
    if len(grid) != 10 or len(annual) != 50 or len(random_runs) != 250:
        raise RuntimeError("Batch011 output cardinality mismatch")
    base_count = int(grid.loc[grid.candidate.eq("R100_Q00"), "signal_count_total"].iloc[0])
    grid["realized_retention_vs_baseline"] = grid.signal_count_total / base_count
    q1 = random_runs.groupby(["candidate", "target_retention_percent", "year"], as_index=False).agg(
        mean_strategy_return=("strategy_return", "mean"),
        mean_benchmark_return=("benchmark_return", "mean"),
        mean_excess_return=("excess_return", "mean"),
        minimum_excess_return=("excess_return", "min"),
        positive_excess_fraction=("excess_return", lambda x: float((x > 0).mean())),
        minimum_completed_trades=("completed_trades", "min"),
        terminal_empty_fraction=("open_positions_at_end", lambda x: float((x == 0).mean())),
        pending_empty_fraction=("pending_orders_at_end", lambda x: float((x == 0).mean())),
    )
    robust = []
    for row in grid.itertuples(index=False):
        ann = annual[annual.candidate.eq(row.candidate)]
        starts_group = q1[q1.candidate.eq(row.candidate)]
        ok = bool(
            ann.strategy_return.gt(0).all() and ann.excess_return.gt(0).all()
            and starts_group.mean_excess_return.gt(0).all()
            and starts_group.terminal_empty_fraction.eq(1.0).all()
            and starts_group.pending_empty_fraction.eq(1.0).all()
            and row.open_positions_at_end == 0 and row.pending_orders_at_end == 0
        )
        robust.append(ok)
    grid["robust_pool"] = robust
    q1_min = q1.groupby("candidate").mean_excess_return.min().rename("minimum_year_mean_q1_excess")
    grid = grid.merge(q1_min, on="candidate", validate="one_to_one")
    migration_pool = grid[grid.robust_pool].copy()
    if migration_pool.empty:
        migration_candidate = None
    else:
        migration_candidate = str(migration_pool.sort_values(
            ["worst_annual_excess", "minimum_year_mean_q1_excess", "annualized_excess", "annual_signal_frequency_cv_ddof0", "target_retention_percent", "candidate"],
            ascending=[False, False, False, True, True, True], kind="stable",
        ).iloc[0].candidate)
    return_candidate = str(grid.sort_values(
        ["strategy_cagr", "annualized_excess", "worst_annual_excess", "candidate"],
        ascending=[False, False, False, True], kind="stable",
    ).iloc[0].candidate)
    audited_candidate = migration_candidate or return_candidate

    grid.sort_values("target_retention_percent", ascending=False).to_csv(RESULTS / "full_threshold_grid.csv", index=False, encoding="utf-8-sig")
    annual.sort_values(["target_retention_percent", "year"], ascending=[False, True]).to_csv(RESULTS / "annual_metrics.csv", index=False, encoding="utf-8-sig")
    random_runs.sort_values(["target_retention_percent", "year", "start_rank"], ascending=[False, True, True]).to_csv(RESULTS / "shared_q1_random_start_runs_250.csv", index=False, encoding="utf-8-sig")
    q1.sort_values(["target_retention_percent", "year"], ascending=[False, True]).to_csv(RESULTS / "shared_q1_summary.csv", index=False, encoding="utf-8-sig")

    selection = {
        "status": "summary_candidates_frozen_pending_pre2025_raw_audit",
        "protocol_id": protocol["protocol_id"],
        "migration_priority_candidate": migration_candidate,
        "return_priority_candidate": return_candidate,
        "audited_candidate": audited_candidate,
        "robust_pool_count": int(grid.robust_pool.sum()),
        "candidate_count": 10,
        "shared_q1_run_count": 250,
        "assertions": {
            "instruction_boundary_version": "public-pre2025-v1",
            "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()),
            "maximum_execution_date": str(max(calendar).date()),
            "baseline_exactly_frozen_new_top3": True,
            "all_thresholds_retained": True,
            "production_change": False,
        },
        "source_hashes": {"protocol": sha256(PROTOCOL), "base_panel": sha256(BASE_PANEL), "benchmark": sha256(batch6.BENCHMARK), "runner": sha256(Path(__file__))},
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    audit_dir = RESULTS / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    frame = signals[audited_candidate]
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(frame.symbol.astype(str)))
    if raw_all.date.max() > HARD_MAX_DATE or max(raw_calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch011 raw audit crossed pre-2025 boundary")
    raw_frame = raw_signals(frame, raw_all)
    actions, known = load_verified_pre2025_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    raw_run, raw_trades = core.simulate(
        raw_frame, raw_bars, raw_calendar, audited_candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing, delist_dates=delistings,
    )
    raw_trades.to_csv(audit_dir / "summary_candidate_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
    raw_annual, raw_summary = annual_and_summary(audited_candidate, raw_frame, raw_run, benchmark)
    raw_summary["realized_retention_vs_baseline"] = float(len(raw_frame) / len(raw_frame))
    pd.DataFrame(raw_annual).to_csv(audit_dir / "summary_candidate_annual_metrics_raw.csv", index=False, encoding="utf-8-sig")
    raw_start_rows = []
    for item in starts.itertuples(index=False):
        start = pd.Timestamp(item.start_date)
        window, _ = run_window(raw_frame, raw_bars, raw_calendar, audited_candidate, int(item.year), start, raw=True, actions=actions, known=known, coverage=missing, delistings=delistings)
        strategy_return = float(window[f"return_{int(item.year)}"])
        benchmark_return = benchmark_starts[(int(item.year), start)]
        raw_start_rows.append({
            "candidate": audited_candidate, "year": int(item.year), "start_rank": int(item.start_rank), "start_date": str(start.date()),
            "strategy_return": strategy_return, "benchmark_return": benchmark_return, "excess_return": strategy_return - benchmark_return,
            "completed_trades": int(window["completed_trades"]), "open_positions_at_end": int(window["open_positions_at_end"]),
            "pending_orders_at_end": int(window["pending_orders_at_end"]),
        })
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(audit_dir / "summary_candidate_shared_q1_raw_25.csv", index=False, encoding="utf-8-sig")
    audit_pass = bool(
        not missing and raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE
        and raw_run["open_positions_at_end"] == 0 and raw_run["pending_orders_at_end"] == 0
        and raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()
    )
    audit = {
        "status": "complete" if audit_pass else "audit_failed_no_reselection",
        "audited_candidate": audited_candidate,
        "selection_basis": "migration_priority" if migration_candidate else "return_priority_fallback",
        "audit_did_not_trigger_reselection": True,
        "raw_summary": raw_summary,
        "missing_corporate_action_keys": sorted(missing),
        "raw_q1": {
            "run_count": int(len(raw_starts)),
            "positive_excess_fraction": float((raw_starts.excess_return > 0).mean()),
            "minimum_excess": float(raw_starts.excess_return.min()),
            "all_terminal_empty": bool(raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()),
        },
        "assertions": {
            "maximum_raw_date": str(raw_all.date.max().date()),
            "maximum_execution_date": str(max(raw_calendar).date()),
            "pre2025_boundary_passed": True,
            "corporate_action_coverage_complete": not missing,
            "production_change": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL),
            "selection": sha256(RESULTS / "SELECTION.json"),
            "runner": sha256(Path(__file__)),
            "base_actions": sha256(prior_audit.ACTIONS_BASE),
            "batch006_actions": sha256(audit6.EASTMONEY_ACTIONS),
            "batch007_actions": sha256(PROJECT / "results" / "batch_007_pre2025_start_robustness" / "audit" / "eastmoney_actions.json"),
            "batch010_actions": sha256(PROJECT / "results" / "batch_010_pre2025_new_active_floor" / "audit" / "eastmoney_actions.json"),
        },
    }
    (audit_dir / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    final = {**selection, "status": "complete_research_only_no_production_change" if audit_pass else "complete_screening_raw_audit_failed_no_reselection", "audit_status": audit["status"]}
    (RESULTS / "FINAL_SELECTION.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS / "REPORT.md").write_text(markdown_report(grid, annual, q1, selection, audit), encoding="utf-8")
    print(json.dumps({"migration": migration_candidate, "return": return_candidate, "audited": audited_candidate, "audit": audit["status"]}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
