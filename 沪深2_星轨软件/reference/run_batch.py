from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[2]
PROTOCOL_PATH = PROJECT / "protocol" / "PROTOCOL.json"
QFQ_ROOT = ROOT / "sh_sz_market_research" / "data_pipeline" / "data" / "qfq"
RESULTS = PROJECT / "results" / "batch_001"
CACHE = PROJECT / "cache"
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
FEATURE_START = pd.Timestamp("2018-01-01")
EVAL_START = pd.Timestamp("2020-01-01")
# A signal may wait seven calendar days to buy and then hold thirty calendar days.
LAST_SIGNAL_DATE = HARD_MAX_DATE - pd.Timedelta(days=37)
YEARS = list(range(2020, 2025))

FEATURE_COLUMNS = [
    "vol60",
    "overnight20",
    "intraday20",
    "turn20",
    "mom60",
    "mom20",
    "vol20",
    "ret5",
    "mom120",
    "close_to_high60",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_protocol() -> dict:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if protocol["data"]["hard_max_date"] != "2024-12-31":
        raise RuntimeError("Protocol date boundary changed")
    if protocol["candidate_count"] != 54:
        raise RuntimeError("Protocol candidate count changed")
    return protocol


def numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def build_feature_panel(force: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE / "feature_panel_pre2025.parquet"
    if cache_path.exists() and not force:
        panel = pd.read_parquet(cache_path)
        panel["date"] = pd.to_datetime(panel["date"])
        if panel["date"].max() > LAST_SIGNAL_DATE:
            raise RuntimeError("Feature cache crosses registered signal boundary")
        return panel

    rows: list[pd.DataFrame] = []
    files = sorted(QFQ_ROOT.glob("*/*.parquet"))
    if not files:
        raise FileNotFoundError(QFQ_ROOT)
    required = [
        "date", "open", "high", "low", "close", "preclose", "volume",
        "amount", "turn", "tradestatus", "isST", "symbol",
    ]
    for i, path in enumerate(files, 1):
        d = pd.read_parquet(path, columns=required)
        d["date"] = pd.to_datetime(d["date"])
        d = d[(d["date"] >= FEATURE_START) & (d["date"] <= HARD_MAX_DATE)].copy()
        if len(d) < 120:
            continue
        d = d.sort_values("date").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "preclose", "volume", "amount", "turn"]:
            d[col] = numeric(d[col])
        ret1 = d["close"].pct_change(fill_method=None)
        overnight = d["open"] / d["preclose"] - 1.0
        intraday = d["close"] / d["open"] - 1.0
        tr = pd.concat(
            [
                d["high"] - d["low"],
                (d["high"] - d["preclose"]).abs(),
                (d["low"] - d["preclose"]).abs(),
            ],
            axis=1,
        ).max(axis=1)
        d["obs"] = np.arange(1, len(d) + 1)
        d["vol60"] = ret1.rolling(60, min_periods=60).std(ddof=0)
        d["overnight20"] = overnight.rolling(20, min_periods=20).mean()
        d["intraday20"] = intraday.rolling(20, min_periods=20).mean()
        d["turn20"] = d["turn"].rolling(20, min_periods=20).mean()
        d["mom60"] = d["close"] / d["close"].shift(60) - 1.0
        d["mom20"] = d["close"] / d["close"].shift(20) - 1.0
        d["vol20"] = ret1.rolling(20, min_periods=20).std(ddof=0)
        d["ret5"] = d["close"] / d["close"].shift(5) - 1.0
        d["mom120"] = d["close"] / d["close"].shift(120) - 1.0
        d["close_to_high60"] = d["close"] / d["close"].rolling(60, min_periods=60).max() - 1.0
        d["atr_pct"] = (tr.rolling(14, min_periods=14).mean() / d["close"]).clip(0.015, 0.05)
        d["amount_med20"] = d["amount"].rolling(20, min_periods=20).median()
        st = d["isST"].astype(str).str.strip().str.lower()
        trade = d["tradestatus"].astype(str).str.strip()
        mask = (
            (d["date"] >= EVAL_START)
            & (d["date"] <= LAST_SIGNAL_DATE)
            & (d["obs"] >= 120)
            & (d["close"].between(2.0, 80.0))
            & (d["amount"] >= 20_000_000)
            & (d["amount_med20"] >= 30_000_000)
            & (~st.isin(["1", "true", "yes", "st"]))
            & (trade.isin(["1", "1.0", "true", "True"]))
        )
        keep = ["date", "symbol", "close", "atr_pct"] + FEATURE_COLUMNS
        out = d.loc[mask, keep].dropna().copy()
        if not out.empty:
            out["symbol"] = out["symbol"].astype(str)
            rows.append(out)
        if i % 500 == 0:
            print(f"feature files {i}/{len(files)}", flush=True)
    if not rows:
        raise RuntimeError("No eligible feature rows")
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)
    panel.to_parquet(cache_path, index=False)
    return panel


