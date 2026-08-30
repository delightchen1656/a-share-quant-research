from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT.parent
ARCHIVE = PROJECT / "inputs" / "supermind_exports" / "run123_20260822"
OUT = PROJECT / "outputs" / "run123_analysis"


def read_positions(run: int):
    raw = pd.read_csv(ARCHIVE / f"dailyposition{run}", encoding="utf-8-sig")
    raw.columns = [str(x).strip() for x in raw.columns]
    raw["date"] = pd.to_datetime(raw["日期"], errors="coerce").ffill()
    nav = raw[raw["日期"].notna()][["date", "总资产", "现金"]].copy()
    nav.columns = ["date", "asset", "cash"]
    nav = nav.sort_values("date").drop_duplicates("date", keep="last")
    holdings = raw[raw["证券"].notna()].copy()
    holdings["symbol"] = holdings["证券"].str.extract(r"\((\d{6}\.(?:SH|SZ|BJ))\)")
    holdings["name"] = holdings["证券"].str.replace(r"\([^)]*\)", "", regex=True)
    holdings = holdings[["date", "symbol", "name", "数量", "持仓", "收盘价", "收益"]]
    holdings.columns = ["date", "symbol", "name", "quantity", "value", "close", "unrealized"]
    return nav, holdings


def read_trades(run: int):
    trades = pd.read_csv(ARCHIVE / f"detal{run}", encoding="utf-8-sig").drop_duplicates()
    trades["date"] = pd.to_datetime(trades["日期"])
    trades["symbol"] = trades["代码"].astype(str)
    return trades.sort_values(["date", "时间"])


def drawdown_metrics(nav: pd.DataFrame):
    x = nav.copy()
    x["peak"] = x.asset.cummax()
    x["drawdown"] = x.asset / x.peak - 1
    trough = x.loc[x.drawdown.idxmin()]
    peak = x[x.date <= trough.date].loc[x[x.date <= trough.date].asset.idxmax()]
    return {
        "start": str(x.date.iloc[0].date()), "end": str(x.date.iloc[-1].date()),
        "start_asset": float(x.asset.iloc[0]), "end_asset": float(x.asset.iloc[-1]),
        "total_return": float(x.asset.iloc[-1] / x.asset.iloc[0] - 1),
        "max_drawdown": float(trough.drawdown),
        "peak_date": str(peak.date.date()), "peak_asset": float(peak.asset),
        "trough_date": str(trough.date.date()), "trough_asset": float(trough.asset),
    }


def july_attribution(nav, holdings, trades):
    start = pd.Timestamp("2026-06-30")
    end = pd.Timestamp("2026-07-31")
    n = nav[(nav.date >= start) & (nav.date <= end)].copy()
    h = holdings[(holdings.date >= start) & (holdings.date <= end)].copy()
    t = trades[(trades.date > start) & (trades.date <= end)].copy()
    pivot = h.pivot_table(index="date", columns="symbol", values="value", aggfunc="sum").fillna(0)
    pivot = pivot.reindex(n.date).fillna(0)
    tx = t.pivot_table(index="date", columns="symbol", values="金额", aggfunc="sum").fillna(0)
    tx = tx.reindex(index=pivot.index, columns=pivot.columns, fill_value=0)
    # Security P&L = end value - prior value - signed transaction cash into security.
    pnl = pivot.diff().iloc[1:] - tx.iloc[1:]
    contribution = pnl.sum().sort_values()
    names = h.drop_duplicates("symbol").set_index("symbol")["name"].to_dict()
    worst = [{"symbol": s, "name": names.get(s, ""), "pnl": float(v)} for s, v in contribution.head(15).items()]
    best = [{"symbol": s, "name": names.get(s, ""), "pnl": float(v)} for s, v in contribution.tail(10).sort_values(ascending=False).items()]
    if len(n):
        peak_row = n.loc[n.asset.idxmax()]
        final_row = n.iloc[-1]
        period_return = final_row.asset / n.iloc[0].asset - 1
        peak_to_end = final_row.asset / peak_row.asset - 1
    else:
        peak_row = final_row = None
        period_return = peak_to_end = np.nan
    return {
        "period_start_asset": float(n.iloc[0].asset), "period_end_asset": float(n.iloc[-1].asset),
        "period_return": float(period_return), "july_peak_date": str(peak_row.date.date()),
        "july_peak_asset": float(peak_row.asset), "peak_to_end": float(peak_to_end),
        "trade_rows": int(len(t)), "buy_amount": float(t.loc[t["操作"].eq("买入"), "金额"].sum()),
        "sell_amount_abs": float(-t.loc[t["操作"].eq("卖出"), "金额"].sum()),
        "fees_and_tax": float(t["佣金"].sum() + t["印花税"].sum()),
        "worst_security_contributions": worst, "best_security_contributions": best,
    }


def market_july():
    index = pd.read_parquet(PROJECT / "data" / "benchmark" / "000688.SH.parquet")
    index["date"] = pd.to_datetime(index.date)
    idx = index[index.date.between("2026-06-30", "2026-07-31")].sort_values("date")
    star_files = list((PROJECT / "data" / "classified" / "SH" / "star" / "raw").glob("*.parquet"))
    rows = []
    for f in star_files:
        x = pd.read_parquet(f, columns=["date", "symbol", "close", "tradestatus"])
        x["date"] = pd.to_datetime(x.date)
        x = x[x.date.between("2026-06-30", "2026-07-31")].sort_values("date")
        if len(x) >= 2:
            rows.append((x.symbol.iloc[-1], x.close.iloc[-1] / x.close.iloc[0] - 1))
    ret = pd.Series(dict(rows), dtype=float)
    return {
        "star50_return": float(idx.close.iloc[-1] / idx.close.iloc[0] - 1),
        "star_equal_weight_return": float(ret.mean()), "star_median_return": float(ret.median()),
        "positive_share": float((ret > 0).mean()), "stock_count": int(len(ret)),
        "best_decile_mean": float(ret.nlargest(max(1, len(ret)//10)).mean()),
        "worst_decile_mean": float(ret.nsmallest(max(1, len(ret)//10)).mean()),
    }


def log_counts(run: int):
    text = (ARCHIVE / f"outlog{run}").read_text(encoding="utf-8-sig", errors="replace")
    return {key: len(re.findall(pattern, text)) for key, pattern in {
        "candidates": r"STAR candidates", "audits": r"EXECUTION_AUDIT",
        "filled": r"filled (?:BUY|STOP|TPALL|TPHALF|TIME)", "errors": r"ERROR|Traceback",
    }.items()}


def main():
    result = {"runs": {}, "market_2026_07": market_july()}
    for run in (1, 2, 3):
        nav, holdings = read_positions(run)
        trades = read_trades(run)
        item = {"nav": drawdown_metrics(nav), "trade_rows": int(len(trades)), "log": log_counts(run)}
        if run == 3:
            item["july_2026"] = july_attribution(nav, holdings, trades)
        result["runs"][str(run)] = item
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
