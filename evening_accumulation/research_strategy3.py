"""Research Strategy 3 on top of frozen Strategy 2 low-risk v1."""
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
OUT = ROOT / "outputs" / "strategy3_research"
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
    "strategy2": "基准1-2止损过滤",
    "bear_probability": "走步熊市概率软缩放",
    "downside_diversify": "下行相关性风险分散",
    "health_monitor": "模型健康度软调节",
    "bear_downside": "熊市概率+下行分散",
    "bear_health": "熊市概率+健康监控",
    "downside_health": "下行分散+健康监控",
    "strategy3_combo": "三方向组合候选",
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


MARKET_FEATURES = [
    "mret5", "mret20", "mret60", "mvol20", "breadth1", "breadth20",
    "dispersion", "downside_share", "common_risk", "avg_dd20",
]


def build_walkforward_bear_probability(qfq: pd.DataFrame) -> tuple[dict, dict]:
    """Quarterly expanding-window model; target is a future 20-session 10% market drawdown."""
    px = qfq.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = px.pct_change(fill_method=None)
    mret = rets.mean(axis=1)
    nav = (1.0 + mret.fillna(0.0)).cumprod()
    frame = pd.DataFrame(index=px.index)
    frame["mret5"] = nav.pct_change(5)
    frame["mret20"] = nav.pct_change(20)
    frame["mret60"] = nav.pct_change(60)
    frame["mvol20"] = mret.rolling(20).std()
    frame["breadth1"] = (rets > 0).mean(axis=1).rolling(5).mean()
    frame["breadth20"] = (px / px.shift(20) - 1 > 0).mean(axis=1)
    frame["dispersion"] = rets.std(axis=1).rolling(5).mean()
    frame["downside_share"] = (rets < -0.03).mean(axis=1).rolling(5).mean()
    cross_var = rets.var(axis=1).rolling(20).mean()
    frame["common_risk"] = (mret.rolling(20).var() / cross_var.replace(0, np.nan)).clip(0, 1)
    dd20 = px / px.rolling(20).max() - 1
    frame["avg_dd20"] = dd20.mean(axis=1)
    forward_min = pd.concat([nav.shift(-i) / nav - 1 for i in range(1, 21)], axis=1).min(axis=1)
    frame["bear"] = (forward_min <= -0.10).astype(float)
    frame.loc[frame.index[-20:], "bear"] = np.nan
    frame = frame.replace([np.inf, -np.inf], np.nan)
    predictions = pd.Series(0.0, index=frame.index)
    trained_quarters = []
    quarters = pd.period_range("2021Q1", "2026Q3", freq="Q")
    for quarter in quarters:
        test_start = quarter.start_time.normalize()
        test_end = min(quarter.end_time.normalize(), END)
        eligible_dates = frame.index[frame.index < test_start]
        if len(eligible_dates) <= 20:
            continue
        purge_end = eligible_dates[-21]
        train = frame[(frame.index <= purge_end) & frame.bear.notna()].dropna(subset=MARKET_FEATURES)
        test = frame[(frame.index >= test_start) & (frame.index <= test_end)].dropna(subset=MARKET_FEATURES)
        if len(train) < 180 or train.bear.nunique() < 2 or test.empty:
            continue
        model = HistGradientBoostingClassifier(
            max_iter=80, learning_rate=0.04, max_leaf_nodes=7,
            l2_regularization=5.0, class_weight="balanced", random_state=91,
        )
        model.fit(train[MARKET_FEATURES], train.bear.astype(int))
        predictions.loc[test.index] = model.predict_proba(test[MARKET_FEATURES])[:, 1]
        trained_quarters.append({
            "quarter": str(quarter), "train_end": str(purge_end.date()),
            "train_rows": int(len(train)), "bear_rate": float(train.bear.mean()),
        })
    return predictions.to_dict(), {
        "target": "next 20 sessions equal-weight STAR drawdown <= -10%",
        "method": "quarterly expanding window with 20-session purge",
        "trained_quarters": trained_quarters,
    }


def prepare() -> tuple[Prepared, dict]:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs/event_recognition_v2/event_model.joblib")
    ds = features(qfq, cfg)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES).copy()
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    ds, stop_meta = add_stop_probability(ds)
    bear_probability, bear_meta = build_walkforward_bear_probability(qfq)
    ds["market_ret20"] = ds.groupby("date")["ret20"].transform("mean")
    ds["market_breadth"] = ds.groupby("date")["ret20"].transform(lambda s: float((s > 0).mean()))
    market = ds.groupby("date").agg(
        market_ret20=("market_ret20", "first"), market_breadth=("market_breadth", "first"),
        signal_count=("probability", lambda s: int((s >= THRESHOLD).sum())),
    )
    market["bear_probability"] = [float(bear_probability.get(d, 0.0)) for d in market.index]
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
    ), {"stop_model": stop_meta, "bear_model": bear_meta}


