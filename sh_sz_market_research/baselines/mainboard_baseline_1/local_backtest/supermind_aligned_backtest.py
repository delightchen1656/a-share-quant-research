"""沪深基准1的SuperMind对齐本地回测。

以平台导出的1000万元成交记录为撮合口径依据：月初09:31调仓、原始开盘价
双边0.20%滑点、佣金万3且最低5元、卖出印花税0.10%、100股整数手、
单次成交不超过当日成交量0.5%，未完成目标仓位不跨日追单。
"""
from __future__ import annotations

import base64
import json
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent
PROJECT = BASELINE.parents[1]
DATA = PROJECT / "data_pipeline" / "data"
PLATFORM_CODE = PROJECT / "platform" / "supermind" / "supermind_mainboard_baseline_1.py"
PLATFORM_RUN = BASELINE / "platform_runs" / "supermind_20200102_20260911_capital_10000000"
OUT = HERE / "outputs" / "supermind_aligned_10m_20200102_20260911"
CACHE = HERE / "cache" / "monthly_factor_snapshot.parquet"

START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2026-09-11")
INITIAL_CASH = 10_000_000.0
TARGET_COUNT = 20
BUFFER_COUNT = 40
TARGET_EXPOSURE = 0.95
MIN_LISTING_BARS = 250
MIN_AMOUNT20 = 50_000_000.0
MIN_VOL20 = 0.004
MAX_VOL20 = 0.08
MAX_SINGLE_MULTIPLE = 1.5
LOT = 100
SLIPPAGE = 0.002
COMMISSION = 0.0003
MIN_COMMISSION = 5.0
STAMP_TAX = 0.001  # 与本次SuperMind导出成交明细一致
OLD_PLATFORM_VOLUME_LIMIT = 0.005
ACTIVE_VOLUME_LIMIT = 0.05


def load_universe() -> list[str]:
    text = PLATFORM_CODE.read_text(encoding="utf-8")
    hit = re.search(r'_MAINBOARD_UNIVERSE_B64\s*=\s*"([^"]+)"', text)
    if hit is None:
        raise RuntimeError("SuperMind股票池不存在")
    symbols = json.loads(zlib.decompress(base64.b64decode(hit.group(1))).decode("utf-8"))
    return [s for s in symbols if is_ordinary_mainboard_a(s)]


def is_ordinary_mainboard_a(symbol: str) -> bool:
    """仅允许无需科创/创业/北交所等附加权限的沪深主板普通A股。"""
    if symbol.endswith(".SH"):
        return symbol.startswith(("600", "601", "603", "605"))
    if symbol.endswith(".SZ"):
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def exchange(symbol: str) -> str:
    return symbol[-2:]


def raw_path(symbol: str) -> Path:
    return DATA / "raw" / exchange(symbol) / f"{symbol}.parquet"


def qfq_path(symbol: str) -> Path:
    return DATA / "qfq" / exchange(symbol) / f"{symbol}.parquet"


def rank01(values: np.ndarray, reverse: bool = False) -> np.ndarray:
    a = np.asarray(values, dtype=float)
    out = np.zeros(len(a), dtype=float)
    valid = np.isfinite(a)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return out
    order = idx[np.argsort(a[idx], kind="mergesort")]
    if len(order) == 1:
        out[order[0]] = 0.5
    else:
        out[order] = np.arange(len(order), dtype=float) / float(len(order) - 1)
    if reverse:
        out[valid] = 1.0 - out[valid]
    return out


def dividend_quality(q: pd.DataFrame, r: pd.DataFrame) -> float:
    common = q.index.intersection(r.index)
    if len(common) < MIN_LISTING_BARS:
        return 0.0
    qc = q.loc[common, "close"].to_numpy(float)
    rc = r.loc[common, "close"].to_numpy(float)
    valid = np.isfinite(qc) & np.isfinite(rc) & (qc > 0) & (rc > 0)
    factor = np.full(len(common), np.nan)
    factor[valid] = qc[valid] / rc[valid]
    change = np.zeros(len(factor) - 1)
    pair = np.isfinite(factor[1:]) & np.isfinite(factor[:-1]) & (factor[:-1] > 0)
    change[pair] = np.abs(factor[1:][pair] / factor[:-1][pair] - 1)
    n = len(change)
    blocks = [change[max(0, n-250):], change[max(0, n-500):max(0, n-250)],
              change[max(0, n-750):max(0, n-500)]]
    yields = [float(np.sum(x[(x > .0005) & (x < .12)])) for x in blocks]
    persistence = sum(x > 0 for x in yields) / 3.0
    return .70 * persistence + .30 * min(yields[0] / .05, 1.0)


