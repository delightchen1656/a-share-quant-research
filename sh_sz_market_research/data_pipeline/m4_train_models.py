"""M4: build technical features, train rally/stop-first models, and freeze them.

Model/pool/threshold selection uses 2018-2024 only.  The 2025-01-01 through
2026-07-31 holdout is deliberately not scored here.
"""
from __future__ import annotations

import json
import math
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FEATURE_DIR = DATA / "derived" / "features"
SCORE_DIR = DATA / "derived" / "scores"
OUT = ROOT / "outputs" / "m4_models"
MODEL_DIR = ROOT / "models"

FEATURES = [
    "ret5", "ret20", "ret60", "range20", "range60", "dd20", "vol20",
    "vol60", "volume_ratio", "volume_cv", "up_volume_share", "pv_corr",
    "close_pos60", "turn20", "amount20", "breakout_gap", "rise_from_low60",
    "volume_spike",
]
FIT_END = "2023-10-31"       # purged from the 2024 validation interval
VALID_START = "2024-01-01"
VALID_END = "2024-10-31"    # 40-session outcome completes during 2024
FINAL_END = "2024-10-31"    # final rally labels are known by 2024 year-end
STOP_FINAL_END = "2024-11-29"  # 22-session outcome completes during 2024
MIN_PRECISION = 0.20


