from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_score, roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Trial:
    name: str
    threshold: float
    max_leaf_nodes: int
    learning_rate: float
    max_iter: int
    l2: float
    top_per_day: int
    max_positions: int
    regime: str = "none"


TRIALS = [
    Trial("r01_conservative", .70, 15, .05, 200, 2.0, 3, 8),
    Trial("r02_baseline", .65, 15, .05, 250, 1.0, 5, 10),
    Trial("r03_low_threshold", .60, 15, .05, 250, 1.0, 5, 10),
    Trial("r04_high_threshold", .75, 15, .05, 250, 1.0, 3, 8),
    Trial("r05_small_tree", .65, 7, .04, 300, 2.0, 5, 10),
    Trial("r06_large_tree", .68, 31, .04, 250, 3.0, 4, 8),
    Trial("r07_strong_reg", .63, 15, .03, 350, 8.0, 5, 10),
    Trial("r08_focused", .68, 7, .05, 250, 4.0, 2, 6),
    Trial("r09_diversified", .62, 15, .04, 300, 3.0, 8, 12),
    Trial("r10_precision", .78, 7, .03, 350, 6.0, 2, 5),
]


def triple_barrier_label(ds: pd.DataFrame, horizon: int, stop: float, target: float) -> pd.Series:
    result = pd.Series(np.nan, index=ds.index, dtype=float)
    for _, g in ds.groupby("symbol", sort=False):
        idx = g.index.to_numpy(); close = g.close.to_numpy(); high = g.high.to_numpy(); low = g.low.to_numpy()
        labels = np.full(len(g), np.nan)
        for i in range(len(g) - horizon):
            h = high[i + 1:i + horizon + 1] >= close[i] * (1 + target)
            s = low[i + 1:i + horizon + 1] <= close[i] * (1 - stop)
            hit_h = np.flatnonzero(h); hit_s = np.flatnonzero(s)
            tp_i = hit_h[0] if len(hit_h) else horizon + 1
            sl_i = hit_s[0] if len(hit_s) else horizon + 1
            labels[i] = float(tp_i < sl_i)
        result.loc[idx] = labels
    return result


