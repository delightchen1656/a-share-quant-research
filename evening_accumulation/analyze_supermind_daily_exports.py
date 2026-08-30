from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "inputs" / "supermind_exports"
OUTPUT = ROOT / "outputs" / "supermind_daily_parity"


def normalize_positions() -> dict:
    source = ARCHIVE / "supermind_daily_100k_20200101_20260630_positions.csv"
    raw = pd.read_csv(source, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]

    nav_rows = raw[raw["日期"].notna()].copy()
    nav_rows["日期"] = pd.to_datetime(nav_rows["日期"])
    nav = nav_rows[["日期", "总资产", "现金"]].rename(
        columns={"日期": "date", "总资产": "total_asset", "现金": "cash"}
    ).sort_values("date").reset_index(drop=True)
    nav.to_csv(OUTPUT / "supermind_daily_nav.csv", index=False, encoding="utf-8-sig")

    raw["date"] = pd.to_datetime(raw["日期"], errors="coerce").ffill()
    holdings = raw[raw["证券"].notna()].copy()
    holdings = holdings[["date", "证券", "数量", "持仓", "收盘价", "收益"]].rename(
        columns={"证券": "symbol", "数量": "quantity", "持仓": "market_value",
                 "收盘价": "close", "收益": "pnl"}
    ).sort_values(["date", "symbol"]).reset_index(drop=True)
    holdings.to_csv(OUTPUT / "supermind_daily_holdings.csv", index=False, encoding="utf-8-sig")

    first = float(nav.iloc[0].total_asset)
    last = float(nav.iloc[-1].total_asset)
    years = (nav.iloc[-1].date - nav.iloc[0].date).days / 365.2425
    return {
        "nav_days": int(len(nav)),
        "holding_rows": int(len(holdings)),
        "first_date": str(nav.iloc[0].date.date()),
        "last_date": str(nav.iloc[-1].date.date()),
        "first_asset": first,
        "last_asset": last,
        "total_return": last / first - 1.0,
        "annualized_return": (last / first) ** (1.0 / years) - 1.0,
    }


def compare_fills() -> dict:
    platform = pd.read_csv(
        ARCHIVE / "supermind_daily_100k_20200101_20260630_trades.csv",
        encoding="utf-8-sig",
    ).drop_duplicates()
    local = pd.read_csv(OUTPUT / "fills.csv", encoding="utf-8-sig")

    platform = platform.rename(columns={
        "日期": "date", "代码": "symbol", "操作": "side",
        "成交价": "price", "数量": "quantity",
    })
    platform["date"] = pd.to_datetime(platform["date"]).dt.strftime("%Y-%m-%d")
    platform["symbol"] = platform["symbol"].astype(str).str.strip()
    platform["side"] = platform["side"].map({"买入": "BUY", "卖出": "SELL"})
    local["date"] = pd.to_datetime(local["date"]).dt.strftime("%Y-%m-%d")
    local["side"] = local["side"].replace({"TPHALF": "SELL", "TPALL": "SELL", "STOP": "SELL", "TIME": "SELL"})

    keys = ["date", "symbol", "side"]
    pkeys = platform[keys].value_counts().rename("platform_count")
    lkeys = local[keys].value_counts().rename("local_count")
    counts = pd.concat([pkeys, lkeys], axis=1).fillna(0)
    matched = counts[["platform_count", "local_count"]].min(axis=1).sum()

    platform["occurrence"] = platform.groupby(keys).cumcount()
    local["occurrence"] = local.groupby(keys).cumcount()
    merged = platform.merge(local, on=keys + ["occurrence"], suffixes=("_platform", "_local"))
    price_error = (merged["price_platform"] - merged["price_local"]).abs()
    metrics = {
        "platform_unique_fills": int(len(platform)),
        "local_fills": int(len(local)),
        "matched_date_symbol_side": int(matched),
        "platform_recall": float(matched / len(platform)),
        "local_precision": float(matched / len(local)),
        "cross_join_price_mae": float(price_error.mean()) if len(merged) else None,
        "cross_join_price_max_error": float(price_error.max()) if len(merged) else None,
    }
    (OUTPUT / "match_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


if __name__ == "__main__":
    result = {"platform_account": normalize_positions(), "fill_match": compare_fills()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