def build_signals(panel: pd.DataFrame) -> pd.DataFrame:
    rank = panel.groupby("date", sort=False)[FEATURE_COLUMNS].rank(pct=True, method="average") - 0.5
    panel = panel[["date", "symbol", "close", "atr_pct"]].copy()
    panel["baseline_lowvol"] = (
        -0.35 * rank["vol60"]
        - 0.20 * rank["overnight20"]
        + 0.25 * rank["intraday20"]
        - 0.20 * rank["turn20"]
    )
    panel["trend_pullback"] = (
        0.40 * rank["mom60"]
        + 0.25 * rank["mom20"]
        - 0.20 * rank["vol20"]
        - 0.15 * rank["ret5"]
    )
    panel["stable_breakout"] = (
        0.35 * rank["mom120"]
        + 0.25 * rank["close_to_high60"]
        + 0.20 * rank["mom20"]
        - 0.20 * rank["vol60"]
    )
    chunks = []
    for name in ["baseline_lowvol", "trend_pullback", "stable_breakout"]:
        s = panel[["date", "symbol", "close", "atr_pct", name]].rename(columns={name: "score"})
        s = s.sort_values(["date", "score", "symbol"], ascending=[True, False, True])
        s = s.groupby("date", sort=False).head(2).copy()
        s["factor"] = name
        chunks.append(s)
    signals = pd.concat(chunks, ignore_index=True)
    signals = signals.sort_values(["date", "factor", "score", "symbol"], ascending=[True, True, False, True])
    RESULTS.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(RESULTS / "signals_all_factors.parquet", index=False)
    return signals


def load_execution_bars(symbols: set[str], force: bool = False) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE / "execution_bars_pre2025.parquet"
    if cache_path.exists() and not force:
        all_bars = pd.read_parquet(cache_path)
        all_bars["date"] = pd.to_datetime(all_bars["date"])
        cached_symbols = set(all_bars["symbol"].astype(str).unique())
        if not symbols.issubset(cached_symbols):
            force = True
    if force or not cache_path.exists():
        rows = []
        columns = ["date", "open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus", "symbol"]
        for i, symbol in enumerate(sorted(symbols), 1):
            path = QFQ_ROOT / symbol[-2:] / f"{symbol}.parquet"
            if not path.exists():
                continue
            d = pd.read_parquet(path, columns=columns)
            d["date"] = pd.to_datetime(d["date"])
            d = d[(d["date"] >= EVAL_START) & (d["date"] <= HARD_MAX_DATE)].copy()
            for col in ["open", "high", "low", "close", "preclose", "volume", "amount"]:
                d[col] = numeric(d[col])
            rows.append(d)
            if i % 500 == 0:
                print(f"execution files {i}/{len(symbols)}", flush=True)
        all_bars = pd.concat(rows, ignore_index=True).sort_values(["symbol", "date"])
        all_bars.to_parquet(cache_path, index=False)
    if all_bars["date"].max() > HARD_MAX_DATE:
        raise RuntimeError("Execution cache crosses 2024 boundary")
    by_symbol = {s: d.set_index("date").sort_index() for s, d in all_bars.groupby("symbol", sort=False)}
    calendar = sorted(all_bars["date"].drop_duplicates().tolist())
    return by_symbol, calendar


