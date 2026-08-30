"""Local approximation of the SuperMind *daily-frequency* baseline30 strategy.

SuperMind daily mode calls handle_bar once around 09:31.  Consequently exits
are evaluated from the opening/first-minute price, not from the daily high/low.
Signals are calculated after the preceding completed daily bar and are eligible
for execution on the next trading day.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features


ROOT = Path(__file__).resolve().parent
START = pd.Timestamp(os.environ.get("BACKTEST_START", "2020-01-01"))
END = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-06-30"))
INITIAL_CASH = float(os.environ.get("BACKTEST_CASH", "100000"))
OUTPUT_FOLDER = os.environ.get("BACKTEST_OUTPUT", "supermind_daily_parity")
THRESHOLD = 0.689688
TOP_PER_DAY = 8
MAX_POSITIONS = 14
POSITION_FRACTION = 0.10
STOP_LOSS = 0.07
TAKE_HALF = 0.24
TAKE_ALL = 0.34
MAX_HOLDING_DAYS = 30
# In this exported daily run SuperMind never called on_order (confirmed by the
# complete log). Consequently position_state is created from the first holding
# but is never updated on fills or removed on a full exit. Re-entries therefore
# reuse the symbol's stale first entry price and half flag.
EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK = True
# The exported trade CSV omits the platform's separate corporate-action ledger.
# Keep this off for displayed-statistic parity; enable only for a sensitivity
# run after cash-dividend/bonus-share records are exported independently.
EMULATE_SUPERMIND_CORPORATE_ACTIONS = False
ENFORCE_STAR_PARTIAL_MINIMUM = True
# V2 neutral PriceSlippage(0.004) is approximately 0.20% adverse per side.
SLIPPAGE_PER_SIDE = 0.002
COMMISSION = 0.0003
MIN_COMMISSION = 5.0
TRANSFER_FEE = 0.00001
MIN_STAR_BUY = 200


def fee(amount: float) -> float:
    return max(MIN_COMMISSION, amount * COMMISSION) + amount * TRANSFER_FEE


def stamp_tax(amount: float, date: pd.Timestamp) -> float:
    return amount * (0.0005 if date >= pd.Timestamp("2023-08-28") else 0.001)


def limit_price(previous_close: float, multiplier: float) -> float:
    # Exchange limit prices are rounded to the nearest cent.
    return np.floor(previous_close * multiplier * 100.0 + 0.5) / 100.0


def run() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs/event_recognition_v2/event_model.joblib")
    ds = features(qfq, cfg)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES).copy()
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    ds = ds[ds.probability >= THRESHOLD]

    raw = raw[(raw.date >= START) & (raw.date <= END)].copy()
    raw_by_date = {date: day.set_index("symbol") for date, day in raw.groupby("date")}
    dates = sorted(raw_by_date)
    if not dates:
        raise RuntimeError("No raw data in requested period")

    # A signal dated T is consumed at the next available market date T+1.
    candidate_by_signal_date = {
        date: group.nlargest(TOP_PER_DAY, "probability")[["symbol", "probability"]]
        for date, group in ds.groupby("date")
    }
    previous_market_date = None
    cash = INITIAL_CASH
    positions: dict[str, dict] = {}
    trades: list[dict] = []
    fills: list[dict] = []
    curve: list[dict] = []
    rejects = {"limit_up": 0, "limit_down": 0, "suspended": 0,
               "cash_or_200": 0, "max_positions": 0}
    peak_positions = 0
    strategy_state: dict[str, dict] = {}
    previous_raw_close: dict[str, float] = {}
    corporate_actions: list[dict] = []

    for date in dates:
        day = raw_by_date[date]
        # SuperMind automatically adjusts held share quantity and cost basis on
        # ex-right dates. BaoStock's raw preclose contains the total-return
        # adjustment; infer common STAR bonus-share ratios to reproduce it.
        for symbol, pos in list(positions.items()):
            if symbol not in day.index or symbol not in previous_raw_close:
                continue
            row = day.loc[symbol]
            preclose = float(row.preclose)
            prior_close = previous_raw_close[symbol]
            total_factor = prior_close / preclose if preclose > 0 else 1.0
            if EMULATE_SUPERMIND_CORPORATE_ACTIONS and abs(total_factor - 1.0) > 0.02:
                share_factor = round(total_factor, 1)
                if share_factor >= 1.1:
                    old_qty = pos["qty"]
                    new_qty = float(int(round(old_qty * share_factor)))
                    cash_dividend = max(0.0, prior_close - preclose * share_factor)
                    cash += old_qty * cash_dividend
                    pos["qty"] = new_qty
                    pos["entry"] = max(0.01, (pos["entry"] - cash_dividend) / share_factor)
                    corporate_actions.append({"date": date, "symbol": symbol,
                                              "old_qty": old_qty, "new_qty": new_qty,
                                              "share_factor": share_factor,
                                              "cash_dividend_per_share": cash_dividend})
        # SuperMind daily handle_bar first submits the preceding day's candidates.
        candidates = candidate_by_signal_date.get(previous_market_date, pd.DataFrame())
        if not candidates.empty:
            for signal in candidates.itertuples():
                if signal.symbol in positions:
                    continue
                if len(positions) >= MAX_POSITIONS:
                    rejects["max_positions"] += 1
                    break
                if signal.symbol not in day.index:
                    rejects["suspended"] += 1
                    continue
                row = day.loc[signal.symbol]
                if str(row.tradestatus) != "1" or row.open <= 0 or row.volume <= 0:
                    rejects["suspended"] += 1
                    continue
                upper = limit_price(float(row.preclose), 1.20)
                if float(row.open) >= upper - 0.001:
                    rejects["limit_up"] += 1
                    continue
                equity_open = cash + sum(
                    pos["qty"] * float(day.loc[symbol, "open"])
                    for symbol, pos in positions.items() if symbol in day.index
                )
                target_value = equity_open * POSITION_FRACTION
                execution_price = float(row.open) * (1.0 + SLIPPAGE_PER_SIDE)
                quantity = int(target_value / execution_price)
                if quantity < MIN_STAR_BUY:
                    rejects["cash_or_200"] += 1
                    continue
                amount = quantity * execution_price
                total_cost = amount + fee(amount)
                while quantity >= MIN_STAR_BUY and total_cost > cash:
                    quantity -= 1
                    amount = quantity * execution_price
                    total_cost = amount + fee(amount)
                if quantity < MIN_STAR_BUY:
                    rejects["cash_or_200"] += 1
                    continue
                cash -= total_cost
                if signal.symbol not in strategy_state:
                    strategy_state[signal.symbol] = {"entry": execution_price, "half": False}
                fills.append({"date": date, "symbol": signal.symbol, "side": "BUY",
                              "price": execution_price, "quantity": quantity,
                              "amount": amount, "fee": fee(amount), "stamp_tax": 0.0})
                positions[signal.symbol] = {
                    "qty": float(quantity), "entry": execution_price,
                    "entry_date": date, "holding_days": 0, "half": False,
                    "probability": float(signal.probability),
                    "realized": -total_cost, "initial_cost": total_cost,
                }
                peak_positions = max(peak_positions, len(positions))

        # One 09:31-style risk check. Daily high/low is intentionally ignored.
        for symbol, pos in list(positions.items()):
            if symbol not in day.index:
                continue
            row = day.loc[symbol]
            if pos["entry_date"] == date:
                continue  # A-share T+1
            pos["holding_days"] += 1
            if str(row.tradestatus) != "1" or row.open <= 0 or row.volume <= 0:
                continue
            lower = limit_price(float(row.preclose), 0.80)
            if float(row.open) <= lower + 0.001:
                rejects["limit_down"] += 1
                continue
            mark = float(row.open)
            state = strategy_state[symbol]
            trigger_entry = state["entry"] if EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK else pos["entry"]
            trigger_half = state["half"] if EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK else pos["half"]
            target_qty = None
            reason = None
            if mark <= trigger_entry * (1.0 - STOP_LOSS):
                target_qty, reason = 0.0, "STOP"
            elif mark >= trigger_entry * (1.0 + TAKE_ALL):
                target_qty, reason = 0.0, "TPALL"
            elif mark >= trigger_entry * (1.0 + TAKE_HALF) and not trigger_half:
                half_target = float(int(pos["qty"] / 2))
                half_sell = pos["qty"] - half_target
                # SuperMind rejects a STAR partial reduction that would create
                # a sub-200-share order/balance. Full liquidation remains legal.
                if ((not ENFORCE_STAR_PARTIAL_MINIMUM)
                        or (half_target >= MIN_STAR_BUY and half_sell >= MIN_STAR_BUY)):
                    target_qty, reason = half_target, "TPHALF"
            elif (date - pos["entry_date"]).days >= MAX_HOLDING_DAYS:
                target_qty, reason = 0.0, "TIME"
            if target_qty is None:
                continue
            sell_qty = pos["qty"] - target_qty
            if sell_qty <= 0:
                continue
            execution_price = mark * (1.0 - SLIPPAGE_PER_SIDE)
            amount = sell_qty * execution_price
            proceeds = amount - fee(amount) - stamp_tax(amount, date)
            cash += proceeds
            fills.append({"date": date, "symbol": symbol, "side": "SELL",
                          "price": execution_price, "quantity": -sell_qty,
                          "amount": -amount, "fee": fee(amount),
                          "stamp_tax": stamp_tax(amount, date), "reason": reason})
            pos["realized"] += proceeds
            pos["qty"] = target_qty
            if reason == "TPHALF":
                pos["half"] = True
                if not EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK:
                    state["half"] = True
            if pos["qty"] <= 0:
                trades.append({
                    "symbol": symbol, "entry_date": pos["entry_date"], "exit_date": date,
                    "reason": reason, "probability": pos["probability"],
                    "pnl": pos["realized"],
                    "return": pos["realized"] / pos["initial_cost"],
                    "tp_half_triggered": bool(pos["half"]),
                })
                del positions[symbol]
                if not EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK:
                    strategy_state.pop(symbol, None)

        equity = cash + sum(
            pos["qty"] * float(day.loc[symbol, "close"])
            for symbol, pos in positions.items() if symbol in day.index
        )
        curve.append({"date": date, "equity": equity, "cash": cash,
                      "positions": len(positions)})
        previous_market_date = date
        for symbol, row in day.iterrows():
            previous_raw_close[symbol] = float(row.close)

    curve_df = pd.DataFrame(curve)
    trades_df = pd.DataFrame(trades)
    years = (curve_df.date.iloc[-1] - curve_df.date.iloc[0]).days / 365.25
    total_return = curve_df.equity.iloc[-1] / INITIAL_CASH - 1.0
    drawdown = curve_df.equity / curve_df.equity.cummax() - 1.0
    summary = {
        "mode": "SuperMind daily-frequency approximation",
        "start": str(START.date()), "end": str(END.date()),
        "initial_cash": INITIAL_CASH, "final_equity": float(curve_df.equity.iloc[-1]),
        "total_return": float(total_return),
        "annualized_return": float((1.0 + total_return) ** (1.0 / years) - 1.0),
        "max_drawdown": float(drawdown.min()), "closed_trades": int(len(trades_df)),
        "win_rate": float(trades_df["return"].gt(0).mean()) if len(trades_df) else None,
        "mean_trade_return": float(trades_df["return"].mean()) if len(trades_df) else None,
        "peak_positions": int(peak_positions), "signals": int(len(ds)), **rejects,
        "missing_daily_order_callback": EMULATE_SUPERMIND_MISSING_DAILY_ORDER_CALLBACK,
        "corporate_actions": int(len(corporate_actions)),
        "corporate_action_adjustment": EMULATE_SUPERMIND_CORPORATE_ACTIONS,
        "star_partial_minimum": ENFORCE_STAR_PARTIAL_MINIMUM,
    }
    return summary, curve_df, trades_df, pd.DataFrame(fills), pd.DataFrame(corporate_actions)


def main() -> None:
    summary, curve, trades, fills, actions = run()
    out = ROOT / "outputs" / OUTPUT_FOLDER
    out.mkdir(parents=True, exist_ok=True)
    curve.to_csv(out / "equity.csv", index=False)
    trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    fills.to_csv(out / "fills.csv", index=False, encoding="utf-8-sig")
    actions.to_csv(out / "corporate_actions.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
