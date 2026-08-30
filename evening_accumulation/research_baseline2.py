"""Research ten orthogonal improvements on top of frozen Baseline 1-1."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from src.data import load_panel
from src.model import FEATURES, eligible, features


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "baseline2_research"
START = pd.Timestamp("2020-01-01")
END = pd.Timestamp("2026-07-31")
INITIAL_CASH = 1_000_000.0
THRESHOLD = 0.689688
TOP_PER_DAY = 8
MAX_POSITIONS = 14
BASE_FRACTION = 0.10
STOP_LOSS = 0.07
TAKE_HALF = 0.24
TAKE_ALL = 0.34
MAX_CALENDAR_DAYS = 30
SLIPPAGE = 0.002
BROKER_COMMISSION_RATE = 0.0003
TRANSFER_FEE_RATE = 0.00001
MIN_COMMISSION_CNY = 5.0
MIN_STAR_BUY = 200


VARIANTS = {
    "baseline1": "基准1-1",
    "stop_risk_filter": "先止损概率过滤",
    "low_vol_filter": "高波动信号过滤",
    "volatility_sizing": "波动率反向仓位",
    "correlation_dedup": "高相关候选去重",
    "market_breadth_gate": "科创普跌广度过滤",
    "opportunity_quality": "机会质量控制仓位",
    "crowding_threshold": "信号拥挤提高阈值",
    "stop_cooldown": "连续止损冷却",
    "drawdown_throttle": "组合回撤限制新增仓位",
    "trailing_profit": "盈利后移动止盈",
}


def fee(amount: float) -> float:
    return max(MIN_COMMISSION_CNY, amount * BROKER_COMMISSION_RATE) + amount * TRANSFER_FEE_RATE


def stamp_tax(amount: float, date: pd.Timestamp) -> float:
    return amount * (0.0005 if date >= pd.Timestamp("2023-08-28") else 0.001)


def limit_price(previous_close: float, multiplier: float) -> float:
    return np.floor(previous_close * multiplier * 100.0 + 0.5) / 100.0


def add_stop_probability(ds: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Predict whether -7% is touched before +24% in the next 22 sessions."""
    chunks = []
    for _, g in ds.groupby("symbol", sort=False):
        g = g.sort_values("date").copy()
        base = g["close"].to_numpy(float)
        opens = g["open"].to_numpy(float)
        n = len(g)
        stop_first = np.full(n, np.nan)
        for i in range(n):
            future = opens[i + 1:min(n, i + 23)] / base[i] - 1.0
            if len(future) < 10:
                continue
            stop_idx = np.flatnonzero(future <= -STOP_LOSS)
            profit_idx = np.flatnonzero(future >= TAKE_HALF)
            si = stop_idx[0] if len(stop_idx) else 10_000
            pi = profit_idx[0] if len(profit_idx) else 10_000
            stop_first[i] = float(si < pi)
        g["stop_first"] = stop_first
        chunks.append(g)
    x = pd.concat(chunks, ignore_index=True)
    train = x[(x.date <= "2024-12-31") & x.stop_first.notna()].copy()
    model = HistGradientBoostingClassifier(
        max_iter=120, learning_rate=0.05, max_leaf_nodes=15,
        l2_regularization=2.0, class_weight="balanced", random_state=73,
    )
    model.fit(train[FEATURES], train.stop_first.astype(int))
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "training_end": "2024-12-31",
            "label": "next_22_sessions_stop7_before_profit24",
        },
        OUT / "stop_risk_model.joblib",
    )
    x["stop_probability"] = model.predict_proba(x[FEATURES])[:, 1]
    meta = {
        "train_end": "2024-12-31", "train_rows": int(len(train)),
        "train_stop_rate": float(train.stop_first.mean()),
        "definition": "next 22 sessions: -7% open touched before +24% open",
    }
    return x, meta


@dataclass
class Prepared:
    raw_by_date: dict
    candidates_by_date: dict
    market_by_date: dict
    returns: pd.DataFrame
    dates: list


def prepare() -> tuple[Prepared, dict]:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs/event_recognition_v2/event_model.joblib")
    ds = features(qfq, cfg)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES).copy()
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    ds, stop_meta = add_stop_probability(ds)
    ds["market_ret20"] = ds.groupby("date")["ret20"].transform("mean")
    ds["market_breadth"] = ds.groupby("date")["ret20"].transform(lambda s: float((s > 0).mean()))
    market = ds.groupby("date").agg(
        market_ret20=("market_ret20", "first"), market_breadth=("market_breadth", "first"),
        signal_count=("probability", lambda s: int((s >= THRESHOLD).sum())),
    )
    candidate_cols = ["symbol", "probability", "stop_probability", "vol20", "ret20"]
    candidates = {
        date: g[g.probability >= THRESHOLD].sort_values("probability", ascending=False)[candidate_cols]
        for date, g in ds.groupby("date")
    }
    q = qfq[(qfq.date >= "2019-10-01") & (qfq.date <= END)].copy()
    returns = q.pivot(index="date", columns="symbol", values="close").pct_change(fill_method=None)
    raw = raw[(raw.date >= START) & (raw.date <= END)].copy()
    raw_by_date = {date: day.set_index("symbol") for date, day in raw.groupby("date")}
    return Prepared(
        raw_by_date=raw_by_date, candidates_by_date=candidates,
        market_by_date=market.to_dict("index"), returns=returns,
        dates=sorted(raw_by_date),
    ), stop_meta


