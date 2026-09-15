"""Realistic daily-bar execution audit for the upstream v5i ETF strategy.

Signal logic is retained.  Unlike upstream, close signals become next-session
open orders, with lots, commissions, slippage, suspension/limit and capacity.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
from tqdm import tqdm

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / "upstream"
sys.path.insert(0, str(UPSTREAM / "src"))
from strategy_a_share_etf_rotation import (  # noqa: E402
    BENCHMARK, ETF_POOL, annual_volatility, mean_abs_correlation, momentum_score,
)
from strategy_v2_high_low_switch import CATEGORY, compute_logbias_rsi, is_overheat  # noqa: E402
from strategy_v5e_capped import (  # noqa: E402
    DEFENSE_BASKETS, ParamsV5E, _vol_target_scale, active_defense_basket,
    apply_commodity_cap,
)

DATA = HERE / "realistic_data"
OUT = HERE / "realistic_outputs"
START_FETCH, END = "20150601", "20260731"
START = pd.Timestamp("2020-01-02")
INITIAL_CASH = 10_000_000.0
COMMISSION_RATE = 0.0002
MIN_COMMISSION = 5.0
SLIPPAGE = 0.002
VOLUME_CAP = 0.05
LOT = 100


def fetch_bar(code: str) -> pd.DataFrame:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{code}.parquet"
    if path.exists():
        d = pd.read_parquet(path)
        d.date = pd.to_datetime(d.date)
        if d.date.max() >= pd.Timestamp("2026-07-20"):
            return d
    symbol = code.split(".")[0]
    exchange = code.split(".")[1].lower()
    last_error = None
    for attempt in range(4):
        try:
            # Sina is used for raw OHLCV because the Eastmoney endpoint is prone
            # to proxy throttling during a 64-symbol audit download.
            raw = ak.fund_etf_hist_sina(symbol=f"{exchange}{symbol}")
            if raw is None or raw.empty:
                raise RuntimeError("empty response")
            rename = {"date": "date", "open": "open", "close": "close", "high": "high",
                      "low": "low", "volume": "volume", "amount": "amount"}
            d = raw.rename(columns=rename)[list(rename.values())].copy()
            d.date = pd.to_datetime(d.date)
            for c in d.columns[1:]:
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d = d[d.date.between(pd.Timestamp("2015-06-01"), pd.Timestamp("2026-07-31"))]
            d["pct_chg"] = d.close.pct_change(fill_method=None) * 100
            d["symbol"] = code
            d.to_parquet(path, index=False)
            return d
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    print(f"[warn] {code}: {last_error}")
    return pd.DataFrame()


def load_bars() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    frames = []
    for code in tqdm(ETF_POOL, desc="OHLCV"):
        d = fetch_bar(code)
        if not d.empty:
            frames.append(d)
    long = pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"])
    days = {d: q.set_index("symbol") for d, q in long.groupby("date")}
    return long, days


def metric(nav: pd.Series) -> dict:
    ret = nav.pct_change().fillna(0)
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    dd = nav / nav.cummax() - 1
    return {"final_asset": float(nav.iloc[-1]), "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1),
            "annualized_return": float((nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1),
            "max_drawdown": float(dd.min()),
            "sharpe": float(np.sqrt(252) * ret.mean() / ret.std()) if ret.std() else 0.0}


@dataclass
class OrderStats:
    turnover_value: float = 0.0
    commission: float = 0.0
    slippage_cost: float = 0.0
    blocked_limit: int = 0
    blocked_suspended: int = 0
    capacity_clipped: int = 0
    orders: int = 0


def main() -> None:
    long, days = load_bars()
    close = long.pivot(index="date", columns="symbol", values="close").sort_index().ffill(limit=5)
    close = close.loc[:pd.Timestamp(END)]
    codes = [c for c in close if c != BENCHMARK]
    returns = np.log(close[codes] / close[codes].shift(1))
    p = ParamsV5E(init_cash=INITIAL_CASH, n_momentum=3, enable_weight_caps=False,
                  max_category_weight=1.0, max_commodity_weight=0.9,
                  enable_vol_targeting=True, vol_target=0.11, vol_target_window=20,
                  defense_basket_name="B3_diversified", trailing_dd=-0.08,
                  trailing_recovery=0.03, trailing_max_days=20)
    logbias, rsi, rsi_diff = compute_logbias_rsi(close[codes], p)
    cal = close.index[close.index >= START]
    weekly = set(close.resample("W-FRI").last().index.intersection(cal))

    cash = INITIAL_CASH
    shares: dict[str, int] = {}
    pending: dict[str, float] | None = None
    current_candidates: list[str] = []
    current_vol = pd.Series(dtype=float)
    stats = OrderStats()
    nav_rows, trades, decisions = [], [], []
    trail_on, trail_low, trail_days = False, None, 0

    def value_at(date: pd.Timestamp, field: str = "close") -> float:
        d = days.get(date)
        total = cash
        if d is None:
            return total
        for code, qty in shares.items():
            if code in d.index and np.isfinite(d.at[code, field]):
                total += qty * float(d.at[code, field])
            elif code in close.columns and np.isfinite(close.at[date, code]):
                total += qty * float(close.at[date, code])
        return total

    def execute(date: pd.Timestamp, target: dict[str, float]) -> None:
        nonlocal cash, shares
        d = days.get(date)
        if d is None:
            return
        equity = value_at(date, "open")
        all_codes = set(shares) | set(target)
        # Sells first, buys second. Unfilled quantities remain in the account.
        for side in ("sell", "buy"):
            for code in sorted(all_codes):
                cur = shares.get(code, 0)
                if code not in d.index or not np.isfinite(d.at[code, "open"]) or d.at[code, "volume"] <= 0:
                    if (side == "sell" and cur) or (side == "buy" and target.get(code, 0) > 0):
                        stats.blocked_suspended += 1
                    continue
                op = float(d.at[code, "open"])
                hi, lo = float(d.at[code, "high"]), float(d.at[code, "low"])
                pct = float(d.at[code, "pct_chg"]) if np.isfinite(d.at[code, "pct_chg"]) else 0.0
                one_price = abs(hi - lo) < 1e-10
                if side == "buy" and one_price and pct >= 9.5:
                    stats.blocked_limit += 1; continue
                if side == "sell" and one_price and pct <= -9.5:
                    stats.blocked_limit += 1; continue
                tgt = int((equity * target.get(code, 0) / op) // LOT * LOT)
                desired = tgt - cur
                if (side == "sell" and desired >= 0) or (side == "buy" and desired <= 0):
                    continue
                max_qty = int((float(d.at[code, "volume"]) * VOLUME_CAP) // LOT * LOT)
                qty = min(abs(desired), max_qty)
                if qty < abs(desired):
                    stats.capacity_clipped += 1
                if qty < LOT:
                    continue
                px = op * (1 + SLIPPAGE if side == "buy" else 1 - SLIPPAGE)
                value = qty * px
                fee = max(MIN_COMMISSION, value * COMMISSION_RATE)
                if side == "buy":
                    affordable = int((cash / (px * (1 + COMMISSION_RATE))) // LOT * LOT)
                    qty = min(qty, affordable)
                    if qty < LOT: continue
                    value = qty * px; fee = max(MIN_COMMISSION, value * COMMISSION_RATE)
                    cash -= value + fee; shares[code] = cur + qty
                else:
                    qty = min(qty, cur); value = qty * px; fee = max(MIN_COMMISSION, value * COMMISSION_RATE)
                    cash += value - fee; shares[code] = cur - qty
                    if shares[code] == 0: shares.pop(code)
                stats.orders += 1; stats.turnover_value += value; stats.commission += fee
                stats.slippage_cost += qty * op * SLIPPAGE
                trades.append({"date": date, "symbol": code, "side": side, "qty": qty,
                               "open": op, "fill": px, "value": value, "commission": fee})

    def signal(date: pd.Timestamp) -> tuple[dict[str, float], str]:
        nonlocal current_candidates, current_vol
        if trail_on:
            return active_defense_basket(DEFENSE_BASKETS[p.defense_basket_name], close, date, p.defense_min_hist), "trail"
        bench = close[BENCHMARK].loc[:date].dropna()
        if len(bench) > p.regime_lookback and bench.iloc[-1] / bench.iloc[-p.regime_lookback - 1] - 1 < p.regime_threshold:
            return active_defense_basket(DEFENSE_BASKETS[p.defense_basket_name], close, date, p.defense_min_hist), "regime"
        hist_len = close[codes].loc[:date].notna().sum()
        universe = [c for c in codes if hist_len[c] >= p.min_hist_days and np.isfinite(close.at[date, c])]
        vol = annual_volatility(returns[universe], p.vol_window).loc[date].dropna()
        vol = vol[(vol >= p.vol_low) & (vol <= p.vol_high)]
        if len(vol) < p.n_corr:
            return {}, "insufficient"
        mc = mean_abs_correlation(returns, p.corr_window, date, list(vol.index))
        candidates = mc.nsmallest(p.n_corr).index.tolist()
        mom = momentum_score(close[codes], date, p.momentum_window, candidates).dropna().sort_values(ascending=False)
        picks = []
        for code in mom.index:
            if mom[code] <= 0: break
            if is_overheat(logbias.at[date, code], rsi.at[date, code], rsi_diff.at[date, code], CATEGORY[code], p):
                continue
            picks.append(code)
            if len(picks) == p.n_momentum: break
        current_candidates, current_vol = candidates, vol
        if not picks: return {}, "risk_on_empty"
        inv = 1 / vol.loc[picks]; target = (inv / inv.sum()).to_dict()
        target = apply_commodity_cap(target, candidates, CATEGORY, vol, p.max_commodity_weight)
        target = _vol_target_scale(target, close[codes], date, p.vol_target_window, p.vol_target)
        return target, "risk_on"

    for date in cal:
        if pending is not None:
            execute(date, pending); pending = None
        nav = value_at(date, "close")
        nav_rows.append({"date": date, "asset": nav, "cash": cash, "positions": len(shares)})
        hist_nav = pd.Series([r["asset"] for r in nav_rows])
        peak = float(hist_nav.max()); dd = nav / peak - 1
        if not trail_on and len(hist_nav) >= 20 and dd <= p.trailing_dd:
            trail_on, trail_low, trail_days = True, nav, 0
        elif trail_on:
            trail_days += 1; trail_low = min(float(trail_low), nav)
            if nav / trail_low - 1 >= p.trailing_recovery or trail_days >= p.trailing_max_days:
                trail_on = False
        if date in weekly:
            pending, kind = signal(date)
            decisions.append({"date": date, "kind": kind, "target": json.dumps(pending, ensure_ascii=False)})
        elif not trail_on and current_candidates and shares:
            hot = [c for c in shares if c in logbias.columns and
                   is_overheat(logbias.at[date, c], rsi.at[date, c], rsi_diff.at[date, c], CATEGORY[c], p)]
            if hot:
                mom = momentum_score(close[codes], date, p.momentum_window, current_candidates).dropna()
                keep = [c for c in shares if c not in hot]
                pool = [c for c in current_candidates if c not in keep and c in mom and mom[c] > 0 and
                        not is_overheat(logbias.at[date, c], rsi.at[date, c], rsi_diff.at[date, c], CATEGORY[c], p)]
                pool.sort(key=lambda c: logbias.at[date, c])
                names = (keep + pool)[:p.n_momentum]
                av = current_vol.reindex(names).dropna()
                if len(av):
                    inv = 1 / av; pending = (inv / inv.sum()).to_dict()

    nav_df = pd.DataFrame(nav_rows).set_index("date")
    summary = metric(nav_df.asset)
    years = (nav_df.index[-1] - nav_df.index[0]).days / 365.25
    summary.update({"initial_cash": INITIAL_CASH, "commission_rate": COMMISSION_RATE,
                    "min_commission": MIN_COMMISSION, "slippage": SLIPPAGE,
                    "volume_cap": VOLUME_CAP, "lot": LOT, "annual_turnover": stats.turnover_value / INITIAL_CASH / years,
                    **stats.__dict__})
    OUT.mkdir(parents=True, exist_ok=True)
    nav_df.reset_index().to_csv(OUT / "daily_equity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(trades).to_csv(OUT / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(decisions).to_csv(OUT / "decisions.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
