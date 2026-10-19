from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402


ROOT = core.ROOT
PROJECT = core.PROJECT
RAW_ROOT = ROOT / "sh_sz_market_research" / "data_pipeline" / "data" / "raw"
RESULTS = PROJECT / "results" / "batch_002"
AUDIT = RESULTS / "audit"
ACTIONS_BASE = ROOT / "strategies" / "hushen" / "backtest" / "data" / "actions_merged.json"
ACTIONS_DOWNLOADED = AUDIT / "action_responses"
EASTMONEY_ACTIONS = AUDIT / "eastmoney_actions.json"
METADATA = ROOT / "sh_sz_market_research" / "data_pipeline" / "data" / "metadata" / "historical_mainboard_universe.csv"


def number(value) -> float:
    text = str(value).strip()
    return float(text) if text else 0.0


def load_raw_bars(symbols: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], pd.DataFrame]:
    core.CACHE.mkdir(parents=True, exist_ok=True)
    cache = core.CACHE / "raw_execution_bars_batch002_pre2025.parquet"
    rebuild = True
    if cache.exists():
        all_bars = pd.read_parquet(cache)
        all_bars["date"] = pd.to_datetime(all_bars["date"])
        rebuild = not symbols.issubset(set(all_bars.symbol.astype(str).unique()))
    if rebuild:
        rows = []
        columns = ["date", "open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus", "symbol"]
        for i, symbol in enumerate(sorted(symbols), 1):
            path = RAW_ROOT / symbol[-2:] / f"{symbol}.parquet"
            if not path.exists():
                raise FileNotFoundError(path)
            d = pd.read_parquet(path, columns=columns)
            d["date"] = pd.to_datetime(d["date"])
            d = d[d.date.between(core.EVAL_START, core.HARD_MAX_DATE)].copy()
            for col in ["open", "high", "low", "close", "preclose", "volume", "amount"]:
                d[col] = pd.to_numeric(d[col], errors="coerce")
            rows.append(d)
            if i % 500 == 0:
                print(f"raw audit files {i}/{len(symbols)}", flush=True)
        all_bars = pd.concat(rows, ignore_index=True).sort_values(["symbol", "date"])
        all_bars.to_parquet(cache, index=False)
    if all_bars.date.max() > core.HARD_MAX_DATE:
        raise RuntimeError("Raw audit data crossed 2024 boundary")
    by_symbol = {s: d.set_index("date").sort_index() for s, d in all_bars.groupby("symbol", sort=False)}
    calendar = sorted(all_bars.date.drop_duplicates().tolist())
    return by_symbol, calendar, all_bars