def select_candidates(prep: Prepared, signal_date, held, modes: set[str]) -> list[dict]:
    frame = prep.candidates_by_date.get(signal_date)
    if frame is None or frame.empty:
        return []
    x = frame.copy()
    if "stop_risk_filter" in modes:
        x = x[x.stop_probability <= 0.50]
        x["rank_score"] = x.probability - 0.22 * x.stop_probability
    else:
        x["rank_score"] = x.probability
    if "low_vol_filter" in modes:
        x = x[x.vol20 <= 0.040]
    if "crowding_threshold" in modes:
        count = prep.market_by_date.get(signal_date, {}).get("signal_count", 0)
        if count >= 45:
            x = x[x.probability >= 0.74]
    x = x.sort_values("rank_score", ascending=False)
    limit = 4 if "correlation_dedup" in modes else TOP_PER_DAY
    selected = []
    for row in x.itertuples():
        if row.symbol in held:
            continue
        if "correlation_dedup" in modes and selected:
            hist = prep.returns.loc[:signal_date].tail(20)
            correlations = [hist[row.symbol].corr(hist[item["symbol"]]) for item in selected
                            if row.symbol in hist and item["symbol"] in hist]
            if correlations and np.nanmax(correlations) >= 0.72:
                continue
        selected.append({
            "symbol": row.symbol, "probability": float(row.probability),
            "stop_probability": float(row.stop_probability), "vol20": float(row.vol20),
        })
        if len(selected) >= limit:
            break
    return selected