def is_trading(bar: pd.Series | None) -> bool:
    if bar is None:
        return False
    return str(bar["tradestatus"]).strip() in {"1", "1.0", "True", "true"} and float(bar["volume"]) > 0


def is_one_price_limit_down(bar: pd.Series) -> bool:
    pre = float(bar["preclose"])
    if pre <= 0:
        return False
    one_price = abs(float(bar["high"]) - float(bar["low"])) < 1e-9
    return one_price and float(bar["close"]) / pre - 1.0 <= -0.095


def commission(value: float, rate: float, minimum: float) -> float:
    return max(minimum, value * rate)


@dataclass
class Pending:
    symbol: str
    signal_date: pd.Timestamp
    expiry_date: pd.Timestamp
    target: float
    atr_pct: float
    score: float
    budget: float


@dataclass
class Holding:
    symbol: str
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    deadline: pd.Timestamp
    expiry_session: pd.Timestamp
    shares: int
    entry_price: float
    entry_cost: float
    entry_notional: float
    atr_pct: float
    take_price: float
    stop_price: float
    entry_year: int
    locked_until: pd.Timestamp = pd.Timestamp.min
    dividends: float = 0.0
    frozen: bool = False
    frozen_value: float = 0.0


def get_bar(by_symbol: dict[str, pd.DataFrame], symbol: str, date: pd.Timestamp) -> pd.Series | None:
    d = by_symbol.get(symbol)
    if d is None or date not in d.index:
        return None
    row = d.loc[date]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[-1]
    return row


def last_session_on_or_before(calendar: list[pd.Timestamp], deadline: pd.Timestamp) -> pd.Timestamp:
    i = bisect_right(calendar, deadline) - 1
    if i < 0:
        raise RuntimeError("No session before deadline")
    return calendar[i]


def mark_equity(cash: float, deferred: float, holdings: list[Holding], by_symbol: dict[str, pd.DataFrame], date: pd.Timestamp, receivable: float = 0.0) -> float:
    value = cash + deferred + receivable
    for h in holdings:
        if h.frozen:
            value += h.frozen_value
            continue
        d = by_symbol[h.symbol]
        idx = d.index.searchsorted(date, side="right") - 1
        if idx >= 0:
            value += h.shares * float(d.iloc[idx]["close"])
    return value