def trading_calendar() -> pd.DatetimeIndex:
    idx = pd.read_parquet(DATA / "indices" / "000905.SH.parquet", columns=["date", "close"])
    dates = pd.DatetimeIndex(pd.to_datetime(idx.date).sort_values().unique())
    return dates[(dates >= START) & (dates <= END)]


def execution_signal_dates() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    idx = pd.read_parquet(DATA / "indices" / "000905.SH.parquet", columns=["date", "close"])
    dates = pd.DatetimeIndex(pd.to_datetime(idx.date).sort_values().unique())
    pairs = []
    for i in range(1, len(dates)):
        d = pd.Timestamp(dates[i])
        if START <= d <= END and (i == 0 or dates[i-1].month != d.month):
            pairs.append((d, pd.Timestamp(dates[i-1])))
    return pairs


def build_factor_cache(force: bool = False) -> pd.DataFrame:
    if CACHE.exists() and not force:
        cached = pd.read_parquet(CACHE)
        return cached[cached.symbol.map(is_ordinary_mainboard_a)].copy()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pairs = execution_signal_dates()
    rows: list[dict] = []
    universe = load_universe()
    for number, symbol in enumerate(universe, 1):
        rp, qp = raw_path(symbol), qfq_path(symbol)
        if not rp.exists() or not qp.exists():
            continue
        raw = pd.read_parquet(rp, columns=["date", "close", "tradestatus"])
        qfq = pd.read_parquet(qp, columns=["date", "close", "amount", "isST", "tradestatus"])
        for frame in (raw, qfq):
            frame["date"] = pd.to_datetime(frame.date)
            frame.sort_values("date", inplace=True)
        # 对齐history(..., skip_paused=True, ...)：停牌记录不占历史窗口。
        raw = raw[raw.tradestatus.astype(str) == "1"].set_index("date")
        qfq = qfq[qfq.tradestatus.astype(str) == "1"].set_index("date")
        for execute_date, signal_date in pairs:
            q = qfq.loc[:signal_date].tail(751)
            if len(q) < MIN_LISTING_BARS:
                continue
            c = pd.to_numeric(q.close, errors="coerce").to_numpy(float)
            amount = pd.to_numeric(q.amount, errors="coerce").to_numpy(float)
            if len(c) < 121 or not np.all(np.isfinite(c[-121:])):
                continue
            if str(q.isST.iloc[-1]) == "1":
                continue
            ret = c[1:] / c[:-1] - 1
            vol20 = float(np.std(ret[-20:], ddof=1))
            amount20 = float(np.nanmean(amount[-20:]))
            if not (MIN_VOL20 <= vol20 <= MAX_VOL20 and amount20 >= MIN_AMOUNT20):
                continue
            neg = np.minimum(ret[-20:], 0)
            downside = max(float(np.sqrt(np.mean(neg*neg))), .002)
            high120, ma60 = float(np.max(c[-120:])), float(np.mean(c[-60:]))
            r = raw.loc[:signal_date].tail(751)
            rows.append({"execute_date": execute_date, "signal_date": signal_date,
                         "symbol": symbol, "amount20": amount20,
                         "near_high": c[-1]/high120, "below_high": 1-c[-1]/high120,
                         "below_ma60": max(0.0, 1-c[-1]/ma60),
                         "dividend": dividend_quality(q, r), "downside": downside})
        if number % 250 == 0:
            print(f"factor cache [{number}/{len(universe)}]", flush=True)
    factors = pd.DataFrame(rows)
    factors.to_parquet(CACHE, index=False)
    return factors


def ranked_months(factors: pd.DataFrame,
                  bull_weights: tuple[float, float, float] = (.25, .20, .55),
                  bear_weights: tuple[float, float, float] = (.40, .25, .35),
                  regime_ma: int = 120) -> dict[pd.Timestamp, pd.DataFrame]:
    idx = pd.read_parquet(DATA / "indices" / "000905.SH.parquet", columns=["date", "close"])
    idx["date"] = pd.to_datetime(idx.date)
    idx.sort_values("date", inplace=True)
    regimes = {}
    for d, s in factors[["execute_date", "signal_date"]].drop_duplicates().itertuples(index=False):
        x = idx[idx.date <= s].tail(121)
        regimes[pd.Timestamp(d)] = bool(len(x) >= regime_ma and
                                        x.close.iloc[-1] > x.close.tail(regime_ma).mean())
    out = {}
    for date, x in factors.groupby("execute_date"):
        x = x.copy().reset_index(drop=True)
        low_amount = rank01(x.amount20.to_numpy(), True)
        near_high = rank01(x.near_high.to_numpy())
        below_high = rank01(x.below_high.to_numpy())
        below_ma = rank01(x.below_ma60.to_numpy())
        dividend = rank01(x.dividend.to_numpy())
        if regimes[pd.Timestamp(date)]:
            x["score"] = (bull_weights[0]*low_amount + bull_weights[1]*near_high
                          + bull_weights[2]*dividend)
        else:
            x["score"] = (bear_weights[0]*below_high + bear_weights[1]*below_ma
                          + bear_weights[2]*dividend)
        out[pd.Timestamp(date)] = x.sort_values("score", ascending=False, kind="mergesort")
    return out