def simulate(prep: Prepared, modes: set[str], start=START, end=END,
             initial_cash=INITIAL_CASH) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    dates = [d for d in prep.dates if start <= d <= end]
    cash = float(initial_cash)
    positions = {}
    trades = []
    curve = []
    previous_date = None
    high_water = cash
    recent_reasons = []
    cooldown = 0
    previous_close = {}
    for date in dates:
        day = prep.raw_by_date[date]
        for symbol, pos in list(positions.items()):
            if symbol not in day.index or symbol not in previous_close:
                continue
            row = day.loc[symbol]
            factor = previous_close[symbol] / float(row.preclose) if row.preclose > 0 else 1.0
            if abs(factor - 1.0) > 0.02:
                share_factor = round(factor, 1)
                if share_factor >= 1.1:
                    old_qty = pos["qty"]
                    dividend = max(0.0, previous_close[symbol] - float(row.preclose) * share_factor)
                    cash += old_qty * dividend
                    pos["qty"] = float(int(round(old_qty * share_factor)))
                    pos["entry"] = max(0.01, (pos["entry"] - dividend) / share_factor)
        equity_open = cash + sum(
            p["qty"] * float(day.loc[s, "open"]) for s, p in positions.items() if s in day.index
        )
        current_dd = equity_open / high_water - 1.0
        market = prep.market_by_date.get(previous_date, {})
        pause = False
        if "market_breadth_gate" in modes:
            pause |= market.get("market_ret20", 0) < -0.08 and market.get("market_breadth", 1) < 0.30
        if "stop_cooldown" in modes:
            if cooldown > 0:
                pause = True
                cooldown -= 1
            elif len(recent_reasons) >= 5 and recent_reasons[-5:].count("STOP") >= 3:
                pause, cooldown = True, 2
        if "drawdown_throttle" in modes and current_dd <= -0.15:
            pause = True
        candidates = [] if pause else select_candidates(prep, previous_date, positions, modes)
        quality_fraction = BASE_FRACTION
        if "opportunity_quality" in modes and candidates:
            median_p = float(np.median([x["probability"] for x in candidates]))
            quality_fraction = 0.07 if median_p < 0.76 or len(candidates) < 4 else BASE_FRACTION
        if "drawdown_throttle" in modes and current_dd <= -0.10:
            quality_fraction = min(quality_fraction, 0.07)
        for signal in candidates:
            symbol = signal["symbol"]
            if symbol in positions or len(positions) >= MAX_POSITIONS or symbol not in day.index:
                continue
            row = day.loc[symbol]
            if str(row.tradestatus) != "1" or row.open <= 0 or row.volume <= 0:
                continue
            if float(row.open) >= limit_price(float(row.preclose), 1.20) - 0.001:
                continue
            fraction = quality_fraction
            if "volatility_sizing" in modes:
                fraction *= float(np.clip(0.028 / max(signal["vol20"], 0.015), 0.55, 1.0))
            execution = float(row.open) * (1 + SLIPPAGE)
            target = equity_open * fraction
            qty = int(target / execution)
            amount = qty * execution
            total = amount + fee(amount) if qty >= MIN_STAR_BUY else np.inf
            while qty >= MIN_STAR_BUY and total > cash:
                qty -= 1
                amount = qty * execution
                total = amount + fee(amount)
            if qty < MIN_STAR_BUY:
                continue
            cash -= total
            positions[symbol] = {
                "qty": float(qty), "entry": execution, "entry_date": date,
                "half": False, "probability": signal["probability"],
                "realized": -total, "initial_cost": total, "peak": execution,
            }
        for symbol, pos in list(positions.items()):
            if symbol not in day.index or pos["entry_date"] == date:
                continue
            row = day.loc[symbol]
            if str(row.tradestatus) != "1" or row.open <= 0 or row.volume <= 0:
                continue
            if float(row.open) <= limit_price(float(row.preclose), 0.80) + 0.001:
                continue
            mark = float(row.open)
            pos["peak"] = max(pos["peak"], mark)
            target_qty, reason = None, None
            if mark <= pos["entry"] * (1 - STOP_LOSS):
                target_qty, reason = 0.0, "STOP"
            elif mark >= pos["entry"] * (1 + TAKE_ALL):
                target_qty, reason = 0.0, "TPALL"
            elif "trailing_profit" in modes and pos["peak"] >= pos["entry"] * 1.15 and mark <= pos["peak"] * 0.90:
                target_qty, reason = 0.0, "TRAIL"
            elif mark >= pos["entry"] * (1 + TAKE_HALF) and not pos["half"]:
                half = float(int(pos["qty"] / 2))
                if half >= MIN_STAR_BUY and pos["qty"] - half >= MIN_STAR_BUY:
                    target_qty, reason = half, "TPHALF"
            elif (date - pos["entry_date"]).days >= MAX_CALENDAR_DAYS:
                target_qty, reason = 0.0, "TIME"
            if target_qty is None:
                continue
            sell_qty = pos["qty"] - target_qty
            execution = mark * (1 - SLIPPAGE)
            amount = sell_qty * execution
            proceeds = amount - fee(amount) - stamp_tax(amount, date)
            cash += proceeds
            pos["realized"] += proceeds
            pos["qty"] = target_qty
            if reason == "TPHALF":
                pos["half"] = True
            if pos["qty"] <= 0:
                ret = pos["realized"] / pos["initial_cost"]
                trades.append({"symbol": symbol, "entry_date": pos["entry_date"],
                               "exit_date": date, "reason": reason, "return": ret})
                recent_reasons.append(reason)
                recent_reasons = recent_reasons[-10:]
                del positions[symbol]
        equity = cash + sum(p["qty"] * float(day.loc[s, "close"])
                            for s, p in positions.items() if s in day.index)
        high_water = max(high_water, equity)
        curve.append({"date": date, "equity": equity, "cash": cash, "positions": len(positions)})
        previous_date = date
        for symbol, row in day.iterrows():
            previous_close[symbol] = float(row.close)
    curve = pd.DataFrame(curve)
    trades = pd.DataFrame(trades)
    years = max((curve.date.iloc[-1] - curve.date.iloc[0]).days / 365.25, 1 / 12)
    total = curve.equity.iloc[-1] / initial_cash - 1
    dd = curve.equity / curve.equity.cummax() - 1
    summary = {
        "start": str(start.date()), "end": str(end.date()),
        "initial_cash": initial_cash, "final_equity": float(curve.equity.iloc[-1]),
        "total_return": float(total), "annualized_return": float((1 + total) ** (1 / years) - 1),
        "max_drawdown": float(dd.min()), "closed_trades": int(len(trades)),
        "win_rate": float((trades["return"] > 0).mean()) if len(trades) else None,
        "mean_trade_return": float(trades["return"].mean()) if len(trades) else None,
    }
    return summary, curve, trades