def simulate(
    signals: pd.DataFrame,
    by_symbol: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    factor: str,
    entry_offset: float,
    hold_days: int,
    exit_name: str,
    take_mult: float,
    stop_mult: float,
    keep_trades: bool = False,
    actions: dict[tuple[pd.Timestamp, str], list[dict]] | None = None,
    known_action_keys: set[str] | None = None,
    coverage_sink: set[str] | None = None,
    delist_dates: dict[str, pd.Timestamp] | None = None,
    slots: int = 10,
    equity_curve_sink: list[dict] | None = None,
) -> tuple[dict, pd.DataFrame]:
    initial = 100_000.0
    if slots <= 0:
        raise ValueError("slots must be positive")
    comm_rate = 0.0003
    comm_min = 5.0
    stamp = 0.001
    slip = 0.002
    cash = initial
    deferred_cash = 0.0
    deferred_release: pd.Timestamp | None = None
    pending: list[Pending] = []
    holdings: list[Holding] = []
    trades: list[dict] = []
    rejected_capacity = 0
    expired_entries = 0
    skipped_no_free_slot = 0
    skipped_duplicate_symbol = 0
    pending_orders_created = 0
    filled_orders = 0
    cash_limited_orders = 0
    below_100_share_orders = 0
    occupied_slot_sum = 0
    occupied_slot_observations = 0
    peak_occupied_slots = 0
    blocked_exits = 0
    blocked_exit_reason_counts: dict[str, int] = {}
    action_events = 0
    action_source_counts: dict[str, int] = {}
    delisting_freezes = 0
    receivables: list[tuple[pd.Timestamp, float]] = []
    actions = actions or {}
    delist_dates = delist_dates or {}

    factor_signals = signals[signals["factor"] == factor].copy()
    signal_map = {d: g.to_dict("records") for d, g in factor_signals.groupby("date", sort=False)}
    year_end_equity: dict[int, float] = {}

    for cal_i, date in enumerate(calendar):
        if date < EVAL_START or date > HARD_MAX_DATE:
            continue
        if deferred_release is not None and date >= deferred_release:
            cash += deferred_cash
            deferred_cash = 0.0
            deferred_release = None
        due = [x for x in receivables if x[0] <= date]
        if due:
            cash += sum(x[1] for x in due)
            receivables = [x for x in receivables if x[0] > date]

        # Apply known ex-date events to overnight holders before today's exits.
        for h in holdings:
            key = f"{h.symbol}/{date.year}"
            if known_action_keys is not None and key not in known_action_keys and coverage_sink is not None:
                coverage_sink.add(key)
            out_date = delist_dates.get(h.symbol)
            if out_date is not None and date >= out_date and not h.frozen:
                h.frozen = True
                h.frozen_value = 0.8 * h.entry_notional
                delisting_freezes += 1
            if h.frozen or date <= h.entry_date:
                continue
            for event in actions.get((date, h.symbol), []):
                old_shares = h.shares
                dividend = float(event.get("cash", 0.0))
                stock = float(event.get("stock", 0.0))
                taxable_stock = float(event.get("taxable_stock", 0.0))
                factor_value = 1.0 + stock
                new_shares = old_shares * factor_value
                if abs(new_shares - round(new_shares)) > 1e-8:
                    raise RuntimeError(f"Fractional corporate-action shares: {h.symbol} {date} {new_shares}")
                tax = old_shares * taxable_stock * 0.20
                net_cash = old_shares * dividend - tax
                pay = pd.Timestamp(event.get("pay", date)).normalize()
                release = pd.Timestamp(event.get("release", date)).normalize()
                receivables.append((pay, net_cash))
                h.dividends += net_cash
                h.shares = int(round(new_shares))
                h.take_price /= factor_value
                h.stop_price /= factor_value
                if factor_value > 1.0:
                    h.locked_until = max(h.locked_until, release)
                action_events += 1
                source = str(event.get("source", "baostock_cache"))
                action_source_counts[source] = action_source_counts.get(source, 0) + 1

        # Exit decisions occur before buy fills; proceeds become reusable next session.
        survivors: list[Holding] = []
        for h in holdings:
            if h.frozen:
                survivors.append(h)
                continue
            if date <= h.entry_date:
                survivors.append(h)
                continue
            bar = get_bar(by_symbol, h.symbol, date)
            if not is_trading(bar):
                survivors.append(h)
                continue
            assert bar is not None
            if date < h.locked_until:
                survivors.append(h)
                continue
            low, high, opn, close = map(float, [bar["low"], bar["high"], bar["open"], bar["close"]])
            reason = None
            base = None
            stop_hit = low <= h.stop_price
            take_hit = high >= h.take_price
            if stop_hit:
                reason = "stop"
                base = min(opn, h.stop_price)
            elif take_hit:
                reason = "take"
                base = max(opn, h.take_price)
            elif date >= h.expiry_session:
                reason = "expiry"
                base = close
            if reason is None:
                survivors.append(h)
                continue
            if is_one_price_limit_down(bar):
                blocked_exits += 1
                blocked_exit_reason_counts[reason] = blocked_exit_reason_counts.get(reason, 0) + 1
                survivors.append(h)
                continue
            sell_price = max(0.01, base * (1.0 - slip))
            gross = h.shares * sell_price
            fees = commission(gross, comm_rate, comm_min) + gross * stamp
            proceeds = gross - fees
            deferred_cash += proceeds
            if cal_i + 1 < len(calendar):
                release = calendar[cal_i + 1]
                deferred_release = release if deferred_release is None else min(deferred_release, release)
            pnl = proceeds + h.dividends - h.entry_cost
            trades.append({
                "factor": factor,
                "entry_offset": entry_offset,
                "hold_days": hold_days,
                "exit_set": exit_name,
                "symbol": h.symbol,
                "signal_date": h.signal_date,
                "entry_date": h.entry_date,
                "exit_date": date,
                "shares": h.shares,
                "entry_price": h.entry_price,
                "exit_price": sell_price,
                "entry_notional": h.entry_notional,
                "entry_cost": h.entry_cost,
                "entry_fee": h.entry_cost - h.entry_notional,
                "exit_gross": gross,
                "exit_fee_and_tax": fees,
                "exit_proceeds": proceeds,
                "pnl": pnl,
                "gross_trade_pnl_before_fees": gross + h.dividends - h.entry_notional,
                "return": pnl / h.entry_cost,
                "reason": reason,
                "entry_year": h.entry_year,
            })
        holdings = survivors

        # Existing conditional buys monitor through their seventh calendar day.
        still_pending: list[Pending] = []
        occupied_symbols = {h.symbol for h in holdings}
        for p in pending:
            if date > p.expiry_date:
                expired_entries += 1
                continue
            if date <= p.signal_date:
                still_pending.append(p)
                continue
            if p.symbol in occupied_symbols:
                continue
            bar = get_bar(by_symbol, p.symbol, date)
            if not is_trading(bar) or bar is None or float(bar["low"]) > p.target:
                still_pending.append(p)
                continue
            base = min(float(bar["open"]), p.target)
            buy_price = min(float(bar["high"]), base * (1.0 + slip))
            affordable = min(p.budget, cash)
            if cash + 1e-9 < p.budget:
                cash_limited_orders += 1
            shares = int(affordable // (buy_price * 100)) * 100
            capacity = int((float(bar["volume"]) * 0.02) // 100) * 100
            if shares > capacity:
                shares = capacity
                rejected_capacity += 1
            if shares < 100:
                below_100_share_orders += 1
                continue
            gross = shares * buy_price
            fee = commission(gross, comm_rate, comm_min)
            cost = gross + fee
            while shares >= 100 and cost > cash + 1e-9:
                shares -= 100
                gross = shares * buy_price
                fee = commission(gross, comm_rate, comm_min) if shares else 0.0
                cost = gross + fee
            if shares < 100:
                below_100_share_orders += 1
                continue
            cash -= cost
            deadline = date + pd.Timedelta(days=hold_days)
            expiry_session = last_session_on_or_before(calendar, deadline)
            atr = p.atr_pct
            holdings.append(Holding(
                symbol=p.symbol,
                signal_date=p.signal_date,
                entry_date=date,
                deadline=deadline,
                expiry_session=expiry_session,
                shares=shares,
                entry_price=buy_price,
                entry_cost=cost,
                entry_notional=gross,
                atr_pct=atr,
                take_price=buy_price * (1.0 + take_mult * atr),
                stop_price=buy_price * (1.0 - stop_mult * atr),
                entry_year=date.year,
            ))
            filled_orders += 1
            occupied_symbols.add(p.symbol)
        pending = still_pending

        # New orders are created after this close and cannot fill today.
        occupied_symbols = {x.symbol for x in pending} | {x.symbol for x in holdings}
        free_slots = slots - len(pending) - len(holdings)
        for row in signal_map.get(date, []):
            symbol = str(row["symbol"])
            if symbol in occupied_symbols:
                skipped_duplicate_symbol += 1
                continue
            if free_slots <= 0:
                skipped_no_free_slot += 1
                continue
            equity = mark_equity(cash, deferred_cash, holdings, by_symbol, date, sum(x[1] for x in receivables))
            budget = max(0.0, equity / slots)
            pending.append(Pending(
                symbol=symbol,
                signal_date=date,
                expiry_date=date + pd.Timedelta(days=7),
                target=float(row["close"]) * (1.0 - entry_offset * float(row["atr_pct"])),
                atr_pct=float(row["atr_pct"]),
                score=float(row["score"]),
                budget=budget,
            ))
            pending_orders_created += 1
            occupied_symbols.add(symbol)
            free_slots -= 1

        occupied_now = len(pending) + len(holdings)
        occupied_slot_sum += occupied_now
        occupied_slot_observations += 1
        peak_occupied_slots = max(peak_occupied_slots, occupied_now)

        if date.year in YEARS:
            year_last = calendar[bisect_right(calendar, pd.Timestamp(f"{date.year}-12-31")) - 1]
            if date == year_last:
                year_end_equity[date.year] = mark_equity(cash, deferred_cash, holdings, by_symbol, date, sum(x[1] for x in receivables))

        if equity_curve_sink is not None:
            equity_curve_sink.append({
                "date": date,
                "equity": mark_equity(cash, deferred_cash, holdings, by_symbol, date, sum(x[1] for x in receivables)),
            })

    final_equity = mark_equity(cash, deferred_cash, holdings, by_symbol, HARD_MAX_DATE, sum(x[1] for x in receivables))
    annual_returns = {}
    prev = initial
    for year in YEARS:
        value = year_end_equity.get(year, prev)
        annual_returns[year] = value / prev - 1.0
        prev = value
    t = pd.DataFrame(trades)
    total_entry_fees = float(t["entry_fee"].sum()) if not t.empty else 0.0
    total_exit_fees_and_tax = float(t["exit_fee_and_tax"].sum()) if not t.empty else 0.0
    gross_trade_pnl_before_fees = float(t["gross_trade_pnl_before_fees"].sum()) if not t.empty else 0.0
    net_trade_pnl_after_fees = float(t["pnl"].sum()) if not t.empty else 0.0
    counts = {y: int((t["entry_year"] == y).sum()) if not t.empty else 0 for y in YEARS}
    eligible = all(counts[y] >= 20 for y in YEARS)
    arr = np.array([annual_returns[y] for y in YEARS], dtype=float)
    count_arr = np.array([counts[y] for y in YEARS], dtype=float)
    count_cv = float(count_arr.std(ddof=0) / count_arr.mean()) if count_arr.mean() else math.inf
    cagr = (final_equity / initial) ** (1.0 / 5.0) - 1.0 if final_equity > 0 else -1.0
    result = {
        "candidate": f"{factor}__entry{entry_offset:.2f}atr__{exit_name}__{hold_days}cal",
        "factor": factor,
        "entry_offset_atr": entry_offset,
        "exit_set": exit_name,
        "take_atr": take_mult,
        "stop_atr": stop_mult,
        "hold_calendar_days": hold_days,
        "eligible": eligible,
        "cagr": cagr,
        "final_equity": final_equity,
        "worst_annual_return": float(arr.min()),
        "profitable_years": int((arr > 0).sum()),
        "annual_return_std": float(arr.std(ddof=0)),
        "trade_count_cv": count_cv,
        "completed_trades": int(len(t)),
        "total_entry_fees": total_entry_fees,
        "total_exit_fees_and_tax": total_exit_fees_and_tax,
        "total_fees": total_entry_fees + total_exit_fees_and_tax,
        "gross_trade_pnl_before_fees": gross_trade_pnl_before_fees,
        "net_trade_pnl_after_fees": net_trade_pnl_after_fees,
        "open_positions_at_end": len(holdings),
        "pending_orders_at_end": len(pending),
        "expired_entry_orders": expired_entries,
        "capacity_limited_orders": rejected_capacity,
        "slots": slots,
        "total_signals": int(len(factor_signals)),
        "skipped_no_free_slot": skipped_no_free_slot,
        "skipped_duplicate_symbol": skipped_duplicate_symbol,
        "pending_orders_created": pending_orders_created,
        "filled_orders": filled_orders,
        "cash_limited_orders": cash_limited_orders,
        "below_100_share_orders": below_100_share_orders,
        "average_occupied_slots_eod": float(occupied_slot_sum / occupied_slot_observations) if occupied_slot_observations else 0.0,
        "peak_occupied_slots_eod": peak_occupied_slots,
        "order_creation_rate": float(pending_orders_created / len(factor_signals)) if len(factor_signals) else 0.0,
        "fill_per_signal_rate": float(filled_orders / len(factor_signals)) if len(factor_signals) else 0.0,
        "fill_per_created_order_rate": float(filled_orders / pending_orders_created) if pending_orders_created else 0.0,
        "blocked_exit_attempts": blocked_exits,
        "blocked_exit_reason_counts": blocked_exit_reason_counts,
        "corporate_action_events": action_events,
        "corporate_action_source_counts": action_source_counts,
        "delisting_freezes": delisting_freezes,
        "unpaid_receivables": float(sum(x[1] for x in receivables)),
    }
    for year in YEARS:
        result[f"return_{year}"] = annual_returns[year]
        result[f"trades_{year}"] = counts[year]
    return result, t if keep_trades else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-features", action="store_true")
    parser.add_argument("--force-bars", action="store_true")
    args = parser.parse_args()
    protocol = read_protocol()
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel = build_feature_panel(force=args.force_features)
    if panel["date"].max() > LAST_SIGNAL_DATE:
        raise RuntimeError("Panel violates outcome boundary")
    signals = build_signals(panel)
    del panel
    gc.collect()
    by_symbol, calendar = load_execution_bars(set(signals["symbol"]), force=args.force_bars)
    formulas = [x["name"] for x in protocol["factor_formulas"]]
    exit_sets = protocol["exit"]["atr_take_stop_pairs"]
    results = []
    total = 54
    n = 0
    for factor in formulas:
        for entry_offset in protocol["entry"]["entry_atr_offsets"]:
            for hold_days in protocol["exit"]["holding_calendar_days"]:
                for exit_set in exit_sets:
                    n += 1
                    row, _ = simulate(
                        signals, by_symbol, calendar, factor, float(entry_offset), int(hold_days),
                        exit_set["name"], float(exit_set["take"]), float(exit_set["stop"]),
                    )
                    results.append(row)
                    print(f"candidate {n}/{total}: {row['candidate']} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)
    grid = pd.DataFrame(results)
    grid = grid.sort_values(
        ["eligible", "cagr", "worst_annual_return", "profitable_years", "annual_return_std", "trade_count_cv", "candidate"],
        ascending=[False, False, False, False, True, True, True],
    ).reset_index(drop=True)
    grid.to_csv(RESULTS / "grid.csv", index=False, encoding="utf-8-sig")
    eligible = grid[grid["eligible"]]
    if eligible.empty:
        champion = grid.iloc[0]
        selection_status = "no_eligible_candidate"
    else:
        champion = eligible.iloc[0]
        selection_status = "unique_champion_frozen_pending_full_audit"
    champion_params = champion.to_dict()
    _, trades = simulate(
        signals,
        by_symbol,
        calendar,
        champion_params["factor"],
        float(champion_params["entry_offset_atr"]),
        int(champion_params["hold_calendar_days"]),
        champion_params["exit_set"],
        float(champion_params["take_atr"]),
        float(champion_params["stop_atr"]),
        keep_trades=True,
    )
    trades.to_csv(RESULTS / "champion_trades_screening.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(PROTOCOL_PATH),
        "runner_sha256": sha256(Path(__file__)),
        "selection_status": selection_status,
        "candidate_count": int(len(grid)),
        "eligible_candidate_count": int(grid["eligible"].sum()),
        "champion": champion_params,
        "screening_limitations": [
            "Forward-adjusted bars are used for finite-batch screening.",
            "Historical level-2 depth is unavailable; orders at or below 2% of daily volume are assumed fully filled as authorized.",
            "The frozen champion requires a separate raw-price corporate-action and execution audit before any registration decision.",
        ],
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
