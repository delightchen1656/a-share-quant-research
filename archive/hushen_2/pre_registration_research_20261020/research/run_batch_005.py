from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_002 as batch2  # noqa: E402
import run_batch_004 as batch4  # noqa: E402


PROJECT = core.PROJECT
PROTOCOL = PROJECT / "protocol" / "BATCH_005.json"
RESULTS = PROJECT / "results" / "batch_005_pre2025_signal_filters"
BATCH4_AUDIT = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "audit" / "FINAL_AUDIT.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"

M_WEIGHTS = (0.25, 0.75, 0.0)
T_WEIGHTS = (0.50, 0.25, 0.25, 0.0)
H_WEIGHTS = (0.25, 0.25, 0.25, 0.25)
OUTER_WEIGHTS = (0.30, 0.30, 0.40)
QUANTILES = tuple(round(0.50 + 0.05 * i, 2) for i in range(10))


def load_protocol() -> dict:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    experiments = {item["name"]: item for item in p["experiments"]}
    if not p["post_2024_forbidden"] or p["separation_controls"]["total_screening_runs"] != 13:
        raise RuntimeError("Batch005 boundary or run-count registration changed")
    if experiments["count_only"]["maximum_daily_signals"] != [1, 2, 3]:
        raise RuntimeError("Count-only grid changed")
    if tuple(experiments["threshold_only"]["rolling_quantiles"]) != QUANTILES:
        raise RuntimeError("Threshold-only grid changed")
    if experiments["threshold_only"]["maximum_daily_signals"] != 3:
        raise RuntimeError("Threshold-only K changed")
    frozen = p["frozen_factor_spec"]
    if tuple(frozen["M_internal_utility_pen025_pen100"]) != M_WEIGHTS:
        raise RuntimeError("Frozen M weights changed")
    if tuple(frozen["T_internal_mom120_close_high60_mom20_neg_vol60"]) != T_WEIGHTS:
        raise RuntimeError("Frozen T weights changed")
    if tuple(frozen["H_internal_neg_size_neg_vol60_overnight_neg_intraday"]) != H_WEIGHTS:
        raise RuntimeError("Frozen H weights changed")
    if tuple(frozen["outer_M_T_H"]) != OUTER_WEIGHTS:
        raise RuntimeError("Frozen outer weights changed")
    return p


def load_scored_development_panel() -> pd.DataFrame:
    if not BASE_PANEL.exists():
        raise FileNotFoundError(BASE_PANEL)
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.min() < core.EVAL_START or panel.date.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Batch004 base panel date boundary failed")
    m = batch4.component_m(panel, M_WEIGHTS)
    t = batch4.component_t(panel, T_WEIGHTS)
    h = batch4.component_h(panel, H_WEIGHTS)
    out = panel[["date", "symbol", "close", "atr_pct"]].copy()
    out["score"] = OUTER_WEIGHTS[0] * m + OUTER_WEIGHTS[1] * t + OUTER_WEIGHTS[2] * h
    return out.dropna(subset=["score"]).sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)