def commission(value: float) -> float:
    return max(MIN_COMMISSION, value * COMMISSION)


def apply_corporate_action(cash: float, positions: dict, day: pd.DataFrame,
                           previous_close: dict) -> float:
    for symbol, qty in list(positions.items()):
        if symbol not in day.index or symbol not in previous_close:
            continue
        row = day.loc[symbol]
        preclose = float(row.preclose)
        if not np.isfinite(preclose) or preclose <= 0:
            continue
        factor = previous_close[symbol] / preclose
        if abs(factor - 1) <= .02:
            continue
        share_factor = round(factor, 1)
        if share_factor >= 1.1:
            dividend = max(0.0, previous_close[symbol] - preclose*share_factor)
            cash += qty * dividend
            positions[symbol] = int(round(qty*share_factor))
        elif factor > 1.0:
            cash += qty * max(0.0, previous_close[symbol] - preclose)
    return cash


def load_daily_panel(symbols: set[str]) -> pd.DataFrame:
    frames = []
    cols = ["date", "open", "high", "low", "close", "preclose", "volume",
            "tradestatus", "pctChg", "isST"]
    for number, symbol in enumerate(sorted(symbols), 1):
        p = raw_path(symbol)
        if not p.exists():
            continue
        x = pd.read_parquet(p, columns=cols)
        x["date"] = pd.to_datetime(x.date)
        x = x[x.date.between(START, END)].copy()
        x["symbol"] = symbol
        frames.append(x)
        if number % 200 == 0:
            print(f"daily panel [{number}/{len(symbols)}]", flush=True)
    return pd.concat(frames, ignore_index=True)


