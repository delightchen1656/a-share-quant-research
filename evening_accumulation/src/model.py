from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_score, recall_score, roc_auc_score


FEATURES = ["ret5", "ret20", "ret60", "range20", "range60", "dd20", "vol20", "vol60",
            "volume_ratio", "volume_cv", "up_volume_share", "pv_corr", "close_pos60",
            "turn20", "amount20", "breakout_gap", "rise_from_low60", "volume_spike"]


def _one(g: pd.DataFrame, label_horizon: int, target_rise: float) -> pd.DataFrame:
    g = g.sort_values("date").copy(); c, v = g.close, g.volume
    r = c.pct_change(fill_method=None); vchg = v.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    g["ret5"], g["ret20"], g["ret60"] = c.pct_change(5, fill_method=None), c.pct_change(20, fill_method=None), c.pct_change(60, fill_method=None)
    for n in (20, 60):
        g[f"range{n}"] = g.high.rolling(n).max() / g.low.rolling(n).min() - 1
    g["dd20"] = c / c.rolling(20).max() - 1
    g["vol20"], g["vol60"] = r.rolling(20).std(), r.rolling(60).std()
    g["volume_ratio"] = v.rolling(5).mean() / v.rolling(20).mean()
    g["volume_cv"] = v.rolling(20).std() / v.rolling(20).mean()
    g["up_volume_share"] = v.where(r > 0, 0).rolling(20).sum() / v.rolling(20).sum()
    g["pv_corr"] = r.rolling(20).corr(vchg)
    lo, hi = c.rolling(60).min(), c.rolling(60).max()
    g["close_pos60"] = (c - lo) / (hi - lo).replace(0, np.nan)
    g["rise_from_low60"] = c / lo - 1
    g["volume_spike"] = v / v.rolling(20).mean()
    g["turn20"], g["amount20"] = g.turn.rolling(20).mean(), np.log1p(g.amount.rolling(20).mean())
    g["breakout_gap"] = c / c.shift(1).rolling(60).max() - 1
    future_high = g.high.shift(-1).iloc[::-1].rolling(label_horizon, min_periods=label_horizon).max().iloc[::-1]
    g["label"] = (future_high / c - 1 >= target_rise).astype(float); g.loc[future_high.isna(), "label"] = np.nan
    return g


def features(qfq: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    chunks = []
    for symbol, group in qfq.groupby("symbol", sort=False):
        part = _one(group, cfg["label_horizon_days"], cfg["target_rise"])
        part["symbol"] = symbol
        chunks.append(part)
    return pd.concat(chunks, ignore_index=True).replace([np.inf, -np.inf], np.nan)


def eligible(ds: pd.DataFrame, cfg: dict) -> pd.Series:
    age = ds.groupby("symbol").cumcount() + 1
    ok = age >= cfg["min_listing_days"]
    ok &= np.expm1(ds.amount20) >= cfg["min_avg_amount_20"]
    if cfg["exclude_st"]: ok &= ds.isST.ne("1")
    # Avoid learning a chase-after-breakout rule.
    ok &= ds.ret5.le(.12) & ds.ret20.le(.20) & ds.rise_from_low60.le(.30)
    ok &= ds.volume_spike.le(5) & ds.high.ne(ds.low) & ds.pctChg.lt(19.5)
    return ok


def train_all(root: Path, cfg: dict, panels: tuple[pd.DataFrame, pd.DataFrame], board_only: str | None = None) -> None:
    _, qfq = panels; ds = features(qfq, cfg); ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["label"])
    model_dir = root / "models"; model_dir.mkdir(exist_ok=True); reports = {}
    for board, x in ds.groupby("board"):
        if board_only and board != board_only: continue
        dates = np.sort(x.date.unique())
        if len(dates) < 250 or x.label.nunique() < 2: continue
        split_idx = int(len(dates) * .8); split = dates[split_idx]
        purge_idx = max(0, split_idx - cfg["label_horizon_days"])
        train_end = dates[purge_idx]
        tr, va = x[x.date < train_end], x[x.date >= split]
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=.05, max_leaf_nodes=15,
                                           l2_regularization=1, class_weight="balanced", random_state=42)
        m.fit(tr[FEATURES], tr.label.astype(int)); p = m.predict_proba(va[FEATURES])[:, 1]
        pred = p >= cfg["probability_threshold"]
        reports[board] = {"train_end": str(pd.Timestamp(train_end).date()), "valid_start": str(pd.Timestamp(split).date()), "train": len(tr), "valid": len(va),
                          "base_rate": float(va.label.mean()), "precision": float(precision_score(va.label, pred, zero_division=0)),
                          "recall": float(recall_score(va.label, pred, zero_division=0)), "auc": float(roc_auc_score(va.label, p))}
        joblib.dump({"model": m, "features": FEATURES, "board": board, "trained_through": str(x.date.max().date())}, model_dir / f"{board}.joblib")
    (model_dir / "metrics.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))


def _scored(root: Path, cfg: dict, qfq: pd.DataFrame) -> pd.DataFrame:
    ds = features(qfq, cfg); ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES)
    chunks = []
    for path in (root / "models").glob("*.joblib"):
        b = joblib.load(path); x = ds[ds.board.eq(b["board"])].copy()
        if not x.empty: x["probability"] = b["model"].predict_proba(x[FEATURES])[:, 1]; chunks.append(x)
    if not chunks: raise FileNotFoundError("没有模型，请先运行 train")
    return pd.concat(chunks)