def rolling_corr(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    return a.rolling(n).corr(b)


def make_one(symbol: str) -> str:
    exchange = symbol[-2:]
    q = pd.read_parquet(DATA / "qfq" / exchange / f"{symbol}.parquet").sort_values("date").reset_index(drop=True)
    r = pd.read_parquet(DATA / "raw" / exchange / f"{symbol}.parquet").sort_values("date").reset_index(drop=True)
    p = pd.read_parquet(DATA / "derived" / "pools" / exchange / f"{symbol}.parquet")
    lab = pd.read_parquet(DATA / "derived" / "labels" / exchange / f"{symbol}.parquet")
    p["date"] = p.date.astype(str).str[:10]
    lab["date"] = lab.date.astype(str).str[:10]

    close = q.close.astype(float)
    high = q.high.astype(float)
    low = q.low.astype(float)
    volume = q.volume.astype(float)
    amount = q.amount.astype(float)
    turn = q.turn.astype(float)
    ret1 = close.pct_change(fill_method=None)
    vma20 = volume.rolling(20).mean()
    low60 = low.rolling(60).min()
    high20 = high.rolling(20).max()
    high60 = high.rolling(60).max()

    f = pd.DataFrame({"date": q.date.astype(str).str[:10], "symbol": symbol})
    f["ret5"] = close.pct_change(5, fill_method=None)
    f["ret20"] = close.pct_change(20, fill_method=None)
    f["ret60"] = close.pct_change(60, fill_method=None)
    f["range20"] = high.rolling(20).max() / low.rolling(20).min() - 1
    f["range60"] = high60 / low60 - 1
    f["dd20"] = close / close.rolling(20).max() - 1
    f["vol20"] = ret1.rolling(20).std()
    f["vol60"] = ret1.rolling(60).std()
    f["volume_ratio"] = volume.rolling(5).mean() / vma20
    f["volume_cv"] = volume.rolling(20).std() / vma20
    f["up_volume_share"] = volume.where(ret1 > 0, 0).rolling(20).sum() / volume.rolling(20).sum()
    f["pv_corr"] = rolling_corr(ret1, volume.pct_change(fill_method=None), 20)
    f["close_pos60"] = (close - low60) / (high60 - low60)
    f["turn20"] = turn.rolling(20).mean()
    f["amount20"] = amount.rolling(20).mean() / 100_000_000
    f["breakout_gap"] = close / high20.shift(1) - 1
    f["rise_from_low60"] = close / low60 - 1
    f["volume_spike"] = volume / vma20

    f = f.merge(p[["date", "pool_a", "pool_b", "pool_c"]], on="date", how="left")
    f = f.merge(lab[["date", "label40", "label60", "t1_buyable"]], on="date", how="left")

    # Stop-first label: signal after T close, entry at T+1 unadjusted open with
    # 0.20% adverse slippage, then inspect raw intraday low/high for 22 sessions.
    ropen, rhigh, rlow = (r[c].astype(float).to_numpy() for c in ("open", "high", "low"))
    stop = np.full(len(r), np.nan)
    for i in range(len(r) - 23):
        entry = ropen[i + 1] * 1.002
        if not math.isfinite(entry) or entry <= 0:
            continue
        stop_px, profit_px = entry * 0.93, entry * 1.24
        outcome = 0.0
        for j in range(i + 1, min(i + 23, len(r))):
            hit_stop, hit_profit = rlow[j] <= stop_px, rhigh[j] >= profit_px
            if hit_stop:  # conservative if both are touched in one daily bar
                outcome = 1.0
                break
            if hit_profit:
                break
        stop[i] = outcome
    f["stop_first22"] = stop
    f.replace([np.inf, -np.inf], np.nan, inplace=True)
    target = FEATURE_DIR / exchange / f"{symbol}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(target, index=False)
    return symbol


def load_rows(pool_name: str, start: str | None, end: str, cap: int,
              label: str, require_buyable: bool = True) -> pd.DataFrame:
    parts = []
    for path in FEATURE_DIR.rglob("*.parquet"):
        use = ["date", "symbol", pool_name, label, "t1_buyable"] + FEATURES
        x = pd.read_parquet(path, columns=use)
        mask = x[pool_name].fillna(False) & x[label].notna()
        if require_buyable:
            mask &= x.t1_buyable.fillna(False)
        mask &= x.date.le(end)
        if start:
            mask &= x.date.ge(start)
        x = x.loc[mask, ["date", "symbol", label] + FEATURES]
        x = x.dropna(subset=FEATURES)
        if len(x) > cap:
            seed = zlib.crc32(path.stem.encode("utf-8")) & 0xFFFFFFFF
            x = x.sample(cap, random_state=seed).sort_values("date")
        if not x.empty:
            parts.append(x)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def fit_model(x: pd.DataFrame, label: str, seed: int, max_iter: int = 300):
    model = HistGradientBoostingClassifier(
        max_iter=max_iter, learning_rate=0.04, max_leaf_nodes=15,
        l2_regularization=3.0, class_weight="balanced", random_state=seed,
    )
    model.fit(x[FEATURES].astype("float32"), x[label].astype(int))
    return model


def choose_threshold(y: np.ndarray, prob: np.ndarray) -> tuple[float, dict]:
    candidates = np.unique(np.quantile(prob, np.linspace(.50, .9995, 700)))
    best = None
    for threshold in candidates:
        chosen = prob >= threshold
        count = int(chosen.sum())
        if count < 20:
            continue
        correct = int(y[chosen].sum())
        precision = correct / count
        if precision >= MIN_PRECISION:
            key = (correct, precision, count, threshold)
            if best is None or key > best[0]:
                best = (key, threshold, count, correct, precision)
    if best is None:
        threshold = float(np.quantile(prob, .99))
        chosen = prob >= threshold
        count, correct = int(chosen.sum()), int(y[chosen].sum())
        precision = correct / max(count, 1)
    else:
        _, threshold, count, correct, precision = best
    return float(threshold), {"signals": count, "correct": correct, "precision": precision,
                              "recall": correct / max(int(y.sum()), 1)}


def evaluate(model, frame: pd.DataFrame, label: str) -> tuple[np.ndarray, dict]:
    y = frame[label].astype(int).to_numpy()
    prob = model.predict_proba(frame[FEATURES].astype("float32"))[:, 1]
    threshold, selected = choose_threshold(y, prob)
    metrics = {"samples": int(len(y)), "positives": int(y.sum()),
               "base_rate": float(y.mean()), "roc_auc": float(roc_auc_score(y, prob)),
               "pr_auc": float(average_precision_score(y, prob)),
               "threshold": threshold, **selected}
    return prob, metrics


def score_all(rally_model, stop_model, threshold: float, chosen_pool: str) -> None:
    for i, path in enumerate(FEATURE_DIR.rglob("*.parquet"), 1):
        x = pd.read_parquet(path)
        valid = x[FEATURES].notna().all(axis=1)
        rally = np.full(len(x), np.nan)
        risk = np.full(len(x), np.nan)
        if valid.any():
            matrix = x.loc[valid, FEATURES].astype("float32")
            rally[valid] = rally_model.predict_proba(matrix)[:, 1]
            risk[valid] = stop_model.predict_proba(matrix)[:, 1]
        out = x[["date", "symbol", "pool_a", "pool_b", "pool_c", "t1_buyable"]].copy()
        out["rally_probability"], out["stop_probability"] = rally, risk
        out["signal"] = (out[chosen_pool].fillna(False) & out.t1_buyable.fillna(False)
                         & out.rally_probability.ge(threshold))
        target = SCORE_DIR / path.parent.name / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)
        if i % 300 == 0:
            print(f"scored [{i}/3394]", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(DATA / "metadata" / "historical_mainboard_universe.csv",
                           dtype=str, encoding="utf-8-sig")
    symbols = universe.symbol.drop_duplicates().sort_values().tolist()
    print(f"M4 feature build: {len(symbols)} stocks", flush=True)
    with ThreadPoolExecutor(max_workers=8) as workers:
        for i, _ in enumerate(workers.map(make_one, symbols), 1):
            if i % 250 == 0:
                print(f"features [{i}/{len(symbols)}] {i/len(symbols):.1%}", flush=True)

    comparisons = []
    cap_by_pool = {"pool_a": 260, "pool_b": 420, "pool_c": 520}
    fitted = {}
    for n, pool_name in enumerate(("pool_a", "pool_b", "pool_c"), 1):
        print(f"loading/fitting {pool_name}", flush=True)
        fit = load_rows(pool_name, None, FIT_END, cap_by_pool[pool_name], "label40")
        valid = load_rows(pool_name, VALID_START, VALID_END, 10000, "label40")
        model = fit_model(fit, "label40", 40 + n)
        _, metrics = evaluate(model, valid, "label40")
        metrics.update({"pool": pool_name, "fit_samples": int(len(fit)),
                        "fit_positives": int(fit.label40.astype(int).sum())})
        comparisons.append(metrics)
        fitted[pool_name] = model
        joblib.dump({"model": model, "features": FEATURES, "metrics": metrics},
                    MODEL_DIR / f"mainboard_rally_selection_{pool_name}.joblib", compress=3)
        print(pool_name, json.dumps(metrics, ensure_ascii=False), flush=True)

    eligible = [x for x in comparisons if x["precision"] >= MIN_PRECISION]
    chosen = max(eligible or comparisons, key=lambda x: (x["correct"], x["precision"], x["signals"]))
    chosen_pool, threshold = chosen["pool"], float(chosen["threshold"])

    final = load_rows(chosen_pool, None, FINAL_END, cap_by_pool[chosen_pool], "label40")
    rally_model = fit_model(final, "label40", 142)
    stop = load_rows(chosen_pool, None, STOP_FINAL_END, cap_by_pool[chosen_pool], "stop_first22")
    stop_model = fit_model(stop, "stop_first22", 173, max_iter=160)
    stop_train_rate = float(stop.stop_first22.mean())

    frozen = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "feature_count": len(FEATURES), "features": FEATURES,
        "selection_fit_end": FIT_END, "validation": [VALID_START, VALID_END],
        "final_rally_anchor_end": FINAL_END, "final_stop_anchor_end": STOP_FINAL_END,
        "chosen_pool": chosen_pool, "rally_threshold": threshold,
        "stop_threshold": 0.50, "ranking_stop_penalty": 0.22,
        "rally_train_samples": int(len(final)), "rally_train_positive_rate": float(final.label40.mean()),
        "stop_train_samples": int(len(stop)), "stop_train_positive_rate": stop_train_rate,
        "holdout": ["2025-01-01", "2026-07-31"], "holdout_used": False,
        "pool_comparison": comparisons,
    }
    bundle = {"model": rally_model, "features": FEATURES, "pool": chosen_pool,
              "threshold": threshold, "metadata": frozen}
    stop_bundle = {"model": stop_model, "features": FEATURES, "threshold": .50,
                   "metadata": frozen}
    joblib.dump(bundle, MODEL_DIR / "mainboard_rally_frozen.joblib", compress=3)
    joblib.dump(stop_bundle, MODEL_DIR / "mainboard_stop_first_frozen.joblib", compress=3)
    (OUT / "frozen_parameters.json").write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(comparisons).to_csv(OUT / "pool_model_comparison.csv", index=False, encoding="utf-8-sig")

    print("scoring all dates for M5/M6", flush=True)
    score_all(rally_model, stop_model, threshold, chosen_pool)
    report = ["# M4 主板双模型训练报告", "",
              "训练、池选择和阈值选择严格截止于2024年；2025—2026/7未参与。", "",
              "| 池 | 验证样本 | ROC-AUC | PR-AUC | 阈值 | 信号 | 正确 | Precision | Recall |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for x in comparisons:
        report.append(f"| {x['pool']} | {x['samples']:,} | {x['roc_auc']:.4f} | {x['pr_auc']:.4f} | {x['threshold']:.4f} | {x['signals']:,} | {x['correct']:,} | {x['precision']:.2%} | {x['recall']:.2%} |")
    report += ["", f"选定股票池：**{chosen_pool}**；锁定暴涨阈值：**{threshold:.6f}**。",
               f"先止损模型训练样本：{len(stop):,}；正样本率：{stop_train_rate:.2%}。",
               "", "成交可行性、费用与组合结果将在M5逐笔撮合中验证。"]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(frozen, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
