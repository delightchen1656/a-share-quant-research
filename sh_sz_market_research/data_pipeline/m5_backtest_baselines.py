"""M5/M6: realistic daily local backtests for mainboard baselines 1-2, 3-1, 2-2.

The engine uses T close scores and T+1 raw open executions, A-share lots,
commissions/tax/slippage, suspensions and one-price limit locks.  Parameters are
fixed before the 2025-2026/7 holdout is evaluated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "derived" / "backtest_market_by_year"
SCORE_DIR = DATA / "derived" / "scores"
OUT = ROOT / "outputs" / "m5_backtests"
MODEL_DIR = ROOT / "models"
START, END = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-07-31")
INITIAL_CASH = 1_000_000.0
TOP_PER_DAY, MAX_POSITIONS = 8, 14
BASE_FRACTION, MAX_SINGLE = .10, .20
STOP_LOSS, TAKE_HALF, TAKE_ALL = .07, .24, .34
SLIPPAGE = .002
COMMISSION, TRANSFER, MIN_FEE = .0003, .00001, 5.0
LOT = 100


def fee(amount: float) -> float:
    return max(MIN_FEE, amount * COMMISSION) + amount * TRANSFER


def stamp_tax(amount: float, date: pd.Timestamp) -> float:
    return amount * (.0005 if date >= pd.Timestamp("2023-08-28") else .001)


def limit_price(preclose: float, multiple: float) -> float:
    return np.floor(preclose * multiple * 100 + .5) / 100


def build_cache() -> None:
    manifest = CACHE / "manifest.json"
    if manifest.exists() and all((CACHE / f"{y}.parquet").exists() for y in range(2018, 2027)):
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    # A prior interrupted build has no manifest and is safe to replace one year at a time.
    for y in range(2018, 2027):
        partial = CACHE / f"{y}.parquet"
        if partial.exists():
            partial.unlink()
    writers = {}
    counts = {y: 0 for y in range(2018, 2027)}
    try:
        paths = sorted(SCORE_DIR.rglob("*.parquet"))
        for i, score_path in enumerate(paths, 1):
            symbol, exchange = score_path.stem, score_path.parent.name
            raw = pd.read_parquet(DATA / "raw" / exchange / f"{symbol}.parquet",
                                  columns=["date", "open", "high", "low", "close", "preclose",
                                           "volume", "amount", "tradestatus", "pctChg", "isST"])
            qfq = pd.read_parquet(DATA / "qfq" / exchange / f"{symbol}.parquet",
                                  columns=["date", "close"])
            scores = pd.read_parquet(score_path, columns=["date", "rally_probability",
                                                          "stop_probability", "signal"])
            for x in (raw, qfq, scores):
                x["date"] = x.date.astype(str).str[:10]
            x = raw.merge(qfq.rename(columns={"close": "qfq_close"}), on="date", how="inner")
            x = x.merge(scores, on="date", how="inner")
            x["symbol"] = symbol
            x["exchange"] = exchange
            x["year"] = x.date.str[:4].astype(int)
            for col in ("open", "high", "low", "close", "preclose", "volume", "amount",
                        "pctChg", "qfq_close", "rally_probability", "stop_probability"):
                x[col] = pd.to_numeric(x[col], errors="coerce").astype("float64")
            qclose = x.qfq_close.astype(float)
            x["q_ret1"] = qclose.pct_change(fill_method=None)
            x["q_ret20"] = qclose.pct_change(20, fill_method=None)
            x["above_ma60"] = qclose > qclose.rolling(60).mean()
            x["q_ret22"] = qclose.pct_change(22, fill_method=None)
            x["amount20"] = x.amount.astype(float).rolling(20).mean()
            x["amount60"] = x.amount.astype(float).rolling(60).mean()
            for year, part in x.groupby("year"):
                if year not in counts:
                    continue
                table = pa.Table.from_pandas(part.drop(columns="year"), preserve_index=False)
                target = CACHE / f"{year}.parquet"
                if year not in writers:
                    writers[year] = pq.ParquetWriter(target, table.schema, compression="zstd")
                writers[year].write_table(table)
                counts[year] += len(part)
            if i % 300 == 0:
                print(f"cache [{i}/{len(paths)}]", flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    manifest.write_text(json.dumps({"created_at": datetime.now().isoformat(timespec="seconds"),
                                    "counts": counts}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_market() -> pd.DataFrame:
    frames = [pd.read_parquet(CACHE / f"{y}.parquet") for y in range(2018, 2027)]
    market = pd.concat(frames, ignore_index=True)
    market["date"] = pd.to_datetime(market.date)
    for col in ("open", "high", "low", "close", "preclose", "volume", "amount", "pctChg",
                "qfq_close", "q_ret1", "q_ret20", "q_ret22", "amount20", "amount60",
                "rally_probability", "stop_probability"):
        market[col] = pd.to_numeric(market[col], errors="coerce")
    return market


def market_and_industry_state(market: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    mapping = pd.read_csv(DATA / "metadata" / "current_industry_map.csv", dtype=str,
                          encoding="utf-8-sig")
    symbol_col = "symbol" if "symbol" in mapping else "code"
    industry_col = "industry" if "industry" in mapping else mapping.columns[-1]
    imap = mapping.drop_duplicates(symbol_col).set_index(symbol_col)[industry_col].to_dict()
    market["industry"] = market.symbol.map(imap)

    daily = market.groupby("date").agg(
        market_ret=("q_ret1", "mean"), breadth=("above_ma60", "mean"),
        median_ret20=("q_ret20", "median"), dispersion=("q_ret1", "std"),
    ).sort_index()
    idx = pd.read_parquet(DATA / "indices" / "000905.SH.parquet").sort_values("date")
    idx["date"] = pd.to_datetime(idx.date)
    iclose = pd.to_numeric(idx.close, errors="coerce")
    ix = pd.DataFrame({"date": idx.date, "idx_ret5": iclose.pct_change(5),
                       "idx_ret20": iclose.pct_change(20), "idx_ret60": iclose.pct_change(60),
                       "idx_vol20": iclose.pct_change().rolling(20).std()}).set_index("date")
    daily = daily.join(ix, how="left")
    for n in (5, 20):
        daily[f"market_ret{n}"] = (1 + daily.market_ret.fillna(0)).rolling(n).apply(np.prod, raw=True) - 1
    bear_features = ["idx_ret5", "idx_ret20", "idx_ret60", "idx_vol20", "breadth",
                     "median_ret20", "dispersion", "market_ret5", "market_ret20"]
    idx_future_min = (iclose.shift(-1).iloc[::-1].rolling(20, min_periods=20).min().iloc[::-1]
                      / iclose - 1)
    label = pd.Series((idx_future_min <= -.08).astype(float).to_numpy(), index=idx.date)
    label[idx_future_min.isna().to_numpy()] = np.nan
    daily["bear_label"] = label.reindex(daily.index)
    train = daily.loc[:"2023-11-30"].dropna(subset=bear_features + ["bear_label"])
    valid = daily.loc["2024-01-01":"2024-11-30"].dropna(subset=bear_features + ["bear_label"])
    bear_model = HistGradientBoostingClassifier(max_iter=140, learning_rate=.04,
        max_leaf_nodes=9, l2_regularization=4, class_weight="balanced", random_state=202)
    bear_model.fit(train[bear_features], train.bear_label.astype(int))
    vp = bear_model.predict_proba(valid[bear_features])[:, 1]
    daily["bear_probability"] = np.nan
    good = daily[bear_features].notna().all(axis=1)
    daily.loc[good, "bear_probability"] = bear_model.predict_proba(daily.loc[good, bear_features])[:, 1]
    bear_meta = {"features": bear_features, "train_end": "2023-11-30",
                 "validation": ["2024-01-01", "2024-11-30"],
                 "train_samples": len(train), "train_positive_rate": float(train.bear_label.mean()),
                 "validation_samples": len(valid), "validation_positive_rate": float(valid.bear_label.mean()),
                 "validation_roc_auc": float(roc_auc_score(valid.bear_label, vp)),
                 "validation_pr_auc": float(average_precision_score(valid.bear_label, vp))}
    joblib.dump({"model": bear_model, "metadata": bear_meta}, MODEL_DIR / "mainboard_bear_frozen.joblib", compress=3)

    use = market.dropna(subset=["industry"]).copy()
    group = use.groupby(["date", "industry"]).agg(
        group_ret=("q_ret1", "mean"), breadth=("above_ma60", "mean"),
        amount20=("amount20", "sum"), amount60=("amount60", "sum"),
        leader=("q_ret22", "max"), members=("symbol", "nunique"),
    ).reset_index().sort_values(["industry", "date"])
    group["nav"] = group.groupby("industry").group_ret.transform(lambda x: (1 + x.fillna(0)).cumprod())
    by = group.groupby("industry", group_keys=False)
    low252 = by.nav.transform(lambda x: x.rolling(252, min_periods=120).min())
    high252 = by.nav.transform(lambda x: x.rolling(252, min_periods=120).max())
    group["position"] = 100 * (group.nav - low252) / (high252 - low252)
    mom63 = group.nav / by.nav.shift(63) - 1
    sigmoid = lambda value, scale: 100 / (1 + np.exp(-np.clip(value, -5*scale, 5*scale) / scale))
    trend = sigmoid(mom63, .12)
    volume_score = sigmoid(group.amount20 / group.amount60 - 1, .30)
    leader_score = sigmoid(group.leader, .15)
    # The historical implementation gives linkage 10%; neutral 50 is used because
    # the compact daily cache does not retain the full 20-day member covariance cube.
    group["heat"] = (.20 * group.position + .25 * trend + .20 * 100*group.breadth
                     + .12 * volume_score + .10 * 50 + .13 * leader_score).clip(0, 100)
    group["delta"] = group.heat - by.heat.shift(10)
    group["allowed"] = ((group.delta > 0) |
                        ((group.heat >= 65) & (group.delta > -4) & (100*group.breadth >= 55)))
    group.loc[group.members < 4, "allowed"] = False
    return daily.reset_index(), group[["date", "industry", "heat", "delta", "breadth", "allowed"]], bear_meta


@dataclass
class Account:
    name: str
    cash: float = INITIAL_CASH
    positions: dict = field(default_factory=dict)
    trades: list = field(default_factory=list)
    curve: list = field(default_factory=list)
    previous_close: dict = field(default_factory=dict)


def sell(account: Account, symbol: str, pos: dict, qty: int, price: float,
         date: pd.Timestamp, reason: str) -> None:
    amount = qty * price * (1 - SLIPPAGE)
    proceeds = amount - fee(amount) - stamp_tax(amount, date)
    account.cash += proceeds
    pos["realized"] += proceeds
    pos["qty"] -= qty
    if reason == "TPHALF":
        pos["half"] = True
    if pos["qty"] <= 0:
        account.trades.append({"strategy": account.name, "symbol": symbol,
            "entry_date": pos["entry_date"], "exit_date": date, "reason": reason,
            "return": pos["realized"] / pos["initial_cost"], "days": (date-pos["entry_date"]).days})
        del account.positions[symbol]


def simulate(market: pd.DataFrame, states: pd.DataFrame, industry: pd.DataFrame,
             start: pd.Timestamp = START, end: pd.Timestamp = END,
             initial_cash: float = INITIAL_CASH) -> tuple[list, pd.DataFrame, pd.DataFrame]:
    state_map = states.set_index("date").to_dict("index")
    industry_allowed = industry.set_index(["date", "industry"]).allowed.to_dict()
    imap = market.dropna(subset=["industry"]).drop_duplicates("symbol").set_index("symbol").industry.to_dict()
    accounts = {name: Account(name, cash=initial_cash)
                for name in ("baseline1-2", "baseline3-1", "baseline2-2")}
    tradable = market[(market.tradestatus.astype(str) == "1") & market.volume.gt(0)]
    last_tradable = tradable.groupby("symbol").date.max().to_dict()
    dataset_last = market.date.max()
    previous_signals = pd.DataFrame()
    dates = sorted(d for d in market.date.unique() if start <= d <= end)
    by_date = {d: x.set_index("symbol") for d, x in market[market.date.between(start, end)].groupby("date")}
    previous_bear = 0.0
    for di, date in enumerate(dates, 1):
        day = by_date[date]
        bear = previous_bear
        for account in accounts.values():
            # Corporate-action reconciliation before valuation/trading.
            for symbol, pos in list(account.positions.items()):
                if symbol not in day.index or symbol not in account.previous_close:
                    continue
                row = day.loc[symbol]
                factor = account.previous_close[symbol] / row.preclose if row.preclose > 0 else 1
                if abs(factor - 1) > .02:
                    share_factor = round(factor, 1)
                    if share_factor >= 1.1:
                        old = pos["qty"]
                        dividend = max(0, account.previous_close[symbol] - row.preclose * share_factor)
                        account.cash += old * dividend
                        pos["qty"] = int(round(old * share_factor))
                        pos["entry"] = max(.01, (pos["entry"] - dividend) / share_factor)

            # Exits first; a locked down-limit/suspension remains held.
            for symbol, pos in list(account.positions.items()):
                if symbol not in day.index or pos["entry_date"] == date:
                    continue
                row = day.loc[symbol]
                if str(row.tradestatus) != "1" or row.open <= 0 or row.volume <= 0:
                    continue
                # Delisted securities have no later quote with which to value the
                # account.  Settle on their final tradable day with a conservative
                # 10% haircut and record it separately.  Active names are untouched.
                if last_tradable.get(symbol) == date and date < dataset_last:
                    sell(account, symbol, pos, pos["qty"], float(row.close) * .90,
                         date, "DELIST_SETTLEMENT")
                    continue
                if row.high == row.low and row.pctChg <= -9.5:
                    continue
                mark, reason, qty = float(row.open), None, 0
                if mark <= pos["entry"] * (1 - STOP_LOSS):
                    reason, qty = "STOP", pos["qty"]
                elif mark >= pos["entry"] * (1 + TAKE_ALL):
                    reason, qty = "TPALL", pos["qty"]
                elif mark >= pos["entry"] * (1 + TAKE_HALF) and not pos["half"]:
                    proposed = (pos["qty"] // 200) * 100
                    if proposed >= LOT and pos["qty"] - proposed >= LOT:
                        reason, qty = "TPHALF", proposed
                else:
                    age = (date - pos["entry_date"]).days
                    max_days = 30
                    if account.name == "baseline3-1" and age >= 30 and mark >= pos["entry"] * 1.10:
                        max_days = 60
                    if age >= max_days:
                        reason, qty = "TIME", pos["qty"]
                if reason:
                    sell(account, symbol, pos, qty, mark, date, reason)

            equity_open = account.cash + sum(p["qty"] * float(day.loc[s, "open"])
                                              for s, p in account.positions.items() if s in day.index)
            fraction = BASE_FRACTION
            if account.name == "baseline2-2":
                fraction = .055 if bear >= .70 else .075 if bear >= .55 else .09 if bear >= .40 else .10
            candidates = previous_signals
            if not candidates.empty:
                candidates = candidates[~candidates.symbol.isin(account.positions)]
                if account.name == "baseline2-2":
                    candidates = candidates[candidates.apply(
                        lambda z: bool(industry_allowed.get((z.date, imap.get(z.symbol)), False)), axis=1)]
                for z in candidates.head(TOP_PER_DAY).itertuples():
                    symbol = z.symbol
                    if len(account.positions) >= MAX_POSITIONS or symbol not in day.index:
                        break
                    row = day.loc[symbol]
                    if str(row.tradestatus) != "1" or str(row.isST) == "1" or row.open <= 0 or row.volume <= 0:
                        continue
                    if last_tradable.get(symbol) == date and date < dataset_last:
                        continue
                    if row.high == row.low and row.pctChg >= 9.5:
                        continue
                    execution = float(row.open) * (1 + SLIPPAGE)
                    dynamic_fraction = max(fraction, execution * LOT * 1.01 / max(equity_open, 1))
                    dynamic_fraction = min(dynamic_fraction, MAX_SINGLE)
                    qty = int((equity_open * dynamic_fraction) / execution / LOT) * LOT
                    amount = qty * execution
                    total = amount + fee(amount) if qty >= LOT else np.inf
                    while qty >= LOT and total > account.cash:
                        qty -= LOT
                        amount = qty * execution
                        total = amount + fee(amount)
                    if qty < LOT:
                        continue
                    account.cash -= total
                    account.positions[symbol] = {"qty": qty, "entry": execution,
                        "entry_date": date, "half": False, "realized": -total, "initial_cost": total}
            equity = account.cash + sum(p["qty"] * float(day.loc[s, "close"])
                                        for s, p in account.positions.items() if s in day.index)
            account.curve.append({"strategy": account.name, "date": date, "equity": equity,
                                  "cash": account.cash, "positions": len(account.positions),
                                  "bear_probability": bear})
            account.previous_close.update(day.close.astype(float).to_dict())

        # Today's qfq signal becomes tomorrow's order list.
        s = day[(day.signal.fillna(False)) & day.stop_probability.le(.50)].copy().reset_index()
        if not s.empty:
            s["rank_score"] = s.rally_probability - .22 * s.stop_probability
            previous_signals = s.sort_values("rank_score", ascending=False).head(50)
            previous_signals["date"] = date
        else:
            previous_signals = pd.DataFrame()
        previous_bear = float(state_map.get(date, {}).get("bear_probability", 0) or 0)
        if di % 250 == 0:
            print(f"backtest [{di}/{len(dates)}]", flush=True)

    curves = pd.concat([pd.DataFrame(a.curve) for a in accounts.values()], ignore_index=True)
    trades = pd.concat([pd.DataFrame(a.trades) for a in accounts.values()], ignore_index=True)
    summaries = []
    for name, a in accounts.items():
        c = pd.DataFrame(a.curve)
        years = (c.date.iloc[-1] - c.date.iloc[0]).days / 365.25
        total = c.equity.iloc[-1] / initial_cash - 1
        dd = c.equity / c.equity.cummax() - 1
        t = pd.DataFrame(a.trades)
        daily_ret = c.equity.pct_change().dropna()
        summaries.append({"strategy": name, "start": str(c.date.iloc[0].date()),
            "end": str(c.date.iloc[-1].date()), "initial_cash": initial_cash,
            "final_equity": float(c.equity.iloc[-1]), "total_return": float(total),
            "annualized_return": float((1 + total) ** (1/years) - 1),
            "max_drawdown": float(dd.min()), "sharpe": float(np.sqrt(252)*daily_ret.mean()/daily_ret.std()),
            "closed_trades": len(t), "win_rate": float((t["return"] > 0).mean()) if len(t) else None,
            "mean_trade_return": float(t["return"].mean()) if len(t) else None})
    return summaries, curves, trades


def period_metrics(curves: pd.DataFrame) -> pd.DataFrame:
    periods = [(str(y), f"{y}-01-01", f"{y}-12-31") for y in range(2020, 2026)] + [
        ("2026/1-7", "2026-01-01", "2026-07-31"),
        ("锁定测试2025-2026/7", "2025-01-01", "2026-07-31")]
    rows = []
    for name, start, end in periods:
        for strategy, c in curves.groupby("strategy"):
            x = c[c.date.between(start, end)].sort_values("date")
            if x.empty:
                continue
            # Period return rebased to its first observed equity; this is attribution,
            # while the full run above remains a continuous account simulation.
            total = x.equity.iloc[-1] / x.equity.iloc[0] - 1
            days = max((x.date.iloc[-1]-x.date.iloc[0]).days, 1)
            dd = x.equity / x.equity.cummax() - 1
            rows.append({"period": name, "strategy": strategy, "period_return": total,
                         "annualized_return": (1+total)**(365.25/days)-1,
                         "max_drawdown": dd.min(), "end_equity_continuous": x.equity.iloc[-1]})
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("preparing consolidated market cache", flush=True)
    build_cache()
    print("loading market", flush=True)
    market = load_market()
    print("training frozen bear model and computing industry states", flush=True)
    states, industries, bear_meta = market_and_industry_state(market)
    print("running three baselines together", flush=True)
    summaries, curves, trades = simulate(market, states, industries)
    periods = period_metrics(curves)
    independent_rows = []
    independent_trades = []
    independent_periods = [(str(y), pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31"))
                           for y in range(2020, 2026)]
    independent_periods += [
        ("2026/1-7", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-07-31")),
        ("锁定测试2025-2026/7", pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-31")),
    ]
    for period_name, period_start, period_end in independent_periods:
        print(f"independent period {period_name}", flush=True)
        sm, _, tr = simulate(market, states, industries, period_start, period_end, INITIAL_CASH)
        for row in sm:
            row["period"] = period_name
            independent_rows.append(row)
        if not tr.empty:
            tr["period"] = period_name
            independent_trades.append(tr)
    independent = pd.DataFrame(independent_rows)
    pd.DataFrame(summaries).to_csv(OUT / "full_period_summary.csv", index=False, encoding="utf-8-sig")
    curves.to_parquet(OUT / "daily_equity.parquet", index=False)
    trades.to_csv(OUT / "trades.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(OUT / "period_metrics.csv", index=False, encoding="utf-8-sig")
    independent.to_csv(OUT / "independent_period_summary.csv", index=False, encoding="utf-8-sig")
    if independent_trades:
        pd.concat(independent_trades, ignore_index=True).to_csv(
            OUT / "independent_period_trades.csv", index=False, encoding="utf-8-sig")
    (OUT / "bear_model_metadata.json").write_text(json.dumps(bear_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# M5/M6 主板三基准本地回测", "",
             "统一口径：100万元、日频、T日信号/T+1原始开盘价、0.20%滑点、100股整数手、佣金/最低佣金/过户费/印花税、停牌及一字涨跌停限制。", "",
             "| 策略 | 期末资产 | 累计收益 | 年化 | 最大回撤 | Sharpe | 完整交易 | 胜率 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for x in summaries:
        lines.append(f"| {x['strategy']} | {x['final_equity']/10000:.2f}万 | {x['total_return']:.2%} | {x['annualized_return']:.2%} | {x['max_drawdown']:.2%} | {x['sharpe']:.2f} | {x['closed_trades']} | {x['win_rate']:.2%} |")
    lines += ["", "## 分期表现", "", "| 区间 | 策略 | 收益 | 年化 | 最大回撤 | 连续账户期末资产 |",
              "|---|---|---:|---:|---:|---:|"]
    for x in periods.itertuples():
        lines.append(f"| {x.period} | {x.strategy} | {x.period_return:.2%} | {x.annualized_return:.2%} | {x.max_drawdown:.2%} | {x.end_equity_continuous/10000:.2f}万 |")
    lines += ["", "## 每段独立投入100万元", "",
              "| 区间 | 策略 | 期末资产 | 收益 | 年化 | 最大回撤 | 完整交易 | 胜率 |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for x in independent.itertuples():
        lines.append(f"| {x.period} | {x.strategy} | {x.final_equity/10000:.2f}万 | {x.total_return:.2%} | {x.annualized_return:.2%} | {x.max_drawdown:.2%} | {x.closed_trades} | {x.win_rate:.2%} |")
    lines += ["", "注意：基准2-2目前使用BaoStock当前行业映射，缺少完整历史行业变更链；因此是功能/收益验证，不作为消除行业幸存偏差后的最终版本。",
              "M6锁定区间未参与股票池、阈值、暴涨模型、先止损模型或熊市模型的选择。"]
    (OUT / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(pd.DataFrame(summaries).to_string(index=False), flush=True)
    print(periods.to_string(index=False), flush=True)
    print(independent.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