def load_warmup_panel() -> pd.DataFrame:
    """Build only 2018-2019 score history; parquet filters prevent post-2019 row reads."""
    rows: list[pd.DataFrame] = []
    columns = [
        "date", "open", "high", "low", "close", "preclose", "volume",
        "amount", "turn", "tradestatus", "isST", "symbol",
    ]
    paths = sorted(core.QFQ_ROOT.glob("*/*.parquet"))
    if not paths:
        raise FileNotFoundError(core.QFQ_ROOT)
    for i, path in enumerate(paths, 1):
        b = pd.read_parquet(
            path,
            columns=columns,
            filters=[("date", ">=", core.FEATURE_START), ("date", "<", core.EVAL_START)],
        )
        if b.empty:
            continue
        b["date"] = pd.to_datetime(b.date)
        if b.date.max() >= core.EVAL_START:
            raise RuntimeError("Warmup read crossed into the development period")
        b = b.sort_values("date").reset_index(drop=True)
        if len(b) < 120:
            continue
        for col in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST"]:
            b[col] = pd.to_numeric(b[col], errors="coerce")
        ret = (b.close / b.preclose - 1.0).where(b.tradestatus.eq(1))
        filled = ret.fillna(0.0)
        chain = (1.0 + filled).cumprod()
        prior = chain.shift(1)
        adj_high = chain * (b.high / b.close)
        adj_low = chain * (b.low / b.close)
        tr = pd.concat(
            [adj_high - adj_low, (adj_high - prior).abs(), (adj_low - prior).abs()], axis=1
        ).max(axis=1) / prior
        f = pd.DataFrame(index=b.index)
        for length in [1, 5, 20, 60]:
            f[f"f_ret{length}"] = chain / chain.shift(length) - 1.0
        f["f_vol20"] = ret.rolling(20, min_periods=3).std()
        f["f_ma20"] = chain / chain.rolling(20, min_periods=3).mean() - 1.0
        f["f_amount_ratio5"] = b.amount / b.amount.rolling(5, min_periods=3).mean()
        f["f_log_amount"] = np.log1p(b.amount)
        f["f_log_price"] = np.log(b.close)
        f["f_turn"] = b.turn
        f["f_range"] = (b.high - b.low) / b.preclose
        f["f_downside20"] = ret.clip(upper=0).pow(2).rolling(20, min_periods=3).mean().pow(0.5)
        f["f_ohlc_rsi14"] = filled.clip(lower=0).rolling(14, min_periods=3).sum() / filled.abs().rolling(14, min_periods=3).sum()
        f["f_ohlc_atr_compress5_20"] = tr.rolling(5, min_periods=3).mean() / tr.rolling(20, min_periods=3).mean()
        close_ret = b.close.pct_change(fill_method=None)
        f["vol60"] = close_ret.rolling(60, min_periods=60).std(ddof=0)
        f["mom20"] = b.close / b.close.shift(20) - 1.0
        f["mom120"] = b.close / b.close.shift(120) - 1.0
        f["close_to_high60"] = b.close / b.close.rolling(60, min_periods=60).max() - 1.0
        f["overnight20"] = (b.open / b.preclose - 1.0).rolling(20, min_periods=20).mean()
        f["intraday20"] = (b.close / b.open - 1.0).rolling(20, min_periods=20).mean()
        f["vol60_tech"] = close_ret.rolling(60, min_periods=60).std(ddof=0)
        f["date"] = b.date
        f["symbol"] = b.symbol.astype(str)
        f["obs"] = np.arange(1, len(b) + 1)
        f["close"] = b.close
        f["amount"] = b.amount
        f["amount_med20"] = b.amount.rolling(20, min_periods=20).median()
        f["isST"] = b.isST
        f["tradestatus"] = b.tradestatus
        mask = (
            f.obs.ge(120) & f.close.between(2.0, 80.0) & f.amount.ge(20_000_000)
            & f.amount_med20.ge(30_000_000) & f.isST.eq(0) & f.tradestatus.eq(1)
        )
        keep = [
            "date", "symbol", "close", "vol60", "mom20", "mom120", "close_to_high60",
            "overnight20", "intraday20", "vol60_tech",
        ] + batch2.MODEL_FEATURES
        out = f.loc[mask, keep].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if not out.empty:
            rows.append(out)
        if i % 500 == 0:
            print(f"batch005 warmup files {i}/{len(paths)}", flush=True)
    if not rows:
        raise RuntimeError("No eligible warmup score rows")
    panel = pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)
    for name in ["utility", "pen025", "pen100"]:
        model = lgb.Booster(model_file=str(batch2.MODEL_DIR / f"{name}.txt"))
        if model.feature_name() != batch2.MODEL_FEATURES:
            raise RuntimeError(f"Feature mismatch for frozen model {name}")
        panel[name] = model.predict(panel[batch2.MODEL_FEATURES], num_threads=4)
    panel["cap_proxy_log"] = panel.f_log_amount - np.log(panel.f_turn.clip(lower=1e-6))
    ranks = batch4.rank_center(
        panel,
        ["mom120", "close_to_high60", "mom20", "vol60", "cap_proxy_log", "vol60_tech", "overnight20", "intraday20"],
    )
    panel["t_mom120_pos"] = ranks.mom120
    panel["t_high60_pos"] = ranks.close_to_high60
    panel["t_mom20_pos"] = ranks.mom20
    panel["t_vol60_neg"] = -ranks.vol60
    panel["h_size_neg"] = -ranks.cap_proxy_log
    panel["h_vol60_neg"] = -ranks.vol60_tech
    panel["h_overnight_pos"] = ranks.overnight20
    panel["h_intraday_neg"] = -ranks.intraday20
    m = batch4.component_m(panel, M_WEIGHTS)
    t = batch4.component_t(panel, T_WEIGHTS)
    h = batch4.component_h(panel, H_WEIGHTS)
    panel["score"] = OUTER_WEIGHTS[0] * m + OUTER_WEIGHTS[1] * t + OUTER_WEIGHTS[2] * h
    return panel[["date", "score"]].dropna()


def ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["eligible", "cagr", "worst_annual_return", "profitable_years", "annual_return_std", "trade_count_cv", "candidate"],
        ascending=[False, False, False, False, True, True, True], kind="stable",
    ).reset_index(drop=True)


def make_count_signals(scored: pd.DataFrame, k: int, candidate: str) -> pd.DataFrame:
    out = scored.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")
    out = out.groupby("date", sort=False).head(k).copy()
    out["factor"] = candidate
    return out.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")


def causal_thresholds(scored: pd.DataFrame, warmup: pd.DataFrame, q: float) -> pd.Series:
    warmup_max = warmup.groupby("date", sort=True).score.max()
    development_max = scored.groupby("date", sort=True).score.max()
    maxima = pd.concat([warmup_max, development_max]).sort_index()
    if maxima.index.duplicated().any() or maxima.index.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Threshold maximum-score history boundary failed")
    thresholds = maxima.rolling(252, min_periods=252).quantile(q).shift(1)
    return thresholds.reindex(development_max.index)


def make_threshold_signals(scored: pd.DataFrame, thresholds: pd.Series, q: float, candidate: str) -> pd.DataFrame:
    work = scored.copy()
    work["threshold"] = work.date.map(thresholds)
    work = work[work.threshold.notna() & work.score.ge(work.threshold)].copy()
    work = work.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")
    work = work.groupby("date", sort=False).head(3).copy()
    work["factor"] = candidate
    work["quantile"] = q
    return work.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")


def frequency_rows(signals: pd.DataFrame, all_dates: pd.DatetimeIndex, candidate: str, experiment: str) -> list[dict]:
    counts = signals.groupby("date").size()
    rows = []
    for label, dates in [("overall", all_dates)] + [(str(year), all_dates[all_dates.year == year]) for year in core.YEARS]:
        selected = counts.reindex(dates, fill_value=0)
        rows.append({
            "candidate": candidate,
            "experiment": experiment,
            "period": label,
            "sessions": int(len(dates)),
            "active_signal_days": int((selected > 0).sum()),
            "no_signal_days": int((selected == 0).sum()),
            "total_signals": int(selected.sum()),
            "active_day_fraction": float((selected > 0).mean()) if len(selected) else 0.0,
            "mean_signals_per_session": float(selected.mean()) if len(selected) else 0.0,
            "signal_count_std": float(selected.std(ddof=0)) if len(selected) else 0.0,
        })
    return rows


def simulate(signals, bars, calendar, candidate: str, experiment: str, spec: dict) -> dict:
    row, _ = core.simulate(
        signals, bars, calendar, candidate, 0.0, 30,
        "take4.00_stop1.50", 4.0, 1.5,
    )
    row["candidate"] = candidate
    row["experiment"] = experiment
    row["eligible_trade_count"] = bool(row["eligible"])
    row["eligible"] = bool(row["eligible"] and row["profitable_years"] >= 3)
    row["spec_json"] = json.dumps(spec, sort_keys=True)
    return row


def winner_payload(grid: pd.DataFrame, experiment: str) -> dict:
    winner = grid.iloc[0].to_dict()
    return {
        "experiment": experiment,
        "winner": winner,
        "winning_spec": json.loads(winner["spec_json"]),
        "candidate_count": int(len(grid)),
    }