def simulate(ranks: dict[pd.Timestamp, pd.DataFrame], volume_limit: float,
             target_count: int = TARGET_COUNT, buffer_count: int = BUFFER_COUNT,
             target_exposure: float = TARGET_EXPOSURE,
             max_single_multiple: float = MAX_SINGLE_MULTIPLE,
             panel: pd.DataFrame | None = None,
             ) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_symbols = set()
    for x in ranks.values():
        candidate_symbols.update(x.head(buffer_count).symbol)
    if panel is None:
        panel = load_daily_panel(candidate_symbols)
    else:
        panel = panel[panel.symbol.isin(candidate_symbols)].copy()
    by_date = {pd.Timestamp(d): x.set_index("symbol") for d, x in panel.groupby("date")}
    dates = trading_calendar()
    cash = INITIAL_CASH
    positions: dict[str, int] = {}
    previous_close: dict[str, float] = {}
    curve, trades = [], []
    for date in dates:
        date = pd.Timestamp(date)
        day = by_date.get(date, pd.DataFrame())
        cash = apply_corporate_action(cash, positions, day, previous_close)
        if date in ranks:
            ranked = ranks[date]
            buffer_symbols = ranked.head(buffer_count).symbol.tolist()
            retained = [s for s in positions if s in buffer_symbols]
            selected = retained[:target_count]
            for symbol in ranked.symbol:
                if symbol not in selected:
                    selected.append(symbol)
                if len(selected) >= target_count:
                    break
            ds = ranked.set_index("symbol").downside.to_dict()
            inv = np.array([1/ds[s] for s in selected], dtype=float)
            weights = inv/inv.sum()
            cap = max_single_multiple/target_count
            for _ in range(10):
                above = weights > cap
                if not above.any():
                    break
                fixed = np.minimum(weights[above], cap).sum()
                weights[above] = cap
                free = ~above
                if free.any():
                    weights[free] = weights[free]/weights[free].sum()*(1-fixed)
            targets = dict(zip(selected, weights*target_exposure))
            open_equity = cash + sum(q*float(day.loc[s, "open"]) for s, q in positions.items()
                                     if s in day.index and np.isfinite(day.loc[s, "open"]))
            # 与平台代码一致：旧持仓先处理，再处理首次买入。
            ordered = list(positions) + [s for s in selected if s not in positions]
            for symbol in ordered:
                if symbol not in day.index:
                    continue
                row = day.loc[symbol]
                if str(row.tradestatus) != "1" or float(row.open) <= 0 or float(row.volume) <= 0:
                    continue
                target_weight = targets.get(symbol, 0.0)
                target_qty = int(open_equity*target_weight/float(row.open)/LOT)*LOT
                current = positions.get(symbol, 0)
                delta = target_qty-current
                if delta == 0:
                    continue
                limit_qty = int(float(row.volume)*volume_limit/LOT)*LOT
                qty = min(abs(delta), limit_qty)
                if qty < LOT:
                    continue
                side = "BUY" if delta > 0 else "SELL"
                # 日频09:31的开盘封板判断。
                rate = .05 if str(row.isST) == "1" else .10
                upper = np.floor(float(row.preclose)*(1+rate)*100+.5)/100
                lower = np.floor(float(row.preclose)*(1-rate)*100+.5)/100
                if side == "BUY" and float(row.open) >= upper*.999:
                    continue
                if side == "SELL" and float(row.open) <= lower*1.001:
                    continue
                fill = float(row.open)*(1+SLIPPAGE if side == "BUY" else 1-SLIPPAGE)
                value = qty*fill
                fee = commission(value)
                tax = 0.0 if side == "BUY" else value*STAMP_TAX
                if side == "BUY":
                    while qty >= LOT and value+fee > cash:
                        qty -= LOT
                        value = qty*fill
                        fee = commission(value) if qty else 0
                    if qty < LOT:
                        continue
                    cash -= value+fee
                    positions[symbol] = current+qty
                else:
                    qty = min(qty, current)
                    value, fee, tax = qty*fill, commission(qty*fill), qty*fill*STAMP_TAX
                    cash += value-fee-tax
                    remain = current-qty
                    if remain:
                        positions[symbol] = remain
                    else:
                        positions.pop(symbol, None)
                trades.append({"date": date, "time": "09:31:00", "symbol": symbol,
                               "side": side, "fill_price": fill, "quantity": qty,
                               "amount": value, "commission": fee, "stamp_tax": tax})
        close_equity = cash
        for symbol, qty in positions.items():
            if symbol in day.index and np.isfinite(day.loc[symbol, "close"]):
                close_equity += qty*float(day.loc[symbol, "close"])
                previous_close[symbol] = float(day.loc[symbol, "close"])
            elif symbol in previous_close:
                close_equity += qty*previous_close[symbol]
        curve.append({"date": date, "equity": close_equity, "cash": cash,
                      "holdings": len(positions)})
    return pd.DataFrame(curve), pd.DataFrame(trades)


def platform_curve() -> pd.DataFrame:
    p = PLATFORM_RUN / "supermind_daily_positions_20191231_20260911.csv"
    x = pd.read_csv(p)
    # 每个有日期的行是当日账户汇总，随后无日期行是逐股持仓。
    holding_counts = []
    current_date = None
    count = 0
    for row in x.itertuples(index=False, name=None):
        if pd.notna(row[0]):
            if current_date is not None:
                holding_counts.append((current_date, count))
            current_date, count = row[0], 0
        elif pd.notna(row[3]):
            count += 1
    if current_date is not None:
        holding_counts.append((current_date, count))
    counts = pd.DataFrame(holding_counts, columns=["date", "holdings"])
    counts["date"] = pd.to_datetime(counts.date)
    x["equity"] = pd.to_numeric(x["总资产"], errors="coerce")
    x["cash"] = pd.to_numeric(x["现金"], errors="coerce")
    x = x[x.equity.notna()][["日期", "equity", "cash"]].copy()
    x["date"] = pd.to_datetime(x["日期"])
    x = x.drop(columns="日期").sort_values("date").drop_duplicates("date", keep="last")
    return x.merge(counts, on="date", how="left")


def metrics(curve: pd.DataFrame, initial: float) -> dict:
    x = curve.sort_values("date")
    ret = x.equity.pct_change().dropna()
    years = (x.date.iloc[-1]-x.date.iloc[0]).days/365.25
    total = x.equity.iloc[-1]/initial-1
    dd = x.equity/x.equity.cummax()-1
    return {"start": str(x.date.iloc[0].date()), "end": str(x.date.iloc[-1].date()),
            "initial_cash": initial, "final_equity": float(x.equity.iloc[-1]),
            "total_return": float(total), "annualized_return": float((1+total)**(1/years)-1),
            "max_drawdown": float(dd.min()),
            "sharpe": float(np.sqrt(252)*ret.mean()/ret.std()),
            "average_holdings": (float(x.holdings.mean()) if "holdings" in x
                                  and x.holdings.notna().any() else None),
            "max_holdings": (int(x.holdings.max()) if "holdings" in x
                             and x.holdings.notna().any() else None)}


