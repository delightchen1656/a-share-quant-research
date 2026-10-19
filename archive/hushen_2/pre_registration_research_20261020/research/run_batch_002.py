from __future__ import annotations

import gc
import hashlib
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402


ROOT = core.ROOT
PROJECT = core.PROJECT
QFQ_ROOT = core.QFQ_ROOT
CACHE = core.CACHE
RESULTS = PROJECT / "results" / "batch_002"
PROTOCOL = PROJECT / "protocol" / "BATCH_002.json"
MODEL_DIR = ROOT / "strategies" / "hushen_screen_1" / "model"
MODEL_FEATURES = [
    "f_ret1", "f_ret5", "f_ret20", "f_ret60", "f_vol20", "f_ma20",
    "f_amount_ratio5", "f_log_amount", "f_log_price", "f_turn",
    "f_range", "f_downside20", "f_ohlc_rsi14", "f_ohlc_atr_compress5_20",
]


def digest(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def build_model_panel() -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "model_panel_batch002_pre2025.parquet"
    if path.exists():
        p = pd.read_parquet(path)
        p["date"] = pd.to_datetime(p["date"])
        if p["date"].max() > core.LAST_SIGNAL_DATE:
            raise RuntimeError("Cached model panel crosses registered boundary")
        return p
    rows = []
    files = sorted(QFQ_ROOT.glob("*/*.parquet"))
    cols = ["date", "open", "high", "low", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST", "symbol"]
    for i, file in enumerate(files, 1):
        b = pd.read_parquet(file, columns=cols)
        b["date"] = pd.to_datetime(b["date"])
        b = b[(b.date >= core.FEATURE_START) & (b.date <= core.HARD_MAX_DATE)].sort_values("date").reset_index(drop=True)
        if len(b) < 120:
            continue
        for c in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST"]:
            b[c] = pd.to_numeric(b[c], errors="coerce")
        r = (b.close / b.preclose - 1.0).where(b.tradestatus.eq(1))
        rr = r.fillna(0.0)
        chain = (1.0 + rr).cumprod()
        prior = chain.shift(1)
        adj_high = chain * (b.high / b.close)
        adj_low = chain * (b.low / b.close)
        tr = pd.concat([adj_high - adj_low, (adj_high - prior).abs(), (adj_low - prior).abs()], axis=1).max(axis=1) / prior
        f = pd.DataFrame(index=b.index)
        for k in [1, 5, 20, 60]:
            f[f"f_ret{k}"] = chain / chain.shift(k) - 1.0
        f["f_vol20"] = r.rolling(20, min_periods=3).std()
        f["f_ma20"] = chain / chain.rolling(20, min_periods=3).mean() - 1.0
        f["f_amount_ratio5"] = b.amount / b.amount.rolling(5, min_periods=3).mean()
        f["f_log_amount"] = np.log1p(b.amount)
        f["f_log_price"] = np.log(b.close)
        f["f_turn"] = b.turn
        f["f_range"] = (b.high - b.low) / b.preclose
        f["f_downside20"] = r.clip(upper=0).pow(2).rolling(20, min_periods=3).mean().pow(0.5)
        f["f_ohlc_rsi14"] = rr.clip(lower=0).rolling(14, min_periods=3).sum() / rr.abs().rolling(14, min_periods=3).sum()
        atr5 = tr.rolling(5, min_periods=3).mean()
        atr20 = tr.rolling(20, min_periods=3).mean()
        f["f_ohlc_atr_compress5_20"] = atr5 / atr20
        ret1 = b.close.pct_change(fill_method=None)
        f["vol60"] = ret1.rolling(60, min_periods=60).std(ddof=0)
        f["mom20"] = b.close / b.close.shift(20) - 1.0
        f["mom120"] = b.close / b.close.shift(120) - 1.0
        f["close_to_high60"] = b.close / b.close.rolling(60, min_periods=60).max() - 1.0
        f["atr_pct"] = (tr.rolling(14, min_periods=14).mean()).clip(0.015, 0.05)
        f["amount_med20"] = b.amount.rolling(20, min_periods=20).median()
        f["date"] = b.date
        f["symbol"] = b.symbol.astype(str)
        f["close"] = b.close
        f["obs"] = np.arange(1, len(b) + 1)
        f["isST"] = b.isST
        f["tradestatus"] = b.tradestatus
        f["amount"] = b.amount
        mask = (
            f.date.between(core.EVAL_START, core.LAST_SIGNAL_DATE)
            & f.obs.ge(120)
            & f.close.between(2.0, 80.0)
            & f.amount.ge(20_000_000)
            & f.amount_med20.ge(30_000_000)
            & f.isST.eq(0)
            & f.tradestatus.eq(1)
        )
        keep = ["date", "symbol", "close", "atr_pct", "vol60", "mom20", "mom120", "close_to_high60"] + MODEL_FEATURES
        out = f.loc[mask, keep].replace([np.inf, -np.inf], np.nan).dropna().copy()
        if not out.empty:
            rows.append(out)
        if i % 500 == 0:
            print(f"model feature files {i}/{len(files)}", flush=True)
    panel = pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)
    panel.to_parquet(path, index=False)
    return panel


def make_signals(panel: pd.DataFrame) -> pd.DataFrame:
    models = {}
    for name in ["utility", "pen025", "pen100"]:
        model = lgb.Booster(model_file=str(MODEL_DIR / f"{name}.txt"))
        if model.feature_name() != MODEL_FEATURES:
            raise RuntimeError(f"Feature mismatch for {name}")
        models[name] = model.predict(panel[MODEL_FEATURES], num_threads=4)
    for name, values in models.items():
        panel[name] = values
    panel["model_mean_raw"] = panel[["utility", "pen025", "pen100"]].mean(axis=1)
    stable_components = panel.groupby("date", sort=False)[["mom120", "close_to_high60", "mom20", "vol60"]].rank(pct=True) - 0.5
    panel["stable_raw"] = (
        0.35 * stable_components.mom120
        + 0.25 * stable_components.close_to_high60
        + 0.20 * stable_components.mom20
        - 0.20 * stable_components.vol60
    )
    rank_cols = panel.groupby("date", sort=False)[["model_mean_raw", "utility", "pen025", "pen100", "stable_raw"]].rank(pct=True) - 0.5
    panel["model_mean"] = panel["model_mean_raw"]
    panel["model_stable_75"] = 0.75 * rank_cols.model_mean_raw + 0.25 * rank_cols.stable_raw
    panel["model_stable_50"] = 0.50 * rank_cols.model_mean_raw + 0.50 * rank_cols.stable_raw
    panel["model_unanimous"] = rank_cols[["utility", "pen025", "pen100"]].min(axis=1)
    chunks = []
    for score_name in ["model_mean", "model_stable_75", "model_stable_50", "model_unanimous"]:
        s = panel[["date", "symbol", "close", "atr_pct", score_name, "model_mean_raw"]].rename(columns={score_name: "score"})
        if score_name == "model_mean":
            s = s[s.model_mean_raw >= 0.10]
        s = s.sort_values(["date", "score", "symbol"], ascending=[True, False, True]).groupby("date", sort=False).head(2)
        s = s.copy()
        s["factor"] = score_name
        chunks.append(s)
    signals = pd.concat(chunks, ignore_index=True).sort_values(["date", "factor", "score", "symbol"], ascending=[True, True, False, True])
    RESULTS.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(RESULTS / "signals_all_scores.parquet", index=False)
    return signals


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    parent = json.loads(core.PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol["candidate_count"] != 48 or not protocol["post_2024_forbidden"]:
        raise RuntimeError("Batch 002 protocol mismatch")
    panel = build_model_panel()
    signals = make_signals(panel)
    del panel
    gc.collect()
    by_symbol, calendar = core.load_execution_bars(set(signals.symbol), force=False)
    rows = []
    n = 0
    for score in [x["name"] for x in protocol["signal_scores"]]:
        for offset in protocol["entry_atr_offsets"]:
            for hold in protocol["holding_calendar_days"]:
                for ex in protocol["atr_take_stop_pairs"]:
                    n += 1
                    row, _ = core.simulate(signals, by_symbol, calendar, score, offset, hold, ex["name"], ex["take"], ex["stop"])
                    row["eligible_trade_count"] = row["eligible"]
                    row["eligible"] = bool(row["eligible"] and row["profitable_years"] >= 3)
                    rows.append(row)
                    print(f"batch2 {n}/48 {row['candidate']} cagr={row['cagr']:.4%} profitable={row['profitable_years']} eligible={row['eligible']}", flush=True)
    grid = pd.DataFrame(rows).sort_values(
        ["eligible", "cagr", "worst_annual_return", "profitable_years", "annual_return_std", "trade_count_cv", "candidate"],
        ascending=[False, False, False, False, True, True, True],
    ).reset_index(drop=True)
    grid.to_csv(RESULTS / "grid.csv", index=False, encoding="utf-8-sig")
    eligible = grid[grid.eligible]
    champion = eligible.iloc[0] if not eligible.empty else grid.iloc[0]
    status = "unique_champion_frozen_pending_full_audit" if not eligible.empty else "no_candidate_met_cross_year_gate"
    _, trades = core.simulate(
        signals, by_symbol, calendar, champion.factor, float(champion.entry_offset_atr), int(champion.hold_calendar_days),
        champion.exit_set, float(champion.take_atr), float(champion.stop_atr), keep_trades=True,
    )
    trades.to_csv(RESULTS / "champion_trades_screening.csv", index=False, encoding="utf-8-sig")
    out = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": digest(PROTOCOL),
        "parent_protocol_sha256": digest(core.PROTOCOL_PATH),
        "runner_sha256": digest(Path(__file__)),
        "frozen_model_hashes": {p.name: digest(p) for p in sorted(MODEL_DIR.glob("*.txt"))},
        "selection_status": status,
        "candidate_count": len(grid),
        "eligible_candidate_count": int(grid.eligible.sum()),
        "champion": champion.to_dict(),
        "fit_period_note": "Frozen models were trained on 2018-2021; 2020-2021 results overlap model fitting and are not cross-time validation.",
        "cross_time_period": "2022-2024",
        "post_2024_access": False,
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