def annual_rows(curve: pd.DataFrame, name: str) -> list[dict]:
    rows = []
    for year, g in curve.groupby(curve.date.dt.year):
        g = g.sort_values("date")
        rows.append({
            "variant": name, "year": int(year),
            "start_equity": float(g.equity.iloc[0]), "end_equity": float(g.equity.iloc[-1]),
            "return": float(g.equity.iloc[-1] / g.equity.iloc[0] - 1),
            "max_drawdown": float((g.equity / g.equity.cummax() - 1).min()),
        })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    prep, stop_meta = prepare()
    summaries, annual = [], []
    curves = {}
    for name in VARIANTS:
        modes = set() if name == "baseline1" else {name}
        summary, curve, trades = simulate(prep, modes)
        oos, _, _ = simulate(prep, modes, pd.Timestamp("2025-01-01"), END)
        summary.update({"variant": name, "name_cn": VARIANTS[name],
                        "oos_annualized": oos["annualized_return"],
                        "oos_max_drawdown": oos["max_drawdown"]})
        summary["score"] = (summary["annualized_return"] - 0.55 * abs(summary["max_drawdown"])
                            + 0.70 * oos["annualized_return"] - 0.55 * abs(oos["max_drawdown"]))
        summaries.append(summary)
        annual.extend(annual_rows(curve, name))
        curves[name] = curve
        trades.to_csv(OUT / f"trades_{name}.csv", index=False, encoding="utf-8-sig")
    ranking = pd.DataFrame(summaries).sort_values("score", ascending=False)
    baseline = ranking[ranking.variant == "baseline1"].iloc[0]
    eligible_rank = ranking[
        (ranking.variant != "baseline1")
        & (ranking.annualized_return >= baseline.annualized_return * 0.72)
        & (ranking.oos_annualized >= baseline.oos_annualized - 0.08)
        & (
            (ranking.annualized_return - baseline.annualized_return).abs()
            + (ranking.max_drawdown - baseline.max_drawdown).abs()
            + (ranking.oos_annualized - baseline.oos_annualized).abs()
            > 1e-8
        )
    ]
    top3 = eligible_rank.head(3).variant.tolist()
    if len(top3) < 3:
        top3 = ranking[ranking.variant != "baseline1"].head(3).variant.tolist()
    combo_modes = set(top3)
    combo, combo_curve, combo_trades = simulate(prep, combo_modes)
    combo_oos, _, _ = simulate(prep, combo_modes, pd.Timestamp("2025-01-01"), END)
    combo.update({"variant": "baseline2_candidate", "name_cn": "基准1-2候选",
                  "oos_annualized": combo_oos["annualized_return"],
                  "oos_max_drawdown": combo_oos["max_drawdown"]})
    combo["score"] = (combo["annualized_return"] - 0.55 * abs(combo["max_drawdown"])
                      + 0.70 * combo_oos["annualized_return"] - 0.55 * abs(combo_oos["max_drawdown"]))
    ranking = pd.concat([ranking, pd.DataFrame([combo])], ignore_index=True).sort_values("score", ascending=False)
    annual.extend(annual_rows(combo_curve, "baseline2_candidate"))
    ranking.to_csv(OUT / "direction_ranking.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(annual).to_csv(OUT / "continuous_annual.csv", index=False, encoding="utf-8-sig")
    combo_curve.to_csv(OUT / "baseline2_equity.csv", index=False)
    combo_trades.to_csv(OUT / "baseline2_trades.csv", index=False, encoding="utf-8-sig")

    # 独立逐年回测：每个区间均重新以100万元、空仓开始。
    periods = [
        ("2020", "2020-01-01", "2020-12-31"),
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026H1-7", "2026-01-01", "2026-07-31"),
    ]
    yearly_variants = {"baseline1": set()}
    for variant in top3:
        yearly_variants[variant] = {variant}
    yearly_variants["baseline2_candidate"] = combo_modes
    independent = []
    for variant_name, modes in yearly_variants.items():
        for period_name, period_start, period_end in periods:
            yr, _, _ = simulate(
                prep, modes, pd.Timestamp(period_start), pd.Timestamp(period_end)
            )
            independent.append({
                "variant": variant_name,
                "period": period_name,
                "start": period_start,
                "end": period_end,
                "initial_cash": INITIAL_CASH,
                "ending_equity": yr["final_equity"],
                "total_return": yr["total_return"],
                "annualized_return": yr["annualized_return"],
                "max_drawdown": yr["max_drawdown"],
                "closed_trades": yr["closed_trades"],
                "win_rate": yr["win_rate"],
            })
    pd.DataFrame(independent).to_csv(
        OUT / "independent_yearly.csv", index=False, encoding="utf-8-sig"
    )
    (OUT / "selection.json").write_text(json.dumps({
        "top3": top3, "top3_cn": [VARIANTS[x] for x in top3],
        "stop_model": stop_meta, "score_formula": "full CAGR-0.55|MDD|+0.70 OOS CAGR-0.55|OOS MDD|",
        "oos": "2025-01-01 to 2026-07-31",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ranking[["variant", "name_cn", "annualized_return", "max_drawdown",
                   "oos_annualized", "oos_max_drawdown", "score"]].to_string(index=False))
    print("TOP3", top3)


if __name__ == "__main__":
    main()