def load_actions() -> tuple[dict[tuple[pd.Timestamp, str], list[dict]], set[str]]:
    keyed = json.loads(ACTIONS_BASE.read_text(encoding="utf-8"))
    if EASTMONEY_ACTIONS.exists():
        supplement = json.loads(EASTMONEY_ACTIONS.read_text(encoding="utf-8"))
        keyed.update(supplement["records"])
    if ACTIONS_DOWNLOADED.exists():
        for path in ACTIONS_DOWNLOADED.glob("*.json"):
            if path.name.startswith(("manifest", "query_")):
                continue
            obj = json.loads(path.read_text(encoding="utf-8"))
            if "key" in obj and "records" in obj:
                keyed[obj["key"]] = obj["records"]
    events: dict[tuple[pd.Timestamp, str], list[dict]] = defaultdict(list)
    for key, records in keyed.items():
        symbol = key.split("/")[0]
        for row in records:
            if not row.get("dividOperateDate"):
                continue
            date = pd.Timestamp(row["dividOperateDate"]).normalize()
            if date > core.HARD_MAX_DATE:
                continue
            events[(date, symbol)].append({
                "cash": number(row.get("dividCashPsBeforeTax", 0)),
                "stock": number(row.get("dividStocksPs", 0)) + number(row.get("dividReserveToStockPs", 0)),
                "taxable_stock": number(row.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(row.get("dividPayDate") or row["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(row.get("dividStockMarketDate") or row["dividOperateDate"]).normalize(),
                "source": row.get("source", "baostock_cache"),
            })
    return dict(events), set(keyed)


def load_delistings() -> dict[str, pd.Timestamp]:
    d = pd.read_csv(METADATA, dtype=str)
    d["outDate"] = pd.to_datetime(d.outDate, errors="coerce")
    d = d[d.outDate.notna() & (d.outDate <= core.HARD_MAX_DATE)]
    return dict(zip(d.symbol.astype(str), d.outDate))


def main() -> int:
    AUDIT.mkdir(parents=True, exist_ok=True)
    selection = json.loads((RESULTS / "SELECTION.json").read_text(encoding="utf-8"))
    champion = selection["champion"]
    grid = pd.read_csv(RESULTS / "grid.csv")
    eligible7 = grid[(grid["hold_calendar_days"] == 7) & (grid["eligible"].astype(str).str.lower() == "true")]
    if eligible7.empty:
        raise RuntimeError("No eligible seven-calendar-day candidate")
    best7 = eligible7.iloc[0].to_dict()
    candidates = [("overall_30day", champion), ("best_7day", best7)]
    signals = pd.read_parquet(RESULTS / "signals_all_scores.parquet")
    signals["date"] = pd.to_datetime(signals.date)
    selected_factors = {c["factor"] for _, c in candidates}
    signals = signals[signals.factor.isin(selected_factors)].copy()
    by_symbol, calendar, raw = load_raw_bars(set(signals.symbol.astype(str)))
    raw_close = raw[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    signals = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if signals.raw_close.isna().any():
        raise RuntimeError("Missing raw signal-date close")
    signals = signals.rename(columns={"raw_close": "close"})
    actions, known_keys = load_actions()
    missing: set[str] = set()
    audited = {}
    trade_outputs = {}
    delistings = load_delistings()
    for label, candidate in candidates:
        row, trades = core.simulate(
            signals,
            by_symbol,
            calendar,
            candidate["factor"],
            float(candidate["entry_offset_atr"]),
            int(candidate["hold_calendar_days"]),
            candidate["exit_set"],
            float(candidate["take_atr"]),
            float(candidate["stop_atr"]),
            keep_trades=True,
            actions=actions,
            known_action_keys=known_keys,
            coverage_sink=missing,
            delist_dates=delistings,
        )
        audited[label] = row
        trade_outputs[label] = trades
    if missing:
        gaps = [[key.split("/")[0], int(key.split("/")[1])] for key in sorted(missing)]
        (AUDIT / "action_gaps.json").write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "action_data_required", "gap_count": len(gaps), "gap_file": str(AUDIT / "action_gaps.json")}, ensure_ascii=False))
        return 2
    for label, row in audited.items():
        row["eligible_trade_count"] = all(row[f"trades_{y}"] >= 20 for y in core.YEARS)
        row["eligible_cross_year"] = row["profitable_years"] >= 3
        row["audit_passed"] = bool(row["eligible_trade_count"] and row["eligible_cross_year"] and row["open_positions_at_end"] == 0)
        trade_outputs[label].to_csv(AUDIT / f"trades_{label}_raw_action_audited.csv", index=False, encoding="utf-8-sig")
    output = {
        "status": "complete",
        "selected_overall_candidate": champion["candidate"],
        "separate_horizon_audits": audited,
        "known_action_stock_years": len(known_keys),
        "source_hashes": {
            "audit_champion.py": core.sha256(Path(__file__)),
            "run_batch.py": core.sha256(HERE / "run_batch.py"),
            "run_batch_002.py": core.sha256(HERE / "run_batch_002.py"),
            "PROTOCOL.json": core.sha256(PROJECT / "protocol" / "PROTOCOL.json"),
            "BATCH_002.json": core.sha256(PROJECT / "protocol" / "BATCH_002.json"),
            "eastmoney_actions.json": core.sha256(EASTMONEY_ACTIONS),
        },
        "post_2024_access": False,
        "notes": [
            "Raw unadjusted OHLC drives fills and exits.",
            "Cash dividends, bonus shares and transfer shares are applied from stock-year responses. Existing Baostock caches preserve payment/release dates; Eastmoney gap fills use ex-right date for both because that endpoint omits separate dates.",
            "The authorized 2% daily-volume full-fill approximation remains in force; no candidate hit that capacity limit.",
            "Historical level-2 order-book depth is unavailable.",
        ],
    }
    (AUDIT / "FINAL_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