def generate_signals(root: Path, cfg: dict, panels: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    _, qfq = panels; x = _scored(root, cfg, qfq); latest = x.sort_values("date").groupby("symbol").tail(1)
    sig = latest[latest.probability >= cfg["probability_threshold"]][["date", "symbol", "board", "close", "probability", "amount"]].sort_values("probability", ascending=False)
    out = root / "outputs"; out.mkdir(exist_ok=True); date = pd.Timestamp(qfq.date.max()).strftime("%Y%m%d")
    sig.to_csv(out / f"signals_{date}.csv", index=False, encoding="utf-8-sig"); print(sig.to_string(index=False))


def backtest_all(root: Path, cfg: dict, panels: tuple[pd.DataFrame, pd.DataFrame], board_only: str | None = None) -> None:
    raw, qfq = panels; scored = _scored(root, cfg, qfq)
    # 仅在最后20%日期做真正样本外回测，信号日收盘产生、下一日开盘成交。
    dates = np.sort(scored.date.unique()); start = dates[int(len(dates) * .8)]
    signals = scored[(scored.date >= start) & (scored.probability >= cfg["probability_threshold"])][["date", "symbol", "probability"]]
    raw_groups = {s: g.sort_values("date") for s, g in raw.groupby("symbol")}; trades = []
    for symbol, symbol_signals in signals.sort_values("date").groupby("symbol"):
        if symbol not in raw_groups: continue
        next_allowed = pd.Timestamp.min
        for s in symbol_signals.itertuples():
            if s.date <= next_allowed: continue
            g = raw_groups[symbol][raw_groups[symbol].date > s.date].head(cfg["max_holding_days"])
            if g.empty: continue
            entry = float(g.iloc[0].open) * (1 + cfg["slippage"]); exit_px = float(g.iloc[-1].close); reason = "TIME"
            half_done = False; pnl = 0.0; remaining = 1.0; exit_date = g.iloc[-1].date
            for row in g.itertuples():
                if row.low <= entry * (1 - cfg["stop_loss"]): exit_px = entry * (1 - cfg["stop_loss"]); reason = "STOP"; exit_date = row.date; break
                if row.high >= entry * (1 + cfg["take_profit_all"]):
                    if not half_done:
                        pnl += .5 * cfg["take_profit_half"]
                        remaining = .5
                        half_done = True
                    exit_px = entry * (1 + cfg["take_profit_all"]); reason = "TP30"; exit_date = row.date; break
                if not half_done and row.high >= entry * (1 + cfg["take_profit_half"]):
                    pnl += .5 * cfg["take_profit_half"]; remaining = .5; half_done = True
            ret = pnl + remaining * (exit_px * (1 - cfg["slippage"]) / entry - 1) - 2 * cfg["commission"]
            trades.append({"signal_date": s.date, "exit_date": exit_date, "symbol": symbol, "probability": s.probability, "entry": entry, "return": ret, "reason": reason})
            next_allowed = exit_date
    out = root / "outputs"; out.mkdir(exist_ok=True); suffix = f"_{board_only}" if board_only else ""; df = pd.DataFrame(trades); df.to_csv(out / f"backtest_trades{suffix}.csv", index=False, encoding="utf-8-sig")
    summary = {"signals": len(signals), "trades": len(df), "win_rate": float((df["return"] > 0).mean()) if len(df) else None,
               "mean_return": float(df["return"].mean()) if len(df) else None}
    if len(df): summary["exit_reasons"] = df.reason.value_counts().to_dict()
    (out / f"backtest_summary{suffix}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"); print(summary)
