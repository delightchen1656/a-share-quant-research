from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evening_accumulation" / "data"
QFQ_DIR = DATA / "classified" / "SH" / "star" / "qfq"
RAW_DIR = DATA / "classified" / "SH" / "star" / "raw"
BENCHMARK = DATA / "benchmark" / "000688.SH.parquet"
OUT = Path(__file__).resolve().parent / "outputs"


@dataclass
class Position:
    shares: int
    entry_date: pd.Timestamp


def load_panel(folder: Path, field: str, end: str) -> pd.DataFrame:
    series = {}
    for path in folder.glob("688*.SH.parquet"):
        df = pd.read_parquet(path, columns=["date", field])
        df["date"] = pd.to_datetime(df["date"])
        df = df[df.date <= end].drop_duplicates("date", keep="last")
        series[path.stem] = df.set_index("date")[field]
    return pd.DataFrame(series).sort_index()


def load_raw(end: str) -> dict[str, pd.DataFrame]:
    result = {}
    cols = ["date", "open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus"]
    for path in RAW_DIR.glob("688*.SH.parquet"):
        df = pd.read_parquet(path, columns=cols)
        df["date"] = pd.to_datetime(df["date"])
        result[path.stem] = df[df.date <= end].drop_duplicates("date", keep="last").set_index("date").sort_index()
    return result


def commission(value: float) -> float:
    return max(5.0, value * 0.0003) + value * 0.00001


def stamp_tax(date: pd.Timestamp, value: float) -> float:
    return value * (0.0005 if date >= pd.Timestamp("2023-08-28") else 0.001)


def sellable(row: pd.Series) -> bool:
    if float(row.get("tradestatus", 0)) != 1 or float(row.open) <= 0:
        return False
    # Daily approximation: a one-price limit-down session cannot be sold.
    return not (float(row.high) == float(row.low) and float(row.open) < float(row.preclose))


def buyable(row: pd.Series) -> bool:
    if float(row.get("tradestatus", 0)) != 1 or float(row.open) <= 0:
        return False
    return not (float(row.high) == float(row.low) and float(row.open) > float(row.preclose))


def cluster_universe(returns: pd.DataFrame, eligible: list[str], n_groups: int) -> pd.Series:
    sample = returns[eligible].tail(252)
    good = sample.notna().sum() >= 160
    names = list(good[good].index)
    if len(names) < n_groups:
        return pd.Series(dtype=int)
    corr = sample[names].corr(min_periods=80).fillna(0).clip(-1, 1)
    dist = np.sqrt(np.maximum(0, (1 - corr.values) / 2))
    np.fill_diagonal(dist, 0)
    labels = fcluster(linkage(squareform(dist, checks=False), method="average"), n_groups, criterion="maxclust")
    return pd.Series(labels, index=names, dtype=int)


def group_signal(prices: pd.DataFrame, returns: pd.DataFrame, members: list[str], date: pd.Timestamp) -> dict | None:
    hist = prices.loc[:date, members].tail(520)
    rets = returns.loc[hist.index, members]
    # Reconstruct an equal-weight daily-rebalanced total-return index for current members.
    idx = (1 + rets.mean(axis=1, skipna=True).fillna(0)).cumprod()
    if len(idx) < 240:
        return None
    last = idx.iloc[-1]
    lo, hi = idx.min(), idx.max()
    percentile = 0.5 if hi <= lo else float((last - lo) / (hi - lo))
    mom60 = float(last / idx.iloc[-61] - 1) if len(idx) > 60 else np.nan
    ma120 = float(idx.tail(120).mean())
    breadth = float((hist.iloc[-1] > hist.tail(120).mean()).mean())
    score = (1 - percentile) * 0.45 + np.clip(mom60, -0.2, 0.3) * 1.2 + breadth * 0.35
    enter = percentile <= 0.60 and mom60 > 0 and last > ma120 and breadth >= 0.45
    exit_ = (percentile >= 0.85 and mom60 < 0.03) or last < ma120 * 0.97
    return {"percentile": percentile, "mom60": mom60, "breadth": breadth, "score": float(score), "enter": enter, "exit": exit_}


