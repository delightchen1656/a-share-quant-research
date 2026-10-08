"""Minimal A-share daily backtest using the migrated BaoStock files.

Signal: previous adjusted close > MA20 * 1.01 -> long; < MA20 * 0.99 -> flat.
Execution: next session open, dedicated CNY 100,000 account, 95% target exposure.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from 默认策略 import FACTOR_FIELDS, FACTOR_LOOKBACK, FACTOR_NAME, factor_decision

SYMBOL = "600000.SH"
INITIAL_CASH = 100000.0
TARGET_EXPOSURE = 0.95
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
ONE_SIDE_SLIPPAGE = 0.002
DAILY_VOLUME_LIMIT = 0.05


def round_cent(value: float) -> float:
    return round(float(value) + 1e-10, 2)


def transfer_rate(date: pd.Timestamp) -> float:
    return 0.00002 if date < pd.Timestamp("2022-04-29") else 0.00001


def stamp_rate(date: pd.Timestamp) -> float:
    return 0.001 if date < pd.Timestamp("2023-08-28") else 0.0005


def price_limits(preclose: float, is_st: bool, date: pd.Timestamp) -> tuple[float, float]:
    # Match this project's frozen main-board convention. The 2026-07-06 ST
    # change is irrelevant for the chosen non-ST example but remains explicit.
    pct = 0.05 if is_st and date < pd.Timestamp("2026-07-06") else 0.10
    high = math.floor(preclose * (1 + pct) * 100 + 0.5) / 100
    low = math.floor(preclose * (1 - pct) * 100 + 0.5) / 100
    return high, low


@dataclass
class Lot:
    quantity: int
    buy_date: pd.Timestamp
    dividend_basis: float = 0.0


class Account:
    def __init__(self) -> None:
        self.cash = INITIAL_CASH
        self.lots: list[Lot] = []
        self.receivables: list[tuple[pd.Timestamp, float]] = []
        self.trades: list[dict] = []
        self.rejections: list[dict] = []

    @property
    def quantity(self) -> int:
        return sum(x.quantity for x in self.lots)

    def available(self, date: pd.Timestamp) -> int:
        return sum(x.quantity for x in self.lots if x.buy_date < date)

    def settle_cash(self, date: pd.Timestamp) -> None:
        waiting = []
        for pay_date, amount in self.receivables:
            if pay_date <= date:
                self.cash += amount
            else:
                waiting.append((pay_date, amount))
        self.receivables = waiting

    def dividend(self, date: pd.Timestamp, pay_date: pd.Timestamp, cash_ps: float) -> None:
        if self.quantity <= 0 or cash_ps <= 0:
            return
        amount = round_cent(self.quantity * cash_ps)
        if pay_date <= date:
            self.cash += amount
        else:
            self.receivables.append((pay_date, amount))
        for lot in self.lots:
            lot.dividend_basis += cash_ps

    def reject(self, date: pd.Timestamp, side: str, reason: str) -> None:
        self.rejections.append({"date": str(date.date()), "side": side, "reason": reason})

    def buy(self, date: pd.Timestamp, requested: int, row: pd.Series) -> int:
        if int(row.tradestatus) != 1 or row.volume <= 0:
            self.reject(date, "BUY", "suspended_or_no_volume")
            return 0
        upper, _ = price_limits(float(row.preclose), bool(row.isST), date)
        if row.open >= upper - 1e-8:
            self.reject(date, "BUY", "open_at_upper_limit")
            return 0
        capacity = int(float(row.volume) * DAILY_VOLUME_LIMIT / 100) * 100
        quantity = min(int(requested // 100) * 100, capacity)
        if quantity < 100:
            self.reject(date, "BUY", "below_lot_or_volume_capacity")
            return 0
        price = round_cent(min(float(row.high), upper, float(row.open) * (1 + ONE_SIDE_SLIPPAGE)))
        while quantity >= 100:
            value = round_cent(quantity * price)
            commission = round_cent(max(MIN_COMMISSION, value * COMMISSION_RATE))
            transfer = round_cent(value * transfer_rate(date))
            if value + commission + transfer <= self.cash + 1e-8:
                break
            quantity -= 100
        if quantity < 100:
            self.reject(date, "BUY", "insufficient_cash_after_fees")
            return 0
        value = round_cent(quantity * price)
        commission = round_cent(max(MIN_COMMISSION, value * COMMISSION_RATE))
        transfer = round_cent(value * transfer_rate(date))
        self.cash -= value + commission + transfer
        self.lots.append(Lot(quantity, date))
        self.trades.append({"date": str(date.date()), "side": "BUY", "quantity": quantity,
                            "price": price, "value": value, "commission": commission,
                            "transfer_fee": transfer, "stamp_tax": 0.0,
                            "dividend_tax": 0.0})
        return quantity

    def sell(self, date: pd.Timestamp, requested: int, row: pd.Series) -> int:
        available = self.available(date)
        if available <= 0:
            self.reject(date, "SELL", "t_plus_one_locked")
            return 0
        if int(row.tradestatus) != 1 or row.volume <= 0:
            self.reject(date, "SELL", "suspended_or_no_volume")
            return 0
        _, lower = price_limits(float(row.preclose), bool(row.isST), date)
        if row.open <= lower + 1e-8:
            self.reject(date, "SELL", "open_at_lower_limit")
            return 0
        capacity = int(float(row.volume) * DAILY_VOLUME_LIMIT / 100) * 100
        quantity = min(int(requested), available, capacity)
        if quantity <= 0:
            self.reject(date, "SELL", "volume_capacity")
            return 0
        price = round_cent(max(float(row.low), lower, float(row.open) * (1 - ONE_SIDE_SLIPPAGE)))
        value = round_cent(quantity * price)
        commission = round_cent(max(MIN_COMMISSION, value * COMMISSION_RATE))
        transfer = round_cent(value * transfer_rate(date))
        stamp = round_cent(value * stamp_rate(date))
        remaining = quantity
        dividend_tax = 0.0
        for lot in self.lots:
            if lot.buy_date >= date or remaining == 0:
                continue
            sold = min(remaining, lot.quantity)
            remaining -= sold
            lot.quantity -= sold
            if date <= lot.buy_date + pd.DateOffset(months=1):
                rate = 0.20
            elif date <= lot.buy_date + pd.DateOffset(years=1):
                rate = 0.10
            else:
                rate = 0.0
            dividend_tax += sold * lot.dividend_basis * rate
        if remaining:
            raise RuntimeError("available-share accounting failed")
        dividend_tax = round_cent(dividend_tax)
        self.lots = [x for x in self.lots if x.quantity > 0]
        self.cash += value - commission - transfer - stamp - dividend_tax
        self.trades.append({"date": str(date.date()), "side": "SELL", "quantity": quantity,
                            "price": price, "value": value, "commission": commission,
                            "transfer_fee": transfer, "stamp_tax": stamp,
                            "dividend_tax": dividend_tax})
        return quantity


def load_data(project_root: Path) -> pd.DataFrame:
    base = project_root / "sh_sz_market_research" / "data_pipeline" / "data"
    raw_path = base / "raw" / "SH" / f"{SYMBOL}.parquet"
    qfq_path = base / "qfq" / "SH" / f"{SYMBOL}.parquet"
    if not raw_path.exists() or not qfq_path.exists():
        raise FileNotFoundError("Run restore_data.ps1 first or pass --project-root")
    raw = pd.read_parquet(raw_path).copy()
    qfq_columns = ["date"] + FACTOR_FIELDS
    qfq = pd.read_parquet(qfq_path, columns=qfq_columns).rename(
        columns={name: "qfq_" + name for name in FACTOR_FIELDS})
    raw["date"] = pd.to_datetime(raw.date)
    qfq["date"] = pd.to_datetime(qfq.date)
    data = raw.merge(qfq, on="date", how="inner", validate="one_to_one").sort_values("date")
    numeric = ["open", "high", "low", "close", "preclose", "volume", "tradestatus", "isST"]
    numeric += ["qfq_" + name for name in FACTOR_FIELDS]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    if data.date.duplicated().any() or data[numeric].isna().any().any():
        raise ValueError("invalid or duplicate market data")
    return data.set_index("date")


def load_actions(path: Path) -> dict[pd.Timestamp, dict]:
    frame = pd.read_csv(path)
    frame["operate_date"] = pd.to_datetime(frame.operate_date)
    frame["pay_date"] = pd.to_datetime(frame.pay_date)
    if (frame.stock_per_share.astype(float) != 0).any():
        raise ValueError("stock dividends are not supported by this minimal single-stock example")
    return {r.operate_date: {"pay_date": r.pay_date, "cash": float(r.cash_per_share)}
            for r in frame.itertuples(index=False)}


def run(project_root: Path, start: str, end: str, output: Path) -> dict:
    data = load_data(project_root)
    actions = load_actions(Path(__file__).with_name("corporate_actions_600000.csv"))
    start_date, end_date = pd.Timestamp(start), pd.Timestamp(end)
    selected = data.loc[(data.index >= start_date) & (data.index <= end_date)]
    if selected.empty or data.index.get_loc(selected.index[0]) < FACTOR_LOOKBACK:
        raise ValueError("date range has no data or insufficient pre-start history")
    account = Account()
    desired_long = False
    curve = []
    for date, row in selected.iterrows():
        account.settle_cash(date)
        action = actions.get(date)
        if action:
            account.dividend(date, action["pay_date"], action["cash"])
        loc = data.index.get_loc(date)
        factor_history = data.iloc[:loc][["qfq_" + name for name in FACTOR_FIELDS]].copy()
        factor_history.columns = FACTOR_FIELDS
        desired_long = bool(factor_decision(factor_history, desired_long))
        opening_equity = account.cash + account.quantity * float(row.open) + sum(x[1] for x in account.receivables)
        if desired_long and account.quantity == 0:
            estimated = float(row.open) * (1 + ONE_SIDE_SLIPPAGE)
            target = int(opening_equity * TARGET_EXPOSURE / estimated / 100) * 100
            account.buy(date, target, row)
        elif not desired_long and account.quantity > 0:
            account.sell(date, account.quantity, row)
        equity = account.cash + account.quantity * float(row.close) + sum(x[1] for x in account.receivables)
        curve.append({"date": str(date.date()), "equity": round_cent(equity),
                      "cash": round_cent(account.cash), "shares": account.quantity,
                      "close": float(row.close), "desired_long": desired_long})
    daily = pd.DataFrame(curve)
    nav = daily.equity.to_numpy(float)
    ret = pd.Series(nav).pct_change().dropna()
    peak = np.maximum.accumulate(np.r_[INITIAL_CASH, nav])[1:]
    years = max((pd.Timestamp(daily.date.iloc[-1]) - pd.Timestamp(daily.date.iloc[0])).days / 365.25, 1 / 365.25)
    summary = {
        "symbol": SYMBOL, "factor": FACTOR_NAME,
        "start": daily.date.iloc[0], "end": daily.date.iloc[-1],
        "initial_cash": INITIAL_CASH, "final_equity": round_cent(nav[-1]),
        "total_return": float(nav[-1] / INITIAL_CASH - 1),
        "cagr": float((nav[-1] / INITIAL_CASH) ** (1 / years) - 1),
        "max_drawdown": float(np.min(nav / peak - 1)),
        "annual_volatility": float(ret.std(ddof=1) * np.sqrt(252)) if len(ret) > 1 else 0.0,
        "sharpe_zero_rf": float(ret.mean() / ret.std(ddof=1) * np.sqrt(252)) if len(ret) > 1 and ret.std(ddof=1) > 0 else 0.0,
        "trades": len(account.trades), "rejected_attempts": len(account.rejections),
        "ending_cash": round_cent(account.cash), "ending_shares": account.quantity,
    }
    output.mkdir(parents=True, exist_ok=True)
    daily.to_csv(output / "daily_equity.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(account.trades).to_csv(output / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(account.rejections).to_csv(output / "rejections.csv", index=False, encoding="utf-8-sig")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--start", default="2020-01-02")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("output"))
    args = parser.parse_args()
    print(json.dumps(run(args.project_root.resolve(), args.start, args.end, args.output.resolve()),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