def select_candidates(prep: Prepared, signal_date, held, modes: set[str]) -> list[dict]:
    frame = prep.candidates_by_date.get(signal_date)
    if frame is None or frame.empty:
        return []
    x = frame.copy()
    # Strategy 2 is the immutable base for every Strategy 3 experiment.
    x = x[x.stop_probability <= 0.50]
    x["rank_score"] = x.probability - 0.22 * x.stop_probability
    downside_mode = "downside_diversify" in modes
    if downside_mode and held:
        hist = prep.returns.loc[:signal_date].tail(60)
        negative_market = hist.mean(axis=1) < 0
        hist = hist.loc[negative_market]
        held_symbols = [s for s in held if s in hist.columns]
        penalties = []
        for symbol in x.symbol:
            if symbol not in hist.columns or len(hist) < 15 or not held_symbols:
                penalties.append(0.0)
                continue
            corr = hist[held_symbols].corrwith(hist[symbol]).replace([np.inf, -np.inf], np.nan)
            penalties.append(max(0.0, float(corr.max())) if corr.notna().any() else 0.0)
        x["downside_corr"] = penalties
        x["rank_score"] -= 0.10 * x["downside_corr"]
    x = x.sort_values("rank_score", ascending=False)
    limit = TOP_PER_DAY
    selected = []
    for row in x.itertuples():
        if row.symbol in held:
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
    recent_returns = []
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
        candidates = select_candidates(prep, previous_date, positions, modes)
        quality_fraction = BASE_FRACTION
        if "bear_probability" in modes:
            bear_p = float(market.get("bear_probability", 0.0))
            if bear_p >= 0.70:
                quality_fraction = 0.055
            elif bear_p >= 0.55:
                quality_fraction = 0.075
            elif bear_p >= 0.40:
                quality_fraction = 0.09
        if "health_monitor" in modes and len(recent_returns) >= 15:
            last = recent_returns[-15:]
            stops = recent_reasons[-15:].count("STOP") / 15.0
            if float(np.mean(last)) < -0.01 and stops >= 0.40:
                quality_fraction = min(quality_fraction, 0.075)
                candidates = [x for x in candidates if x["probability"] >= THRESHOLD + 0.015]
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
                recent_reasons = recent_reasons[-20:]
                recent_returns.append(ret)
                recent_returns = recent_returns[-20:]
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
    prep, model_meta = prepare()
    mode_map = {
        "strategy2": set(),
        "bear_probability": {"bear_probability"},
        "downside_diversify": {"downside_diversify"},
        "health_monitor": {"health_monitor"},
        "bear_downside": {"bear_probability", "downside_diversify"},
        "bear_health": {"bear_probability", "health_monitor"},
        "downside_health": {"downside_diversify", "health_monitor"},
        "strategy3_combo": {"bear_probability", "downside_diversify", "health_monitor"},
    }
    summaries, annual = [], []
    for name in VARIANTS:
        modes = mode_map[name]
        summary, curve, trades = simulate(prep, modes)
        oos, _, _ = simulate(prep, modes, pd.Timestamp("2025-01-01"), END)
        summary.update({"variant": name, "name_cn": VARIANTS[name],
                        "oos_annualized": oos["annualized_return"],
                        "oos_max_drawdown": oos["max_drawdown"]})
        summary["score"] = (summary["annualized_return"] - 0.55 * abs(summary["max_drawdown"])
                            + 0.70 * oos["annualized_return"] - 0.55 * abs(oos["max_drawdown"]))
        summaries.append(summary)
        annual.extend(annual_rows(curve, name))
        trades.to_csv(OUT / f"trades_{name}.csv", index=False, encoding="utf-8-sig")
    ranking = pd.DataFrame(summaries).sort_values("score", ascending=False)
    ranking.to_csv(OUT / "direction_ranking.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(annual).to_csv(OUT / "continuous_annual.csv", index=False, encoding="utf-8-sig")
    base_row = ranking[ranking.variant == "strategy2"].iloc[0]
    eligible = ranking[
        (ranking.variant != "strategy2")
        & (ranking.annualized_return >= base_row.annualized_return * 0.85)
        & (ranking.max_drawdown > base_row.max_drawdown)
    ].sort_values(["max_drawdown", "score"], ascending=[False, False])
    candidate = eligible.iloc[0].variant if len(eligible) else "strategy2"
    candidate_modes = mode_map[candidate]
    periods = [
        ("2020", "2020-01-01", "2020-12-31"),
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026H1-7", "2026-01-01", "2026-07-31"),
    ]
    yearly_variants = {"strategy2": set(), candidate: candidate_modes}
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
    start_rows = []
    for year in range(2020, 2027):
        for variant_name, modes in yearly_variants.items():
            result, _, _ = simulate(prep, modes, pd.Timestamp(f"{year}-01-01"), END)
            start_rows.append({
                "variant": variant_name, "start_year": year,
                "initial_cash": INITIAL_CASH, "final_equity": result["final_equity"],
                "total_return": result["total_return"],
                "annualized_return": result["annualized_return"],
                "max_drawdown": result["max_drawdown"],
                "closed_trades": result["closed_trades"], "win_rate": result["win_rate"],
            })
    pd.DataFrame(start_rows).to_csv(
        OUT / "start_year_to_20260731.csv", index=False, encoding="utf-8-sig"
    )
    (OUT / "selection.json").write_text(json.dumps({
        "score_winner": ranking.iloc[0].variant,
        "candidate": candidate, "candidate_cn": VARIANTS[candidate],
        "candidate_rule": "annualized >= 85% of Strategy2 and lower drawdown; choose lowest drawdown",
        "model_meta": model_meta, "score_formula": "full CAGR-0.55|MDD|+0.70 OOS CAGR-0.55|OOS MDD|",
        "oos": "2025-01-01 to 2026-07-31",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ranking[["variant", "name_cn", "annualized_return", "max_drawdown",
                   "oos_annualized", "oos_max_drawdown", "score"]].to_string(index=False))
    print("CANDIDATE", candidate)


if __name__ == "__main__":
    main()