def main() -> None:
    protocol = load_protocol()
    audit4 = json.loads(BATCH4_AUDIT.read_text(encoding="utf-8"))
    if audit4["status"] != "complete" or audit4["champion_spec"] != {
        "M_internal": list(M_WEIGHTS), "T_internal": list(T_WEIGHTS),
        "H_internal": list(H_WEIGHTS), "outer": list(OUTER_WEIGHTS),
    }:
        raise RuntimeError("Batch004 audited champion differs from Batch005 registration")
    RESULTS.mkdir(parents=True, exist_ok=True)
    scored = load_scored_development_panel()
    warmup = load_warmup_panel()
    all_dates = pd.DatetimeIndex(sorted(scored.date.unique()))
    if scored.date.max() > pd.Timestamp("2024-11-22") or warmup.date.max() >= core.EVAL_START:
        raise RuntimeError("Signal or warmup boundary mismatch")
    bars, calendar = core.load_execution_bars(set(scored.symbol.astype(str)), force=False)
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Execution data crosses 2024-12-31")

    count_rows, threshold_rows, frequencies = [], [], []
    signals_by_candidate: dict[str, pd.DataFrame] = {}
    for k in [1, 2, 3]:
        candidate = f"COUNT_ONLY_K{k}"
        signals = make_count_signals(scored, k, candidate)
        row = simulate(signals, bars, calendar, candidate, "count_only", {"maximum_daily_signals": k, "threshold": None})
        count_rows.append(row)
        frequencies.extend(frequency_rows(signals, all_dates, candidate, "count_only"))
        signals_by_candidate[candidate] = signals
        print(f"batch005 {len(count_rows)}/13 {candidate} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)

    for index, q in enumerate(QUANTILES, 4):
        candidate = f"THRESHOLD_ONLY_Q{int(round(q * 100)):02d}_K3"
        thresholds = causal_thresholds(scored, warmup, q)
        signals = make_threshold_signals(scored, thresholds, q, candidate)
        row = simulate(signals, bars, calendar, candidate, "threshold_only", {"maximum_daily_signals": 3, "rolling_sessions": 252, "quantile": q, "shift_sessions": 1})
        threshold_rows.append(row)
        frequencies.extend(frequency_rows(signals, all_dates, candidate, "threshold_only"))
        signals_by_candidate[candidate] = signals
        print(f"batch005 {index}/13 {candidate} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)

    if len(count_rows) + len(threshold_rows) != 13:
        raise RuntimeError("Expected exactly 13 runs")
    count_grid = ordered(pd.DataFrame(count_rows))
    threshold_grid = ordered(pd.DataFrame(threshold_rows))
    count_grid.to_csv(RESULTS / "count_only_grid.csv", index=False, encoding="utf-8-sig")
    threshold_grid.to_csv(RESULTS / "threshold_only_grid.csv", index=False, encoding="utf-8-sig")
    frequency = pd.DataFrame(frequencies)
    frequency.to_csv(RESULTS / "signal_frequency.csv", index=False, encoding="utf-8-sig")
    count_winner = winner_payload(count_grid, "count_only")
    threshold_winner = winner_payload(threshold_grid, "threshold_only")
    (RESULTS / "count_only_winner.json").write_text(json.dumps(count_winner, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RESULTS / "threshold_only_winner.json").write_text(json.dumps(threshold_winner, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for label, payload in [("count_only", count_winner), ("threshold_only", threshold_winner)]:
        candidate = str(payload["winner"]["candidate"])
        signals_by_candidate[candidate].to_parquet(RESULTS / f"{label}_champion_signals_screening.parquet", index=False)

    output = {
        "protocol_id": protocol["protocol_id"],
        "status": "two_unique_experiment_champions_frozen_pending_raw_action_audit",
        "completed_screening_runs": 13,
        "count_only": count_winner,
        "threshold_only": threshold_winner,
        "source_hashes": {
            "BATCH_005.json": core.sha256(PROTOCOL),
            "run_batch_005.py": core.sha256(Path(__file__)),
            "run_batch_004.py": core.sha256(HERE / "run_batch_004.py"),
            "run_batch.py": core.sha256(HERE / "run_batch.py"),
            "batch004_FINAL_AUDIT.json": core.sha256(BATCH4_AUDIT),
            "base_component_panel_pre2025.parquet": core.sha256(BASE_PANEL),
            "execution_bars_pre2025.parquet": core.sha256(core.CACHE / "execution_bars_pre2025.parquet"),
            **{f"model_{path.name}": core.sha256(path) for path in sorted(batch2.MODEL_DIR.glob("*.txt"))},
        },
        "assertions": {
            "post_2024_access": False,
            "maximum_signal_date": str(scored.date.max().date()),
            "maximum_execution_date": str(max(calendar).date()),
            "warmup_maximum_date": str(warmup.date.max().date()),
            "count_only_has_no_threshold": True,
            "threshold_only_daily_count_fixed_at_3": True,
            "cross_combinations": False,
            "screening_run_count_exact": True,
            "grid_expanded": False,
            "production_change": False,
        },
        "development_note": "All 2020-2024 results are development results and are not blind or holdout evidence.",
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    gc.collect()
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