def pick_stocks(prices: pd.DataFrame, amount: pd.DataFrame, members: list[str], date: pd.Timestamp, count: int) -> list[str]:
    p = prices.loc[:date, members]
    a = amount.loc[:date, members]
    rows = []
    for s in members:
        x = p[s].dropna()
        if len(x) < 120 or pd.isna(a[s].tail(20).mean()) or a[s].tail(20).mean() < 50_000_000:
            continue
        r = x.pct_change().tail(120)
        mom = x.iloc[-1] / x.iloc[-61] - 1
        vol = r.std() * math.sqrt(252)
        liq = math.log(max(float(a[s].tail(20).mean()), 1))
        rows.append((s, mom - 0.35 * vol + 0.015 * liq))
    return [s for s, _ in sorted(rows, key=lambda z: z[1], reverse=True)[:count]]


def run(start: str, end: str, cash0: float, groups: int, selected_groups: int, stocks_per_group: int) -> dict:
    prices = load_panel(QFQ_DIR, "close", end)
    amount = load_panel(QFQ_DIR, "amount", end)
    returns = prices.pct_change(fill_method=None)
    raw = load_raw(end)
    dates = prices.index[(prices.index >= start) & (prices.index <= end)]
    rebalance_dates = set(pd.Series(dates, index=dates).groupby(dates.to_period("M")).first())
    cash = cash0
    positions: dict[str, Position] = {}
    pending_targets: list[str] | None = None
    equity_rows, trades, group_rows = [], [], []
    current_labels = pd.Series(dtype=int)
    previous_raw_close: dict[str, float] = {}

    for date in dates:
        # Infer common bonus-share/cash-dividend events from BaoStock raw
        # preclose, matching the project's frozen local execution baseline.
        for symbol, pos in list(positions.items()):
            if symbol not in raw or date not in raw[symbol].index or symbol not in previous_raw_close:
                continue
            row = raw[symbol].loc[date]
            preclose = float(row.preclose)
            factor = previous_raw_close[symbol] / preclose if preclose > 0 else 1.0
            if abs(factor - 1.0) > 0.02:
                share_factor = round(factor, 1)
                if share_factor >= 1.1:
                    old_shares = pos.shares
                    cash_dividend = max(0.0, previous_raw_close[symbol] - preclose * share_factor)
                    cash += old_shares * cash_dividend
                    pos.shares = int(round(old_shares * share_factor))
        # Execute previous close's target at today's open: sell first, then equal-weight buys.
        if pending_targets is not None:
            target = set(pending_targets)
            for symbol in list(positions):
                if symbol in target or date <= positions[symbol].entry_date:
                    continue
                row = raw[symbol].loc[date] if date in raw[symbol].index else None
                if row is None or not sellable(row):
                    continue
                px = min(max(float(row.open) * 0.999, float(row.low)), float(row.high))
                value = positions[symbol].shares * px
                fees = commission(value) + stamp_tax(date, value)
                cash += value - fees
                trades.append([date, symbol, "SELL", positions[symbol].shares, px, fees, "rebalance"])
                del positions[symbol]
            nav_open = cash + sum(
                p.shares * float(raw[s].loc[date, "open"])
                for s, p in positions.items() if date in raw[s].index
            )
            target_value = nav_open / max(len(target), 1)
            for symbol in pending_targets:
                if symbol in positions or symbol not in raw or date not in raw[symbol].index:
                    continue
                row = raw[symbol].loc[date]
                if not buyable(row):
                    continue
                px = min(max(float(row.open) * 1.001, float(row.low)), float(row.high))
                max_by_volume = int(float(row.volume) * 0.25)
                shares = min(int(target_value / px), max_by_volume)
                if shares < 200:
                    continue
                # STAR: after the first 200 shares, increments of one share are allowed.
                while shares >= 200 and shares * px + commission(shares * px) > cash:
                    shares -= 1
                if shares < 200:
                    continue
                value = shares * px
                fees = commission(value)
                cash -= value + fees
                positions[symbol] = Position(shares, date)
                trades.append([date, symbol, "BUY", shares, px, fees, "monthly_signal"])
            pending_targets = None

        if date in rebalance_dates and prices.index.get_loc(date) >= 260:
            hist_amount = amount.loc[:date].tail(20).mean()
            listing_days = prices.loc[:date].notna().sum()
            eligible = list(hist_amount[(hist_amount >= 50_000_000) & (listing_days >= 120)].index)
            current_labels = cluster_universe(returns.loc[:date], eligible, groups)
            candidates = []
            for label in sorted(current_labels.unique()):
                members = list(current_labels[current_labels == label].index)
                # Outlier singletons are correlation artifacts rather than
                # investable industry baskets.
                if len(members) < 5:
                    continue
                sig = group_signal(prices, returns, members, date)
                if sig:
                    group_rows.append([date, int(label), len(members), *[sig[k] for k in ["percentile", "mom60", "breadth", "score", "enter", "exit"]]])
                    if sig["enter"] and not sig["exit"]:
                        candidates.append((label, sig["score"], members))
            candidates.sort(key=lambda x: x[1], reverse=True)
            chosen = candidates[:selected_groups]
            pending_targets = []
            for _, _, members in chosen:
                pending_targets.extend(pick_stocks(prices, amount, members, date, stocks_per_group))

        nav = cash
        for symbol, pos in positions.items():
            if date in raw[symbol].index:
                nav += pos.shares * float(raw[symbol].loc[date, "close"])
        equity_rows.append([date, nav, cash, len(positions)])
        for symbol, frame in raw.items():
            if date in frame.index:
                previous_raw_close[symbol] = float(frame.loc[date, "close"])

    OUT.mkdir(parents=True, exist_ok=True)
    equity = pd.DataFrame(equity_rows, columns=["date", "equity", "cash", "positions"]).set_index("date")
    trades_df = pd.DataFrame(trades, columns=["date", "symbol", "side", "shares", "price", "fees", "reason"])
    group_df = pd.DataFrame(group_rows, columns=["date", "group", "members", "percentile", "mom60", "breadth", "score", "enter", "exit"])
    equity.to_csv(OUT / "equity.csv")
    trades_df.to_csv(OUT / "trades.csv", index=False)
    group_df.to_csv(OUT / "group_signals.csv", index=False)
    rets = equity.equity.pct_change().fillna(0)
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    total = equity.equity.iloc[-1] / cash0 - 1
    cagr = (equity.equity.iloc[-1] / cash0) ** (1 / years) - 1
    dd = equity.equity / equity.equity.cummax() - 1
    sharpe = float(rets.mean() / rets.std() * math.sqrt(252)) if rets.std() else 0
    # Full-period, point-in-time investable STAR equal-weight benchmark. The
    # local STAR 50 file currently begins only in 2025 and is kept separately.
    listed_days = prices.notna().cumsum()
    liquid = amount.rolling(20, min_periods=20).mean() >= 50_000_000
    bench_ret = returns.where((listed_days >= 120) & liquid).mean(axis=1).fillna(0)
    bench_curve = (1 + bench_ret.loc[equity.index]).cumprod()
    official = pd.read_parquet(BENCHMARK)
    official["date"] = pd.to_datetime(official["date"])
    official = official.set_index("date").loc[:equity.index[-1], "close"].dropna()
    result = {
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
        "initial_cash": cash0, "final_equity": float(equity.equity.iloc[-1]),
        "total_return": float(total), "cagr": float(cagr), "max_drawdown": float(dd.min()),
        "sharpe": sharpe, "trade_rows": len(trades_df), "buy_count": int((trades_df.side == "BUY").sum()) if len(trades_df) else 0,
        "star_equal_weight_total_return": float(bench_curve.iloc[-1] - 1),
        "star_equal_weight_max_drawdown": float((bench_curve / bench_curve.cummax() - 1).min()),
        "official_star50_available_start": str(official.index[0].date()),
        "official_star50_available_return": float(official.iloc[-1] / official.iloc[0] - 1),
        "parameters": {"groups": groups, "selected_groups": selected_groups, "stocks_per_group": stocks_per_group},
    }
    (OUT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2020-01-01")
    p.add_argument("--end", default="2026-07-31")
    p.add_argument("--cash", type=float, default=1_000_000)
    p.add_argument("--groups", type=int, default=12)
    p.add_argument("--selected-groups", type=int, default=3)
    p.add_argument("--stocks-per-group", type=int, default=3)
    args = p.parse_args()
    print(json.dumps(run(args.start, args.end, args.cash, args.groups, args.selected_groups, args.stocks_per_group), ensure_ascii=False, indent=2))
