from __future__ import annotations

import json
import math
import re
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
RAW = Path(__file__).resolve().parent / "raw_exports"
OUT = Path(__file__).resolve().parent / "outputs"
OUT.mkdir(parents=True, exist_ok=True)
SOURCES = {
    "baseline1-2": {"positions": RAW / "dailyposition1-2", "trades": RAW / "detal1-2", "log": RAW / "outlog1-2"},
    "baseline2-2": {"positions": RAW / "dailyposition2-2", "trades": RAW / "detal2-2", "log": RAW / "outlog2-2"},
}
NAMES = {"baseline1-2": "基准1-2止损过滤", "baseline2-2": "基准2-2升温防守"}


def load_assets(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    rows = frame[pd.to_datetime(frame["日期"], errors="coerce").notna() & pd.to_numeric(frame["总资产"], errors="coerce").notna()].copy()
    rows["date"] = pd.to_datetime(rows["日期"])
    rows["asset"] = pd.to_numeric(rows["总资产"])
    rows = rows[["date", "asset"]].drop_duplicates("date", keep="first").sort_values("date")
    rows["return"] = rows["asset"].pct_change().fillna(0.0)
    return rows.reset_index(drop=True)


def load_trades(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["日期"])
    for column in ["成交价", "数量", "金额", "佣金", "印花税"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame = frame.sort_values(["date", "时间"], kind="stable").reset_index(drop=True)
    return frame


def performance(returns: pd.Series) -> dict:
    returns = returns.fillna(0.0).astype(float)
    nav = (1.0 + returns).cumprod()
    years = max(len(returns) / 252.0, 1 / 252.0)
    cagr = float(nav.iloc[-1] ** (1 / years) - 1)
    dd = nav / nav.cummax() - 1.0
    mdd = float(dd.min())
    vol = float(returns.std(ddof=1) * np.sqrt(252))
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else np.nan
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    return {"final_multiple": float(nav.iloc[-1]), "cagr": cagr, "max_drawdown": mdd, "volatility": vol, "sharpe": sharpe, "calmar": calmar}


def drawdown_episodes(asset: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    values = asset.set_index("date")["asset"]
    peak_value = float(values.iloc[0]); peak_date = values.index[0]
    in_drawdown = False; trough_value = peak_value; trough_date = peak_date
    episodes = []
    for date, value in values.iloc[1:].items():
        value = float(value)
        if value >= peak_value:
            if in_drawdown:
                episodes.append({"peak_date": peak_date, "trough_date": trough_date, "recovery_date": date,
                                 "drawdown": trough_value / peak_value - 1.0, "recovered": True})
            peak_value = value; peak_date = date; in_drawdown = False; trough_value = value; trough_date = date
        else:
            in_drawdown = True
            if value < trough_value:
                trough_value = value; trough_date = date
    if in_drawdown:
        episodes.append({"peak_date": peak_date, "trough_date": trough_date, "recovery_date": pd.NaT,
                         "drawdown": trough_value / peak_value - 1.0, "recovered": False})
    result = pd.DataFrame(episodes).sort_values("drawdown").head(top_n).copy()
    if len(result):
        result["drawdown_days"] = (result["trough_date"] - result["peak_date"]).dt.days
        result["recovery_days"] = (result["recovery_date"] - result["trough_date"]).dt.days
    return result.reset_index(drop=True)


def fifo_trade_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    lots: dict[str, deque] = {}
    completed = []
    for _, row in trades.iterrows():
        symbol = row["代码"]
        quantity = int(abs(row["数量"]))
        fees = float(row["佣金"] + row["印花税"])
        if row["操作"] == "买入":
            unit_cost = (float(row["金额"]) + fees) / quantity if quantity else 0.0
            lots.setdefault(symbol, deque()).append([quantity, unit_cost, row["date"]])
        else:
            remaining = quantity
            sale_unit = (abs(float(row["金额"])) - fees) / quantity if quantity else 0.0
            while remaining > 0 and lots.get(symbol):
                lot_qty, unit_cost, buy_date = lots[symbol][0]
                matched = min(remaining, lot_qty)
                completed.append({"symbol": symbol, "name": row["名称"], "buy_date": buy_date, "sell_date": row["date"],
                                  "quantity": matched, "buy_unit_cost": unit_cost, "sell_unit_net": sale_unit,
                                  "pnl": matched * (sale_unit - unit_cost), "return": sale_unit / unit_cost - 1 if unit_cost else np.nan})
                remaining -= matched; lot_qty -= matched
                if lot_qty == 0: lots[symbol].popleft()
                else: lots[symbol][0][0] = lot_qty
    return pd.DataFrame(completed)


def monthly_rebalanced(r1: pd.Series, r2: pd.Series, w1: float) -> pd.Series:
    result = []
    sleeve1, sleeve2 = w1, 1.0 - w1
    current_month = None
    for date in r1.index:
        month = date.to_period("M")
        if current_month is None or month != current_month:
            total = sleeve1 + sleeve2
            sleeve1, sleeve2 = total * w1, total * (1.0 - w1)
            current_month = month
        before = sleeve1 + sleeve2
        sleeve1 *= 1.0 + float(r1.loc[date]); sleeve2 *= 1.0 + float(r2.loc[date])
        after = sleeve1 + sleeve2
        result.append(after / before - 1.0)
    return pd.Series(result, index=r1.index)


def raw_bar(symbol: str, date: pd.Timestamp):
    path = ROOT / "evening_accumulation" / "data" / "raw" / f"{symbol}.parquet"
    if not path.exists(): return None
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["date"])
    match = frame[frame.date == date]
    return None if match.empty else match.iloc[0]


assets = {key: load_assets(item["positions"]) for key, item in SOURCES.items()}
trades = {key: load_trades(item["trades"]) for key, item in SOURCES.items()}
joined = assets["baseline1-2"].set_index("date")[["asset", "return"]].join(
    assets["baseline2-2"].set_index("date")[["asset", "return"]], how="inner", lsuffix="_1", rsuffix="_2")
correlation = float(joined["return_1"].corr(joined["return_2"]))

episodes = drawdown_episodes(assets["baseline1-2"])
asset2 = assets["baseline2-2"].set_index("date")["asset"]
for idx, row in episodes.iterrows():
    start = asset2.index[asset2.index.get_indexer([row.peak_date], method="nearest")][0]
    end = asset2.index[asset2.index.get_indexer([row.trough_date], method="nearest")][0]
    episodes.loc[idx, "baseline2_2_return_same_interval"] = float(asset2.loc[end] / asset2.loc[start] - 1.0)

concentration_rows = []
for key, frame in assets.items():
    series = frame.set_index("date")["return"]
    base = performance(series)
    sorted_returns = series.sort_values(ascending=False)
    no5 = series.copy(); no5.loc[sorted_returns.index[:5]] = 0.0
    no10 = series.copy(); no10.loc[sorted_returns.index[:10]] = 0.0
    completed = fifo_trade_pnl(trades[key])
    positive = completed[completed.pnl > 0].sort_values("pnl", ascending=False)
    concentration_rows.append({
        "baseline": key, "name": NAMES[key], "cagr_original": base["cagr"],
        "cagr_without_best_5_days": performance(no5)["cagr"], "cagr_without_best_10_days": performance(no10)["cagr"],
        "top10_winning_trades_pnl": float(positive.head(10).pnl.sum()), "all_winning_trades_pnl": float(positive.pnl.sum()),
        "top10_share_of_winning_pnl": float(positive.head(10).pnl.sum() / positive.pnl.sum()) if positive.pnl.sum() else np.nan,
        "net_realized_pnl": float(completed.pnl.sum()), "completed_fifo_lots": int(len(completed)),
    })
    completed.sort_values("pnl", ascending=False).head(20).to_csv(OUT / f"top_trades_{key}.csv", index=False, encoding="utf-8-sig")
concentration = pd.DataFrame(concentration_rows)

portfolio_rows = []
r1, r2 = joined.return_1, joined.return_2
for w1 in [0.3, 0.4, 0.5, 0.6, 0.7]:
    for frequency, returns in [("每日", w1 * r1 + (1 - w1) * r2), ("每月", monthly_rebalanced(r1, r2, w1))]:
        stats = performance(returns)
        annual = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
        nav = (1.0 + returns).cumprod(); dd = nav / nav.cummax() - 1.0
        underwater = dd < 0
        max_underwater = 0; current = 0
        for flag in underwater:
            current = current + 1 if flag else 0; max_underwater = max(max_underwater, current)
        portfolio_rows.append({"rebalance": frequency, "weight_baseline1_2": w1, "weight_baseline2_2": 1-w1,
                               **stats, "worst_calendar_year": float(annual.min()), "losing_years": int((annual < 0).sum()),
                               "max_underwater_trading_days": max_underwater})
portfolios = pd.DataFrame(portfolio_rows)

audit_rows = []
for key in SOURCES:
    asset = assets[key].set_index("date")
    window = asset.loc["2024-09-01":"2024-11-30"].copy()
    top_days = window.nlargest(10, "return").index
    relevant_dates = set(top_days) | set(pd.date_range("2024-09-24", "2024-10-15", freq="D"))
    subset = trades[key][trades[key].date.isin(relevant_dates)].copy()
    for _, row in subset.iterrows():
        bar = raw_bar(row["代码"], row["date"])
        item = {"baseline": key, "date": row["date"], "time": row["时间"], "symbol": row["代码"], "name": row["名称"],
                "action": row["操作"], "trade_price": row["成交价"], "quantity": abs(int(row["数量"])), "amount": abs(row["金额"]),
                "portfolio_daily_return": float(asset.loc[row["date"], "return"]) if row["date"] in asset.index else np.nan}
        if bar is not None:
            item.update({"raw_open": float(bar.open), "raw_high": float(bar.high), "raw_low": float(bar.low), "raw_close": float(bar.close),
                         "raw_preclose": float(bar.preclose), "raw_volume": float(bar.volume), "raw_pct_chg": float(bar.pctChg),
                         "trade_inside_raw_range": bool(float(bar.low) - 0.011 <= row["成交价"] <= float(bar.high) + 0.011),
                         "one_price_board": bool(float(bar.high) == float(bar.low)), "suspended": bool(str(bar.tradestatus) != "1" or float(bar.volume) <= 0)})
        audit_rows.append(item)
audit = pd.DataFrame(audit_rows).sort_values(["baseline", "date", "time"])

daily = joined.reset_index().rename(columns={"asset_1":"asset_baseline1_2", "return_1":"return_baseline1_2", "asset_2":"asset_baseline2_2", "return_2":"return_baseline2_2"})
daily.to_csv(OUT / "daily_returns_aligned.csv", index=False, encoding="utf-8-sig")
episodes.to_csv(OUT / "baseline1_2_top5_drawdowns.csv", index=False, encoding="utf-8-sig")
concentration.to_csv(OUT / "return_concentration.csv", index=False, encoding="utf-8-sig")
portfolios.to_csv(OUT / "portfolio_grid.csv", index=False, encoding="utf-8-sig")
audit.to_csv(OUT / "oct2024_trade_audit.csv", index=False, encoding="utf-8-sig")

summary = {
    "date_start": str(joined.index.min().date()), "date_end": str(joined.index.max().date()), "aligned_days": int(len(joined)),
    "daily_return_correlation": correlation,
    "asset_start_end": {key: {"start": float(frame.asset.iloc[0]), "end": float(frame.asset.iloc[-1]), **performance(frame["return"])} for key, frame in assets.items()},
    "best_portfolios_under_15pct_mdd": portfolios[portfolios.max_drawdown >= -0.15].sort_values("cagr", ascending=False).to_dict("records"),
    "audit_trade_count": int(len(audit)), "audit_outside_raw_range": int((audit.trade_inside_raw_range == False).sum()),
    "audit_one_price_buys": int(((audit.action == "买入") & (audit.one_price_board == True)).sum()),
    "audit_suspended_trades": int((audit.suspended == True).sum()),
}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