def portfolio_backtest(raw: pd.DataFrame, scored: pd.DataFrame, cfg: dict, trial: Trial,
                       benchmark: pd.DataFrame | None = None, start_date=None, end_date=None):
    start = pd.Timestamp(start_date or "2025-01-01")
    end = pd.Timestamp(end_date or cfg["end_date"])
    raw = raw[(raw.date >= start) & (raw.date <= end)].copy()
    scored = scored[(scored.date >= start) & (scored.date <= end) & (scored.probability >= trial.threshold)]
    if trial.regime != "none":
        if benchmark is None:
            raise ValueError("benchmark is required for regime filtering")
        market = benchmark[["date", "close"]].copy().sort_values("date")
        market["ma20"] = market.close.rolling(20).mean()
        market["ma60"] = market.close.rolling(60).mean()
        market["dd60"] = market.close / market.close.rolling(60).max() - 1
        market["vol20"] = market.close.pct_change().rolling(20).std()
        if trial.regime == "above_ma20": mask = market.close > market.ma20
        elif trial.regime == "above_ma60": mask = market.close > market.ma60
        elif trial.regime == "trend": mask = market.ma20 > market.ma60
        elif trial.regime == "dd10": mask = market.dd60 > -0.10
        elif trial.regime == "low_vol": mask = market.vol20 < 0.025
        else: raise ValueError("unknown regime: " + trial.regime)
        allowed_dates = set(market.loc[mask, "date"])
        scored = scored[scored.date.isin(allowed_dates)]
    signal_by_date = {
        d: g.nlargest(trial.top_per_day, "probability")[["symbol", "probability"]]
        for d, g in scored.groupby("date")
    }
    raw_by_date = {d: g.set_index("symbol") for d, g in raw.groupby("date")}
    dates = sorted(raw_by_date)
    cash = float(cfg["initial_cash"]); positions = {}; pending = pd.DataFrame(); trades = []; curve = []; peak_positions = 0
    rejected = {"limit_up": 0, "limit_down": 0, "suspended": 0, "cash": 0, "lot": 0, "t_plus_one": 0}

    def commission(amount):
        return max(float(cfg.get("min_commission", 5.0)), amount * float(cfg["commission"]))

    def transfer(amount):
        return amount * float(cfg.get("transfer_fee", 0.00001))

    def sell_tax(amount, trade_date):
        # Historical A-share rate was 0.1%; it was halved on 2023-08-28.
        rate = float(cfg.get("stamp_tax_sell", 0.0005)) if trade_date >= pd.Timestamp("2023-08-28") else 0.001
        return amount * rate
    for date in dates:
        day = raw_by_date[date]
        # Orders are based solely on the previous close signal and execute at today's open.
        if not pending.empty:
            for sig in pending.itertuples():
                if len(positions) >= trial.max_positions: break
                if sig.symbol in positions or sig.symbol not in day.index: continue
                row = day.loc[sig.symbol]
                if row.tradestatus != "1" or row.open <= 0:
                    rejected["suspended"] += 1; continue
                if float(row.high) == float(row.low) and float(row.pctChg) >= 19.5:
                    rejected["limit_up"] += 1; continue
                equity_open = cash + sum(p["qty"] * float(day.loc[s, "open"]) for s, p in positions.items() if s in day.index)
                budget = min(equity_open * cfg["position_fraction"], cash)
                price = min(float(row.high), float(row.open) * (1 + cfg["slippage"]))
                volume_cap = int(float(row.volume) * float(cfg.get("daily_volume_limit", .25)))
                qty = min(int(budget / price), volume_cap)
                if qty < int(cfg.get("min_order_shares_star", 200)):
                    rejected["lot"] += 1; continue
                amount = qty * price; fee = commission(amount) + transfer(amount); cost = amount + fee
                while qty >= int(cfg.get("min_order_shares_star", 200)) and cost > cash:
                    qty -= 1; amount = qty * price; fee = commission(amount) + transfer(amount); cost = amount + fee
                if qty < int(cfg.get("min_order_shares_star", 200)):
                    rejected["cash"] += 1; continue
                cash -= cost
                positions[sig.symbol] = {"qty": float(qty), "entry": price, "entry_date": date,
                                         "days": 0, "half": False, "probability": sig.probability,
                                         "realized": -cost, "initial_cost": cost}
                peak_positions = max(peak_positions, len(positions))
        for symbol, pos in list(positions.items()):
            if symbol not in day.index: continue
            row = day.loc[symbol]; pos["days"] += 1
            if pos["entry_date"] == date:
                rejected["t_plus_one"] += 1
                continue
            stop_px = pos["entry"] * (1 - cfg["stop_loss"])
            tp20 = pos["entry"] * (1 + cfg["take_profit_half"])
            tp30 = pos["entry"] * (1 + cfg["take_profit_all"])
            sells = []
            one_price_down = float(row.high) == float(row.low) and float(row.pctChg) <= -19.5
            if row.low <= stop_px and one_price_down:
                rejected["limit_down"] += 1
                sells = []
            elif row.low <= stop_px:
                fill = max(float(row.low), min(float(row.open), stop_px) * (1 - cfg["slippage"]))
                sells = [(pos["qty"], fill, "STOP")]
            elif row.high >= tp30:
                if not pos["half"]:
                    half = int(pos["qty"] / 2)
                    if half >= int(cfg.get("min_order_shares_star", 200)):
                        sells.append((half, min(float(row.high), tp20 * (1 - cfg["slippage"])), "TP20"))
                        sells.append((pos["qty"] - half, min(float(row.high), max(float(row.open), tp30) * (1 - cfg["slippage"])), "TP30"))
                    else:
                        sells.append((pos["qty"], min(float(row.high), max(float(row.open), tp30) * (1 - cfg["slippage"])), "TP30"))
                    pos["half"] = True
                else:
                    sells.append((pos["qty"], min(float(row.high), max(float(row.open), tp30) * (1 - cfg["slippage"])), "TP30"))
            elif not pos["half"] and row.high >= tp20:
                half = int(pos["qty"] / 2)
                if half >= int(cfg.get("min_order_shares_star", 200)):
                    sells = [(half, min(float(row.high), max(float(row.open), tp20) * (1 - cfg["slippage"])), "TP20")]; pos["half"] = True
            elif pos["days"] >= cfg["max_holding_days"]:
                if one_price_down:
                    rejected["limit_down"] += 1; sells = []
                else: sells = [(pos["qty"], max(float(row.low), float(row.close) * (1 - cfg["slippage"])), "TIME")]
            final_reason = None
            for qty, price, reason in sells:
                amount = qty * price
                proceeds = amount - commission(amount) - transfer(amount) - sell_tax(amount, date)
                cash += proceeds; pos["realized"] += proceeds; pos["qty"] -= qty
                final_reason = reason
            if pos["qty"] <= 1e-9:
                trades.append({"symbol": symbol, "entry_date": pos["entry_date"], "exit_date": date,
                               "reason": final_reason, "probability": pos["probability"], "pnl": pos["realized"],
                               "return": pos["realized"] / pos["initial_cost"],
                               "tp20_triggered": bool(pos["half"])})
                del positions[symbol]
        equity = cash + sum(p["qty"] * float(day.loc[s, "close"]) for s, p in positions.items() if s in day.index)
        curve.append({"date": date, "equity": equity})
        pending = signal_by_date.get(date, pd.DataFrame())
    curve = pd.DataFrame(curve)
    if curve.empty: return {}, curve, pd.DataFrame(trades)
    total_return = curve.equity.iloc[-1] / curve.equity.iloc[0] - 1
    years = (curve.date.iloc[-1] - curve.date.iloc[0]).days / 365.25
    annualized = (curve.equity.iloc[-1] / curve.equity.iloc[0]) ** (1 / years) - 1
    drawdown = curve.equity / curve.equity.cummax() - 1
    stats = {"annualized_return": float(annualized), "total_return": float(total_return),
             "max_drawdown": float(drawdown.min()), "final_equity": float(curve.equity.iloc[-1]),
             "trades": len(trades), "signals": int(len(scored)), "peak_positions": int(peak_positions),
             **{"rejected_" + k: int(v) for k, v in rejected.items()}}
    closed = pd.DataFrame(trades)
    if not closed.empty:
        stats["win_rate"] = float(closed["return"].gt(0).mean())
        stats["mean_trade_return"] = float(closed["return"].mean())
    return stats, curve, pd.DataFrame(trades)


