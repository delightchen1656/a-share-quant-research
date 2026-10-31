from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


FEATURES = [
    "ret5", "ret20", "ret60", "range20", "range60", "dd20", "vol20", "vol60",
    "volume_ratio", "volume_cv", "up_volume_share", "pv_corr", "close_pos60",
    "turn20", "amount20", "breakout_gap", "rise_from_low60", "volume_spike",
]

BASE_RULES = {
    "min_listing_sessions": 120,
    "min_avg_amount_20": 50_000_000.0,
    "exclude_st": True,
    "max_holding_sessions": 20,
    "stop_loss": 0.07,
    "take_profit_half": 0.15,
    "take_profit_all": 0.30,
    "commission_each_side": 0.0003,
    "slippage_each_side": 0.0005,
    "initial_cash": 1_000_000.0,
}


SCHEMES: dict[str, dict[str, Any]] = {
    "dynamic_balanced": {
        "health": {"min_matured": 12, "event_window": 30, "trade_window": 8,
                   "stress_event_rate": 0.15, "healthy_event_rate": 0.25,
                   "stress_trade_mean": -0.02, "healthy_trade_mean": 0.0},
        "states": {
            "healthy": {"event_add": 0.00, "stop_risk_cap": 0.50, "position_fraction": 0.20, "max_positions": 5, "cooldown_sessions": 0},
            "caution": {"event_add": 0.04, "stop_risk_cap": 0.40, "position_fraction": 0.125, "max_positions": 4, "cooldown_sessions": 2},
            "stressed": {"event_add": 0.08, "stop_risk_cap": 0.30, "position_fraction": 0.08, "max_positions": 2, "cooldown_sessions": 5},
        },
    },
    "dynamic_defensive": {
        "health": {"min_matured": 12, "event_window": 30, "trade_window": 8,
                   "stress_event_rate": 0.15, "healthy_event_rate": 0.25,
                   "stress_trade_mean": -0.02, "healthy_trade_mean": 0.0},
        "states": {
            "healthy": {"event_add": 0.02, "stop_risk_cap": 0.45, "position_fraction": 1 / 6, "max_positions": 5, "cooldown_sessions": 1},
            "caution": {"event_add": 0.06, "stop_risk_cap": 0.35, "position_fraction": 0.10, "max_positions": 3, "cooldown_sessions": 3},
            "stressed": {"event_add": 0.10, "stop_risk_cap": 0.25, "position_fraction": 0.05, "max_positions": 2, "cooldown_sessions": 8},
        },
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _one(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").copy()
    c, v = g.close.astype(float), g.volume.astype(float)
    r = c.pct_change(fill_method=None)
    vchg = v.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
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
    g["turn20"] = g.turn.rolling(20).mean()
    g["amount20"] = np.log1p(g.amount.rolling(20).mean())
    g["breakout_gap"] = c / c.shift(1).rolling(60).max() - 1
    g["listing_session"] = np.arange(1, len(g) + 1)
    return g.replace([np.inf, -np.inf], np.nan)


def make_features(qfq: pd.DataFrame) -> pd.DataFrame:
    qfq = qfq.copy()
    qfq["date"] = pd.to_datetime(qfq["date"])
    parts = [_one(g) for _, g in qfq.groupby("symbol", sort=False)]
    ds = pd.concat(parts, ignore_index=True)
    ok = ds.listing_session.ge(BASE_RULES["min_listing_sessions"])
    ok &= np.expm1(ds.amount20).ge(BASE_RULES["min_avg_amount_20"])
    ok &= ds.ret5.le(0.12) & ds.ret20.le(0.20) & ds.rise_from_low60.le(0.30)
    ok &= ds.volume_spike.le(5) & ds.high.ne(ds.low) & ds.pctChg.astype(float).lt(19.5)
    ok &= ds.tradestatus.astype(str).eq("1")
    if BASE_RULES["exclude_st"]:
        ok &= ds.isST.astype(str).ne("1")
    return ds.loc[ok].dropna(subset=FEATURES).copy()


def load_snapshot(inputs: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    def load_dir(name: str) -> pd.DataFrame:
        frames = [pd.read_parquet(p) for p in sorted((inputs / name).glob("*.parquet"))]
        if not frames:
            raise FileNotFoundError(f"no parquet files in {inputs / name}")
        x = pd.concat(frames, ignore_index=True)
        x["date"] = pd.to_datetime(x["date"])
        return x.sort_values(["date", "symbol"]).reset_index(drop=True)
    return load_dir("raw"), load_dir("qfq")


def score_candidates(qfq: pd.DataFrame, model_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        event = joblib.load(model_dir / "event_model.joblib")
        stop = joblib.load(model_dir / "stop_risk_model.joblib")
    if list(event["features"]) != FEATURES or list(stop["features"]) != FEATURES:
        raise ValueError("frozen model feature contract mismatch")
    ds = make_features(qfq)
    ds["event_probability"] = event["model"].predict_proba(ds[FEATURES])[:, 1]
    ds["stop_risk_probability"] = stop["model"].predict_proba(ds[FEATURES])[:, 1]
    keep = ["date", "symbol", "close", "event_probability", "stop_risk_probability"]
    meta = {
        "event_threshold": float(event["threshold"]),
        "event_horizon": int(event["horizon"]),
        "event_target": float(event["target"]),
        "warnings": sorted({str(w.message) for w in caught}),
    }
    return ds[keep].sort_values(["date", "event_probability", "symbol"], ascending=[True, False, True]).reset_index(drop=True), meta


def add_matured_event_outcomes(scores: pd.DataFrame, qfq: pd.DataFrame, horizon: int, target: float) -> pd.DataFrame:
    result = scores.copy()
    result["maturity_date"] = pd.NaT
    result["event_hit"] = np.nan
    qmap = {s: g.sort_values("date").reset_index(drop=True) for s, g in qfq.groupby("symbol", sort=False)}
    idxmap = {s: {pd.Timestamp(d): i for i, d in enumerate(g.date)} for s, g in qmap.items()}
    mats, hits = [], []
    for r in result.itertuples(index=False):
        g = qmap.get(r.symbol); i = idxmap.get(r.symbol, {}).get(pd.Timestamp(r.date))
        if g is None or i is None or i + horizon >= len(g):
            mats.append(pd.NaT); hits.append(np.nan); continue
        future = g.iloc[i + 1:i + 1 + horizon]
        mats.append(pd.Timestamp(future.iloc[-1].date))
        hits.append(float(float(future.high.max()) / float(r.close) - 1 >= target))
    result["maturity_date"] = mats
    result["event_hit"] = hits
    return result


def _health_state(scheme: dict[str, Any], matured: list[float], trade_returns: list[float]) -> tuple[str, dict[str, float | int | None]]:
    h = scheme["health"]
    ev = matured[-int(h["event_window"]):]
    tr = trade_returns[-int(h["trade_window"]):]
    ev_rate = float(np.mean(ev)) if ev else None
    tr_mean = float(np.mean(tr)) if tr else None
    if len(ev) < int(h["min_matured"]):
        state = "caution"
    elif ev_rate < h["stress_event_rate"] or (len(tr) >= 4 and tr_mean < h["stress_trade_mean"]):
        state = "stressed"
    elif ev_rate >= h["healthy_event_rate"] and len(tr) >= 4 and tr_mean >= h["healthy_trade_mean"]:
        state = "healthy"
    else:
        state = "caution"
    return state, {"matured_count": len(ev), "event_hit_rate": ev_rate, "completed_trade_count": len(tr), "completed_trade_mean": tr_mean}


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: float
    initial_shares: float
    basis_cash: float
    sessions: int = 0
    half_done: bool = False
    realized_cash: float = 0.0


def simulate(raw: pd.DataFrame, scored: pd.DataFrame, event_threshold: float, scheme: dict[str, Any], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = raw.copy(); raw["date"] = pd.to_datetime(raw.date)
    scored = scored.copy(); scored["date"] = pd.to_datetime(scored.date); scored["maturity_date"] = pd.to_datetime(scored.maturity_date)
    dates = sorted(d for d in raw.date.unique() if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end))
    raw_by_date = {pd.Timestamp(d): g.set_index("symbol") for d, g in raw[raw.date.isin(dates)].groupby("date")}
    sig_by_date = {pd.Timestamp(d): g for d, g in scored.groupby("date")}
    mature_by_date = {pd.Timestamp(d): g for d, g in scored.dropna(subset=["maturity_date"]).groupby("maturity_date")}
    cash = float(BASE_RULES["initial_cash"]); positions: dict[str, Position] = {}; pending: list[dict[str, Any]] = []
    matured: list[float] = []; trade_returns: list[float] = []; last_exit_index: dict[str, int] = {}
    trades: list[dict[str, Any]] = []; decisions: list[dict[str, Any]] = []; equity_rows: list[dict[str, Any]] = []
    for di, date in enumerate(dates):
        date = pd.Timestamp(date); day = raw_by_date.get(date)
        if day is None: continue
        # Orders were selected using only information available at the prior close.
        for order in sorted(pending, key=lambda x: (-x["event_probability"], x["symbol"])):
            symbol = order["symbol"]
            if symbol in positions or symbol not in day.index or len(positions) >= order["max_positions"]:
                continue
            row = day.loc[symbol]
            if isinstance(row, pd.DataFrame): row = row.iloc[0]
            if str(row.tradestatus) != "1" or float(row.open) <= 0: continue
            mark_equity = cash + sum(p.shares * (float(day.loc[s].close) if s in day.index else p.entry_price) for s, p in positions.items())
            budget = min(cash, mark_equity * float(order["position_fraction"]))
            entry = float(row.open) * (1 + BASE_RULES["slippage_each_side"])
            shares = budget / (entry * (1 + BASE_RULES["commission_each_side"]))
            if shares <= 0: continue
            paid = shares * entry * (1 + BASE_RULES["commission_each_side"]); cash -= paid
            positions[symbol] = Position(symbol, date, entry, shares, shares, paid)
        pending = []
        # Intraday exits. Original stop/take-profit geometry is invariant across schemes.
        for symbol in list(positions):
            p = positions[symbol]
            if symbol not in day.index: continue
            row = day.loc[symbol]
            if isinstance(row, pd.DataFrame): row = row.iloc[0]
            if str(row.tradestatus) != "1": continue
            p.sessions += 1; exit_reason = None; exit_price = None
            stop_px = p.entry_price * (1 - BASE_RULES["stop_loss"])
            tp_half = p.entry_price * (1 + BASE_RULES["take_profit_half"])
            tp_all = p.entry_price * (1 + BASE_RULES["take_profit_all"])
            if float(row.low) <= stop_px:
                exit_reason, exit_price = "STOP", stop_px
            else:
                if not p.half_done and float(row.high) >= tp_half:
                    sell = p.shares * 0.5; proceeds = sell * tp_half * (1 - BASE_RULES["commission_each_side"])
                    cash += proceeds; p.realized_cash += proceeds; p.shares -= sell; p.half_done = True
                if float(row.high) >= tp_all:
                    exit_reason, exit_price = "TP30", tp_all
                elif p.sessions >= BASE_RULES["max_holding_sessions"]:
                    exit_reason, exit_price = "TIME", float(row.close) * (1 - BASE_RULES["slippage_each_side"])
            if exit_reason:
                proceeds = p.shares * float(exit_price) * (1 - BASE_RULES["commission_each_side"])
                cash += proceeds; total = p.realized_cash + proceeds
                ret = total / p.basis_cash - 1
                trade_returns.append(float(ret)); last_exit_index[symbol] = di
                trades.append({"entry_date": p.entry_date, "exit_date": date, "symbol": symbol, "return": ret, "reason": exit_reason})
                del positions[symbol]
        if date in mature_by_date:
            matured.extend(mature_by_date[date].event_hit.dropna().astype(float).tolist())
        state, health = _health_state(scheme, matured, trade_returns)
        params = scheme["states"][state]
        today = sig_by_date.get(date)
        if today is not None:
            threshold = min(0.999999, event_threshold + float(params["event_add"]))
            eligible = today[(today.event_probability >= threshold) & (today.stop_risk_probability <= params["stop_risk_cap"])]
            for r in eligible.sort_values(["event_probability", "symbol"], ascending=[False, True]).itertuples(index=False):
                if r.symbol in positions: continue
                last = last_exit_index.get(r.symbol, -10**9)
                if di - last <= int(params["cooldown_sessions"]): continue
                pending.append({"symbol": r.symbol, "event_probability": float(r.event_probability),
                                "position_fraction": float(params["position_fraction"]), "max_positions": int(params["max_positions"])})
        close_value = cash
        for symbol, p in positions.items():
            px = float(day.loc[symbol].close) if symbol in day.index else p.entry_price
            close_value += p.shares * px
        equity_rows.append({"date": date, "equity": close_value, "cash": cash, "positions": len(positions), "state": state})
        decisions.append({"date": date, "state": state, **health, **params, "orders_for_next_open": len(pending)})
    return pd.DataFrame(equity_rows), pd.DataFrame(trades), pd.DataFrame(decisions)


def metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    if equity.empty:
        return {"return": None, "annualized_return": None, "max_drawdown": None, "sharpe": None, "trades": 0}
    eq = equity.equity.astype(float); daily = eq.pct_change().fillna(0.0)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    years = max(len(eq) / 252.0, 1 / 252.0)
    ann = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1)
    dd = eq / eq.cummax() - 1
    sharpe = float(math.sqrt(252) * daily.mean() / daily.std(ddof=0)) if daily.std(ddof=0) > 0 else None
    return {"return": total, "annualized_return": ann, "max_drawdown": float(dd.min()), "sharpe": sharpe,
            "trades": int(len(trades)), "win_rate": float((trades["return"] > 0).mean()) if len(trades) else None,
            "mean_trade_return": float(trades["return"].mean()) if len(trades) else None,
            "ending_equity": float(eq.iloc[-1])}