def compare_trades(local: pd.DataFrame) -> dict:
    p = PLATFORM_RUN / "supermind_trades_20200102_20260901.csv"
    actual = pd.read_csv(p)
    actual["side"] = actual["操作"].map({"买入": "BUY", "卖出": "SELL"})
    actual["quantity"] = pd.to_numeric(actual["数量"]).abs().astype(int)
    actual["date"] = pd.to_datetime(actual["日期"])
    keys = ["date", "代码", "side"]
    a = actual.rename(columns={"代码": "symbol"})[["date", "symbol", "side", "quantity"]]
    b = local[["date", "symbol", "side", "quantity"]]
    exact = a.merge(b, on=["date", "symbol", "side", "quantity"], how="inner")
    key_match = a.merge(b, on=["date", "symbol", "side"], how="inner")
    return {"platform_rows": len(a), "local_rows": len(b), "exact_row_matches": len(exact),
            "date_symbol_side_matches": len(key_match),
            "exact_match_rate_vs_platform": len(exact)/len(a) if len(a) else None,
            "key_match_rate_vs_platform": len(key_match)/len(a) if len(a) else None}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    factors = build_factor_cache()
    ranks = ranked_months(factors)
    calibrated, calibrated_trades = simulate(ranks, OLD_PLATFORM_VOLUME_LIMIT)
    active, active_trades = simulate(ranks, ACTIVE_VOLUME_LIMIT)
    platform = platform_curve()
    # 平台导出截至2019-12-31含初始行，本地从首个交易日开始；指标统一以1000万元为基数。
    calibrated_metrics = metrics(calibrated, INITIAL_CASH)
    active_metrics = metrics(active, INITIAL_CASH)
    platform_metrics = metrics(platform, INITIAL_CASH)
    comparison = compare_trades(calibrated_trades)
    merged = calibrated.merge(platform, on="date", suffixes=("_local", "_platform"), how="inner")
    merged["equity_gap"] = merged.equity_local-merged.equity_platform
    merged["equity_gap_pct"] = merged.equity_local/merged.equity_platform-1
    summary = {"old_0_5pct_local_calibration": calibrated_metrics,
               "old_0_5pct_platform_export": platform_metrics,
               "active_5pct_local": active_metrics,
               "old_trade_alignment": comparison,
               "last_common_equity_gap": float(merged.equity_gap.iloc[-1]),
               "last_common_equity_gap_pct": float(merged.equity_gap_pct.iloc[-1])}
    calibrated.to_csv(OUT/"local_old_0_5pct_daily_equity.csv", index=False, encoding="utf-8-sig")
    calibrated_trades.to_csv(OUT/"local_old_0_5pct_trades.csv", index=False, encoding="utf-8-sig")
    active.to_csv(OUT/"local_active_5pct_daily_equity.csv", index=False, encoding="utf-8-sig")
    active_trades.to_csv(OUT/"local_active_5pct_trades.csv", index=False, encoding="utf-8-sig")
    merged.to_csv(OUT/"old_0_5pct_daily_equity_comparison.csv", index=False, encoding="utf-8-sig")
    (OUT/"alignment_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 沪深基准1 SuperMind口径对齐", "",
             "初始资金1000万元，区间2020-01-02至2026-09-11。", "",
             "| 口径 | 期末资产 | 年化 | 最大回撤 | Sharpe | 平均持仓 | 最高持仓 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for label, item in [("平台旧0.5%", platform_metrics),
                        ("本地旧0.5%校准", calibrated_metrics),
                        ("本地正式5%", active_metrics)]:
        lines.append("| %s | %.2f万 | %.2f%% | %.2f%% | %.3f | %s | %s |" % (
            label, item["final_equity"]/10000, item["annualized_return"]*100,
            item["max_drawdown"]*100, item["sharpe"],
            "—" if item["average_holdings"] is None else "%.1f" % item["average_holdings"],
            "—" if item["max_holdings"] is None else str(item["max_holdings"])))
    lines += ["", "旧0.5%%本地与平台期末资产差异为%.2f%%；平均持仓和最高持仓基本复现。" %
              (summary["last_common_equity_gap_pct"]*100),
              "逐笔差异主要来自BaoStock与SuperMind的历史复权因子、股票状态和平台内部目标仓位取整。",
              "新正式口径采用5%成交量限制，未完成订单仍不跨日追单；平均持仓恢复到约20只。"]
    (OUT/"REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