def add_benchmark_metrics(stats: dict, curve: pd.DataFrame, benchmark: pd.DataFrame) -> dict:
    joined = curve[["date", "equity"]].merge(benchmark[["date", "close"]], on="date", how="inner").dropna()
    if len(joined) < 2:
        raise ValueError("insufficient overlapping strategy and benchmark dates")
    years = (joined.date.iloc[-1] - joined.date.iloc[0]).days / 365.25
    sg = joined.equity.iloc[-1] / joined.equity.iloc[0]
    bg = joined.close.iloc[-1] / joined.close.iloc[0]
    sr = joined.equity.pct_change().dropna()
    br = joined.close.pct_change().dropna()
    active = sr - br
    benchmark_dd = joined.close / joined.close.cummax() - 1
    tracking_error = float(active.std(ddof=1) * np.sqrt(252))
    beta = float(np.cov(sr, br, ddof=1)[0, 1] / np.var(br, ddof=1)) if np.var(br, ddof=1) > 0 else np.nan
    alpha = float((sr.mean() - beta * br.mean()) * 252) if np.isfinite(beta) else np.nan
    stats.update({
        "benchmark": "000688.SH",
        "benchmark_total_return": float(bg - 1),
        "benchmark_annualized_return": float(bg ** (1 / years) - 1),
        "benchmark_max_drawdown": float(benchmark_dd.min()),
        "excess_total_return": float(sg - bg),
        "geometric_excess_annualized": float((sg / bg) ** (1 / years) - 1),
        "information_ratio": float(active.mean() / active.std(ddof=1) * np.sqrt(252)) if active.std(ddof=1) > 0 else np.nan,
        "tracking_error": tracking_error,
        "alpha_annualized": alpha,
        "beta": beta,
    })
    X = np.column_stack([np.ones(len(br)), br.to_numpy()])
    y = sr.to_numpy(); coef = np.linalg.lstsq(X, y, rcond=None)[0]
    residual = y - X @ coef; dof = len(y) - 2
    covariance = (residual @ residual / dof) * np.linalg.inv(X.T @ X)
    stats["alpha_t_stat"] = float(coef[0] / np.sqrt(covariance[0, 0]))
    joined["strategy_normalized"] = joined.equity / joined.equity.iloc[0]
    joined["benchmark_normalized"] = joined.close / joined.close.iloc[0]
    joined["relative_nav"] = joined.strategy_normalized / joined.benchmark_normalized
    return stats, joined


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    benchmark = pd.read_parquet(ROOT / "data" / "benchmark" / "000688.SH.parquet").sort_values("date")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["barrier_label"] = triple_barrier_label(ds, cfg["label_horizon_days"], cfg["stop_loss"], cfg["take_profit_all"])
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["barrier_label"])
    train = ds[ds.date <= pd.Timestamp("2024-10-31")]
    test = ds[ds.date >= pd.Timestamp("2025-01-01")].copy()
    out = ROOT / "outputs" / "star_10rounds"; out.mkdir(parents=True, exist_ok=True)
    results = []
    for trial in TRIALS:
        model = HistGradientBoostingClassifier(max_iter=trial.max_iter, learning_rate=trial.learning_rate,
            max_leaf_nodes=trial.max_leaf_nodes, l2_regularization=trial.l2, class_weight="balanced", random_state=42)
        model.fit(train[FEATURES], train.barrier_label.astype(int))
        train_p = model.predict_proba(train[FEATURES])[:, 1]
        test["probability"] = model.predict_proba(test[FEATURES])[:, 1]
        stats, curve, trades = portfolio_backtest(raw, test, cfg, trial, benchmark)
        stats, comparison = add_benchmark_metrics(stats, curve, benchmark)
        stats.update({"round": trial.name, "threshold": trial.threshold, "top_per_day": trial.top_per_day,
                      "max_positions": trial.max_positions, "train_auc": float(roc_auc_score(train.barrier_label, train_p)),
                      "train_precision": float(precision_score(train.barrier_label, train_p >= trial.threshold, zero_division=0))})
        results.append(stats); curve.to_csv(out / f"{trial.name}_equity.csv", index=False)
        comparison.to_csv(out / f"{trial.name}_benchmark.csv", index=False)
        trades.to_csv(out / f"{trial.name}_trades.csv", index=False)
        print(json.dumps(stats, ensure_ascii=False), flush=True)
        joblib.dump({"model": model, "features": FEATURES, "trial": trial.__dict__, "config": cfg}, out / f"{trial.name}.joblib")
    table = pd.DataFrame(results).sort_values("annualized_return", ascending=False)
    table.to_csv(out / "rounds.csv", index=False, encoding="utf-8-sig")
    best = table.iloc[0].to_dict(); (out / "best.json").write_text(json.dumps(best, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRANKING\n", table.to_string(index=False))


if __name__ == "__main__":
    main()
