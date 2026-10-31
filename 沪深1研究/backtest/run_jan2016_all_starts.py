"""Reconstruct Hushen1 for every January-2016 start through the latest audited day.

The registered platform entry starts its calendar in 2018.  This study extends the
same factor formula backwards using the separately audited 2013+ raw-price archive,
then switches to the registered frozen rankings at their first available date.
Production market files and strategy state are never modified.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import json
import sys

import numpy as np
import pandas as pd

import engine as e


HOME = Path(__file__).resolve().parents[1]
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
ARCHIVE = (ROOT / "沪深2研究/results/holdout_restricted/"
           "history_2015_extension/attempt_20261022_2119")
DATA = ARCHIVE / "staging"
PRODUCTION = ROOT / "K线数据/沪深"
TRACKING = HOME / "tracking"
TARGET = "2026-10-23"
OUT = HOME / "results/holdout_restricted/jan2016_all_starts_to_20261023"
RUNTIME = OUT / "runtime_inputs"
FACTORS = ["cap", "vol", "overnight", "intraday"]
WEIGHTS = [-0.35, -0.20, 0.25, -0.20]
FIELDS = e.FIELDS


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def trading_calendar() -> pd.DatetimeIndex:
    frame = pd.read_csv(ARCHIVE / "CALENDAR.csv")
    frame["calendar_date"] = pd.to_datetime(frame["calendar_date"])
    dates = pd.DatetimeIndex(frame.loc[frame.is_trading_day.astype(int).eq(1), "calendar_date"])
    current = pd.read_csv(PRODUCTION / "metadata/trade_calendar_20261023.csv")
    current["calendar_date"] = pd.to_datetime(current["calendar_date"])
    current_dates = current.loc[current.is_trading_day.astype(int).eq(1), "calendar_date"]
    dates = pd.DatetimeIndex(sorted(set(dates) | set(current_dates)))
    dates = dates[(dates >= "2013-01-01") & (dates <= TARGET)]
    assert dates[-1] == pd.Timestamp(TARGET)
    return dates


def universe() -> pd.DataFrame:
    result = pd.read_csv(ARCHIVE / "UNIVERSE.csv", dtype=str, keep_default_na=False)
    assert len(result) == 3414 and result.symbol.is_unique
    assert (result.board == "main").all()
    return result.set_index("symbol", drop=False)


def archive_raw(symbol: str) -> Path:
    return DATA / "raw" / symbol[-2:] / (symbol + ".parquet")


def production_raw(symbol: str) -> Path:
    return PRODUCTION / "raw" / symbol[-2:] / (symbol + ".parquet")


def verified_receipts() -> dict[str, dict[str, str]]:
    complete = read_json(ARCHIVE / "DOWNLOAD_COMPLETE.json")
    assert complete["status"] == "downloaded_not_replayed"
    assert complete["symbols"] == 3414 and complete["production_unchanged"] is True
    assert len(complete["receipts"]) == 3414
    return complete["receipts"]


def build_historical_rankings(dates: pd.DatetimeIndex, meta: pd.DataFrame,
                              receipts: dict[str, dict[str, str]]) -> tuple[dict, dict]:
    cache = RUNTIME / "historical_rankings_to_20191231.json"
    audit_cache = RUNTIME / "historical_ranking_audit.json"
    if cache.exists() and audit_cache.exists():
        return read_json(cache), read_json(audit_cache)

    factor_dates = dates[(dates >= "2013-01-01") & (dates <= "2019-12-31")]
    symbols = meta.index.tolist()
    shape = (len(factor_dates), len(symbols))
    eligible = np.zeros(shape, dtype=bool)
    values = {name: np.full(shape, np.nan, dtype=np.float32) for name in FACTORS}
    hashes_checked = 0

    for j, symbol in enumerate(symbols):
        path = archive_raw(symbol)
        key = str(path.relative_to(ARCHIVE)).replace("/", "\\")
        expected = receipts[symbol][key]
        if sha256(path) != expected:
            raise RuntimeError("Receipt hash mismatch: " + symbol)
        hashes_checked += 1
        x = pd.read_parquet(path)
        x["date"] = pd.to_datetime(x.date)
        x = x.set_index("date").sort_index()
        columns = ["open", "high", "low", "close", "preclose", "volume", "amount",
                   "turn", "tradestatus", "isST"]
        x = x.loc[x.index <= factor_dates[-1], columns].apply(pd.to_numeric, errors="raise")
        features, ok, _ = e.r.features(x)
        row = meta.loc[symbol]
        listed = pd.Series(True, index=ok.index)
        if row.ipoDate:
            listed &= listed.index >= pd.Timestamp(row.ipoDate)
        if row.outDate:
            listed &= listed.index < pd.Timestamp(row.outDate)
        ok &= listed
        positions = factor_dates.get_indexer(x.index)
        valid = positions >= 0
        positions = positions[valid]
        for name in FACTORS:
            values[name][positions, j] = features[name].to_numpy()[valid]
        eligible[positions, j] = ok.to_numpy()[valid]
        if (j + 1) % 400 == 0:
            print("RANK_INPUT", j + 1, len(symbols), flush=True)

    combined = np.zeros(shape, dtype=np.float32)
    complete_factor_row = eligible.copy()
    for name, weight in zip(FACTORS, WEIGHTS):
        ranked = pd.DataFrame(values.pop(name), index=factor_dates).where(eligible).rank(
            axis=1, pct=True, method="average").to_numpy(dtype=np.float32)
        complete_factor_row &= np.isfinite(ranked)
        combined += np.nan_to_num(ranked, nan=0.0) * np.float32(weight)
        print("RANK_FACTOR", name, flush=True)
    # pandas addition in the registered reconstruction propagates a missing
    # component; preserve that behavior rather than treating it as a zero rank.
    combined[~complete_factor_row] = np.nan
    scores = pd.DataFrame(combined, index=factor_dates, columns=symbols).rolling(
        5, min_periods=3).mean().where(eligible)

    generated = {}
    for day in factor_dates[factor_dates >= "2015-12-01"]:
        generated[str(day.date())] = scores.loc[day].dropna().sort_values(
            ascending=False, kind="mergesort").head(100).index.tolist()

    frozen = read_json(HOME / "results/latest/rankings_original.json")
    parity_days = ["2019-03-29", "2019-06-28", "2019-12-31"]
    parity = []
    for day in parity_days:
        got, expected = generated[day], frozen[day]
        parity.append({"date": day, "equal": got == expected,
                       "first_difference": next(((a, b) for a, b in zip(got, expected)
                                                  if a != b), None)})
    if not all(item["equal"] for item in parity):
        raise RuntimeError("Historical reconstruction does not match frozen overlap: " + str(parity))

    audit = {
        "source": str(ARCHIVE), "symbols": len(symbols), "verified_raw_receipts": hashes_checked,
        "raw_adjustflag": "3", "factor_start": str(factor_dates[0].date()),
        "generated_end": str(factor_dates[-1].date()), "overlap_parity": parity,
        "formula": {"factors": FACTORS, "weights": WEIGHTS, "smooth": 5, "min_smooth": 3},
    }
    write_json(cache, generated)
    write_json(audit_cache, audit)
    return generated, audit


def full_rankings(historical: dict) -> dict:
    # The first registered frozen date is the exact handoff boundary.
    frozen = read_json(HOME / "results/latest/rankings_original.json")
    ranks = {k: v for k, v in historical.items() if k < "2018-12-20"}
    ranks.update(frozen)
    cfg = read_json(TRACKING / "config.json")
    entry_hash = hashlib.sha256((HOME / "supermind_hushen_1.py").read_bytes()).hexdigest()
    assert cfg["entry_sha256"] == entry_hash
    for path in sorted((TRACKING / "signals").glob("*.json")):
        item = read_json(path)
        assert item["strategy_sha256"] == entry_hash
        ranks[path.stem] = item["ranks"]
    return ranks


def required_signal_dates(dates: pd.DatetimeIndex, starts: pd.DatetimeIndex) -> set[str]:
    anchor = dates.get_loc(pd.Timestamp("2018-01-02"))
    required = {str(dates[dates.get_loc(day) - 1].date()) for day in starts}
    for day in dates[(dates >= starts[0]) & (dates <= TARGET)]:
        actual = dates.get_loc(day)
        shifted = actual - anchor
        if (shifted - 1) % 20 == 0:
            required.add(str(dates[actual - 1].date()))
    return required


class HistoricalMarket:
    def __init__(self, dates: pd.DatetimeIndex, symbols: list[str], meta: pd.DataFrame,
                 receipts: dict[str, dict[str, str]]):
        self.dates = dates[dates >= "2015-12-01"]
        self.anchor = self.dates.get_loc(pd.Timestamp("2018-01-02"))
        self.symbols = symbols
        self.columns = {s: i for i, s in enumerate(symbols)}
        shape = (len(self.dates), len(symbols))
        self.raw = {name: np.full(shape, np.nan) for name in FIELDS}
        self.present = np.zeros(shape, dtype=bool)
        for j, symbol in enumerate(symbols):
            path = archive_raw(symbol)
            key = str(path.relative_to(ARCHIVE)).replace("/", "\\")
            if sha256(path) != receipts[symbol][key]:
                raise RuntimeError("Runtime receipt mismatch: " + symbol)
            x = pd.read_parquet(path)
            x["date"] = pd.to_datetime(x.date)
            if x.date.max() < pd.Timestamp(TARGET):
                current_path = production_raw(symbol)
                if current_path.exists():
                    extra = pd.read_parquet(current_path)
                    extra["date"] = pd.to_datetime(extra.date)
                    extra = extra.loc[extra.date > x.date.max()]
                    if len(extra):
                        x = pd.concat([x, extra], ignore_index=True)
            x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
            x = x.loc[x.index <= TARGET, FIELDS[:10]].apply(pd.to_numeric, errors="raise")
            x["volume20"] = x.volume.rolling(20).mean()
            x["prev_actual"] = x.close.shift()
            x["adjust_ratio"] = x.preclose / x.prev_actual
            positions = self.dates.get_indexer(x.index)
            valid = positions >= 0
            positions = positions[valid]
            x = x.iloc[np.flatnonzero(valid)]
            for name in FIELDS:
                self.raw[name][positions, j] = x[name].to_numpy()
            self.present[positions, j] = True
        self.outs = {s: pd.Timestamp(row.outDate) for s, row in meta.iterrows() if row.outDate}
        actions = e.r.mod(HOME / "backtest/actions.py", "jan2016_action_utils")
        actions.HERE = RUNTIME
        self.actions = actions.Actions(pd.Timestamp(TARGET))

    @lru_cache(maxsize=3)
    def __getitem__(self, date):
        return e.Day(self, self.dates.get_loc(date))


def simulate(market: HistoricalMarket, start: pd.Timestamp, ranks: dict):
    sessions = market.dates[(market.dates >= start) & (market.dates <= TARGET)]
    account = e.Account(sessions[0], market, "strict_daily_limits", 100000, "original", None)
    for day in sessions:
        actual = market.dates.get_loc(day)
        shifted = actual - market.anchor
        for symbol in list(account.holdings):
            action = market.actions.ensure(symbol, day)
            if action:
                account.actions[symbol, day] = action
        account.defer = False
        account.step(day, shifted, market.dates[actual - 1], ranks)
        account.curve[-1]["holdings"] = len(account.holdings)
    result = e.metrics(account, str(start.date()))
    result.update(scenario="strict_daily_limits", control="original", params=None)
    result["issues"] = account.issues
    result["reference"] = account.reference_diffs
    return result, account


def metric_summary(frame: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("期末资产", "final_equity", "currency"), ("累计收益", "total_return", "percent"),
        ("年化收益", "cagr", "percent"), ("最大回撤", "max_drawdown", "percent"),
        ("Sharpe", "sharpe", "number"), ("成交笔数", "trades", "number"),
        ("交易费用", "transaction_fees", "currency"), ("总成本", "total_cost", "currency"),
    ]
    rows = []
    for label, column, unit in specs:
        s = frame[column].astype(float)
        rows.append({"项目": label, "平均": s.mean(), "中位数": s.median(), "最小值": s.min(),
                     "最大值": s.max(), "标准差": s.std(ddof=1), "单位": unit})
    return pd.DataFrame(rows)


def markdown_report(summary: pd.DataFrame, detail: pd.DataFrame, audit: dict) -> str:
    lines = [
        "# 沪深1：2016年1月逐交易日起点至2026-10-23", "",
        "- 起点：2016年1月全部20个交易日；每个独立账户初始资金100,000元。",
        "- 2016—2018-12-19为同因子规则向前重建；2018-12-20起切换到登记基线的冻结排名。",
        "- 执行：次日开盘日线近似、A股整手/T+1/涨跌停/停牌/成交量约束及历史费率；未在末日强平。",
        "- 2019重叠段排名核验：{}。".format("全部一致" if all(x["equal"] for x in audit["overlap_parity"]) else "失败"),
        "", "| 项目 | 平均 | 中位数 | 最小值 | 最大值 | 标准差 |", "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        values = [row.平均, row.中位数, row.最小值, row.最大值, row.标准差]
        if row.单位 == "percent":
            cells = [f"{v:.2%}" for v in values]
        elif row.单位 == "currency":
            cells = [f"{v:,.2f}" for v in values]
        else:
            cells = [f"{v:.3f}" for v in values]
        lines.append("| {} | {} |".format(row.项目, " | ".join(cells)))
    lines += ["", "## 各起点", "",
              "| 起点 | 期末资产 | 累计收益 | 年化 | 最大回撤 | Sharpe | 成交笔数 | 总成本 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in detail.itertuples(index=False):
        lines.append(f"| {row.actual_start} | {row.final_equity:,.2f} | {row.total_return:.2%} | "
                     f"{row.cagr:.2%} | {row.max_drawdown:.2%} | {row.sharpe:.3f} | "
                     f"{int(row.trades)} | {row.total_cost:,.2f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    source_audit = read_json(ROOT / "K线数据/更新备份与审计/20261023/audit.json")
    assert source_audit["status"] == "ok" and source_audit["target"] == TARGET
    dates = trading_calendar()
    meta = universe()
    receipts = verified_receipts()
    historical, rank_audit = build_historical_rankings(dates, meta, receipts)
    ranks = full_rankings(historical)
    starts = dates[(dates >= "2016-01-01") & (dates <= "2016-01-31")]
    assert len(starts) == 20
    required = required_signal_dates(dates[dates >= "2015-12-01"], starts)
    missing = sorted(required - set(ranks))
    if missing:
        raise RuntimeError("Missing signal dates: " + str(missing))
    ranks = {key: ranks[key] for key in required}
    symbols = sorted({symbol for values in ranks.values() for symbol in values})
    print("RUNTIME", len(starts), "starts", len(required), "signal dates", len(symbols), "symbols", flush=True)
    market = HistoricalMarket(dates, symbols, meta, receipts)
    results = []
    curves = []
    trades = []
    try:
        for index, start in enumerate(starts, 1):
            result, account = simulate(market, start, ranks)
            if result["unresolved_actions"] or result["reference_differences"]:
                raise RuntimeError(f"Unresolved ledger issue for {start.date()}: {result['issues']} {result['reference']}")
            results.append(result)
            curve = pd.DataFrame(account.curve)
            curve.insert(0, "requested_start", str(start.date()))
            curves.append(curve)
            tx = pd.DataFrame(account.trades)
            if len(tx):
                tx.insert(0, "requested_start", str(start.date()))
                trades.append(tx)
            print("RUN", index, len(starts), start.date(), round(result["cagr"], 4),
                  round(result["max_drawdown"], 4), flush=True)
    finally:
        market.actions.close()

    detail = pd.DataFrame(results)
    summary = metric_summary(detail)
    detail.to_csv(OUT / "all_starts.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(curves, ignore_index=True).to_parquet(OUT / "daily_equity_all_starts.parquet", index=False)
    if trades:
        pd.concat(trades, ignore_index=True).to_parquet(OUT / "trades_all_starts.parquet", index=False)
    write_json(OUT / "audit.json", {
        "status": "ok", "target": TARGET, "starts": len(starts), "initial_cash_each": 100000,
        "source_market_audit": source_audit, "historical_rank_audit": rank_audit,
        "historical_archive": str(ARCHIVE), "required_signal_dates": len(required),
        "runtime_symbols": len(symbols), "strategy_sha256": hashlib.sha256(
            (HOME / "supermind_hushen_1.py").read_bytes()).hexdigest(),
        "boundary": "same-rule backward reconstruction before 2018-12-20; frozen registered ranks thereafter",
    })
    (OUT / "report.md").write_text(markdown_report(summary, detail, rank_audit), encoding="utf-8")
    print("COMPLETE", OUT, flush=True)


if __name__ == "__main__":
    main()
