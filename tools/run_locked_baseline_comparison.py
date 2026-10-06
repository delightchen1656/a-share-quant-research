"""Replay the five locked baselines on one capital/date convention.

This is a local daily-bar execution approximation.  It does not replace the
frozen SuperMind entry files and it deliberately preserves each entry's own
signal, sizing, rebalance and slippage rules.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
import math
import sys
import types
import zlib
from pathlib import Path
from types import SimpleNamespace as NS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "locked_baseline_comparison_20261006"
STAR_DATA = ROOT / "evening_accumulation" / "data"
MAIN_DATA = ROOT / "sh_sz_market_research" / "data_pipeline" / "data"
INITIAL_CASH = 500_000.0
END = pd.Timestamp("2026-09-30")
PERIODS = {
    "2025_latest": pd.Timestamp("2025-01-01"),
    "2020_latest": pd.Timestamp("2020-01-01"),
}
STAR_ENTRIES = {
    "科创1-2": ROOT / "strategies/kechuang/supermind_baseline_1_2_stop_filter.py",
    "科创2-2": ROOT / "strategies/kechuang/supermind_baseline_2_2_rising_defense.py",
    "科创3-1": ROOT / "strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry.py",
}
MAIN_ENTRIES = {
    "沪深基准1": ROOT / "strategies/hushen/supermind_mainboard_baseline_1.py",
    "沪深基准2": ROOT / "strategies/hushen/supermind_mainboard_baseline_2.py",
}
COLORS = {
    "科创1-2": "#1f77b4",
    "科创2-2": "#2ca02c",
    "科创3-1": "#d62728",
    "沪深基准1": "#9467bd",
    "沪深基准2": "#ff7f0e",
}


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_file(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def platform_namespace(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [node for node in tree.body if isinstance(node, (ast.Assign, ast.FunctionDef))]
    ns = {
        "np": np,
        "pd": pd,
        "math": math,
        "base64": base64,
        "zlib": zlib,
        "json": json,
        "g": NS(),
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"), ns)
    return ns


def decode_model(encoded: str) -> dict:
    return json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))


def fast_model(model: dict) -> dict:
    result = dict(model)
    result["fast_trees"] = [
        tuple(
            np.asarray([node[key] for node in tree], dtype=dtype)
            for key, dtype in [
                ("f", np.int16), ("t", float), ("m", bool), ("l", np.int16),
                ("r", np.int16), ("leaf", bool), ("v", float),
            ]
        )
        for tree in model["trees"]
    ]
    return result


def parse_action_cache(paths: list[Path]) -> dict:
    cache = {}
    for path in paths:
        if path.exists():
            cache.update(json.loads(path.read_text(encoding="utf-8")))
    return cache


def action_map(cache: dict, star: bool) -> dict:
    result = {}

    def number(value) -> float:
        return float(value) if str(value).strip() else 0.0

    for key, rows in cache.items():
        symbol = key.split("/")[0]
        for row in rows:
            if not row.get("dividOperateDate"):
                continue
            date = pd.Timestamp(row["dividOperateDate"])
            item = {
                "cash": number(row.get("dividCashPsBeforeTax", "")),
                "stock": number(row.get("dividStocksPs", "")) + number(row.get("dividReserveToStockPs", "")),
                "taxable_stock": number(row.get("dividStocksPs", "")),
                "pay": pd.Timestamp(row.get("dividPayDate") or row["dividOperateDate"]),
                "release": pd.Timestamp(row.get("dividStockMarketDate") or row["dividOperateDate"]),
            }
            result[(symbol, date)] = item
    return result


def common_metrics(curve: pd.DataFrame, trades: pd.DataFrame, initial_cash: float) -> dict:
    curve = curve.sort_values("date").reset_index(drop=True)
    equity = curve["equity"].astype(float)
    daily = equity.pct_change(fill_method=None)
    daily.iloc[0] = equity.iloc[0] / initial_cash - 1.0
    elapsed_days = max(1, int((curve.date.iloc[-1] - curve.date.iloc[0]).days) + 1)
    years = elapsed_days / 365.25
    total_return = float(equity.iloc[-1] / initial_cash - 1.0)
    cagr = float((equity.iloc[-1] / initial_cash) ** (1.0 / years) - 1.0)
    peak = np.maximum.accumulate(np.r_[initial_cash, equity.to_numpy()])[1:]
    drawdown = equity.to_numpy() / peak - 1.0
    volatility = float(daily.std(ddof=1) * np.sqrt(252)) if daily.std(ddof=1) > 0 else 0.0
    sharpe = float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)) if daily.std(ddof=1) > 0 else 0.0
    downside = daily[daily < 0]
    sortino = float(daily.mean() / downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 1 and downside.std(ddof=1) > 0 else 0.0
    max_drawdown = float(drawdown.min())
    return {
        "start": str(curve.date.iloc[0].date()),
        "end": str(curve.date.iloc[-1].date()),
        "initial_cash": initial_cash,
        "final_equity": float(equity.iloc[-1]),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe_rf0": sharpe,
        "sortino_rf0": sortino,
        "max_drawdown": max_drawdown,
        "calmar": float(cagr / abs(max_drawdown)) if max_drawdown < 0 else 0.0,
        "positive_day_rate": float((daily > 0).mean()),
        "average_exposure": float(curve.exposure.mean()),
        "fills": int(len(trades)),
        "fees": float(trades.fee.sum()) if len(trades) and "fee" in trades else np.nan,
    }


def star_prepare():
    print("STAR prepare: loading frozen models", flush=True)
    namespaces = {name: platform_namespace(path) for name, path in STAR_ENTRIES.items()}
    base_ns = namespaces["科创1-2"]
    event_model = fast_model(decode_model(base_ns["_EMBEDDED_MODEL_B64"]))
    stop_model = fast_model(decode_model(base_ns["_EMBEDDED_STOP_MODEL_B64"]))
    base_ns["g"].model = event_model
    universe = list(event_model["universe"])
    feature_path = ROOT / "strategies/kechuang/training_source/src/model.py"
    feature = import_file(feature_path, "locked_baseline_features")
    metadata = pd.read_csv(STAR_DATA / "metadata/universe.csv").set_index("symbol")
    calendar = pd.read_csv(STAR_DATA / "metadata/trade_calendar_20261004.csv")
    dates = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]))
    dates = dates[(dates >= "2019-01-01") & (dates <= END)]
    chunks = []
    raw_panels = {}
    qfq_panels = {}
    prices = {}
    amounts = {}
    parity = []
    for index, symbol in enumerate(universe):
        raw_path = STAR_DATA / "raw" / f"{symbol}.parquet"
        qfq_path = STAR_DATA / "qfq" / f"{symbol}.parquet"
        if not raw_path.exists() or not qfq_path.exists():
            continue
        raw = pd.read_parquet(raw_path).sort_values("date").set_index("date").loc[:END]
        qfq = pd.read_parquet(qfq_path).sort_values("date").reset_index(drop=True)
        qfq = qfq[qfq.date <= END]
        if not raw.index.equals(pd.DatetimeIndex(qfq.date)):
            raise ValueError(f"STAR raw/qfq dates differ: {symbol}")
        frame = feature._one(qfq, 20, 0.30)
        age = np.arange(len(frame)) + 1
        valid = (
            (age >= 120) & (frame.date >= "2019-01-01") & (frame.date <= END)
            & (frame.ret5 <= 0.12) & (frame.ret20 <= 0.20) & (frame.rise_from_low60 <= 0.30)
            & (frame.volume_spike <= 5) & (frame.high != frame.low) & (frame.pctChg < 19.5)
            & (np.expm1(frame.amount20) >= 50_000_000) & (frame.isST.astype(str) != "1")
        )
        x = frame.loc[valid, ["date"] + event_model["features"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(x):
            values = x[event_model["features"]].to_numpy(float)
            x["p"] = base_ns["_batch_probabilities"](event_model, values)
            x["stop"] = base_ns["_batch_probabilities"](stop_model, values)
            x["score"] = x.p - 0.22 * x.stop
            x["symbol"] = symbol
            chunks.append(x[["date", "symbol", "p", "stop", "score"]])
            sample = x.index[-1]
            hist = qfq.iloc[max(0, sample - 120):sample + 1].set_index("date").rename(
                columns={"turn": "turnover_rate", "amount": "turnover", "pctChg": "quote_rate", "isST": "is_st"}
            )
            hist["is_st"] = hist.is_st.astype(str).eq("1")
            check = base_ns["_last_features"](hist)
            if check is None or not np.allclose(check, frame.loc[sample, event_model["features"]].to_numpy(float), rtol=1e-6, atol=1e-7):
                raise ValueError(f"STAR feature parity failed: {symbol}")
            if len(parity) < 30:
                parity.append(symbol)
        raw["prev_actual"] = raw.close.shift(1)
        raw["adjust_ratio"] = raw.preclose / raw.prev_actual
        raw_panels[symbol] = raw
        qidx = qfq.set_index("date")
        qfq_panels[symbol] = qidx
        prices[symbol] = qidx.close
        amounts[symbol] = qidx.amount
        if (index + 1) % 100 == 0:
            print(f"STAR features {index + 1}/{len(universe)}", flush=True)
    scores = pd.concat(chunks, ignore_index=True).sort_values(["date", "score", "symbol"], ascending=[True, False, True])
    price_panel = pd.DataFrame(prices).reindex(dates)
    amount_panel = pd.DataFrame(amounts).reindex(dates)

    def candidates(threshold: float) -> dict:
        selected = scores[(scores.p >= threshold) & (scores.stop <= 0.50)]
        return {date: list(group.head(8).symbol) for date, group in selected.groupby("date")}

    result = {
        "科创1-2": {"candidates": candidates(float(event_model["threshold"])), "fractions": {}},
        "科创3-1": {"candidates": candidates(0.63), "fractions": {}},
    }

    print("STAR prepare: industry temperature and bear probabilities", flush=True)
    temperature_path = ROOT / "strategies/kechuang/training_source/industry_temperature/temperature_variants.py"
    sys.path.insert(0, str(temperature_path.parent))
    try:
        temp_module = import_file(temperature_path, "locked_baseline_temperature")
    finally:
        sys.path.pop(0)
    ns2 = namespaces["科创2-2"]
    industry_map = decode_model(ns2["_INDUSTRY_MAP_B64"])
    industries = pd.Series(industry_map).reindex(price_panel.columns)
    temp, _ = temp_module.build_temperature(price_panel, amount_panel, industries)
    bear_bundle = decode_model(ns2["_EMBEDDED_BEAR_MODELS_B64"])
    for model in bear_bundle["models"]:
        ns2["_prepare_portable"](model)
    ns2["g"].bear_bundle = bear_bundle
    base2 = scores[(scores.p >= float(event_model["threshold"])) & (scores.stop <= 0.50)]
    bear_by_date = {}
    c2 = {}
    fraction_by_date = {}
    for count, (date, group) in enumerate(base2.groupby("date"), 1):
        window = price_panel.loc[:date].tail(61)
        ret = window / window.shift(1) - 1.0
        mret = ret.mean(axis=1).fillna(0.0)
        nav = (1.0 + mret).cumprod()
        cross_var = float(ret.var(axis=1).iloc[-20:].mean())
        values_by_name = {
            "mret5": float(nav.iloc[-1] / nav.iloc[-6] - 1.0),
            "mret20": float(nav.iloc[-1] / nav.iloc[-21] - 1.0),
            "mret60": float(nav.iloc[-1] / nav.iloc[-61] - 1.0),
            "mvol20": float(mret.iloc[-20:].std()),
            "breadth1": float((ret.iloc[-5:] > 0).mean(axis=1).mean()),
            "breadth20": float((window.iloc[-1] / window.iloc[-21] - 1.0 > 0).mean()),
            "dispersion": float(ret.iloc[-5:].std(axis=1).mean()),
            "downside_share": float((ret.iloc[-5:] < -0.03).mean(axis=1).mean()),
            "common_risk": min(1.0, max(0.0, float(mret.iloc[-20:].var()) / cross_var)) if cross_var > 0 else 0.0,
            "avg_dd20": float((window.iloc[-1] / window.iloc[-20:].max() - 1.0).mean()),
        }
        model = ns2["_bear_model_for_today"](date.to_pydatetime())
        bear = float(ns2["_tree_probability"](model, [values_by_name[name] for name in bear_bundle["features"]])) if model else 0.0
        bear_by_date[date] = bear
        fraction_by_date[date] = 0.055 if bear >= 0.70 else (0.075 if bear >= 0.55 else (0.09 if bear >= 0.40 else 0.10))
        kept = []
        for row in group.itertuples(index=False):
            industry = industry_map.get(row.symbol)
            if industry not in temp["heat"].columns or date not in temp["heat"].index:
                continue
            heat = float(temp["heat"].at[date, industry])
            delta = float(temp["delta"].at[date, industry])
            breadth = float(temp["breadth"].at[date, industry])
            if np.isfinite([heat, delta, breadth]).all() and (delta > 0.0 or (heat >= 65.0 and delta > -4.0 and breadth >= 55.0)):
                kept.append(row.symbol)
            if len(kept) >= 8:
                break
        c2[date] = kept
        if count % 250 == 0:
            print(f"STAR regime {count}/{base2.date.nunique()}", flush=True)
    result["科创2-2"] = {"candidates": c2, "fractions": fraction_by_date}
    validation = {
        "feature_parity_symbols": parity,
        "event_model_universe": len(universe),
        "loaded_symbols": len(raw_panels),
        "score_rows": len(scores),
        "last_score_date": str(scores.date.max().date()),
        "strategy_sha256": {name: sha256(path) for name, path in STAR_ENTRIES.items()},
    }
    return dates, raw_panels, metadata, result, validation


def star_action_map() -> dict:
    cache_path = ROOT / "strategies/kechuang/baseline_3_1_dynamic_500k_retrain/results/corporate_actions.json"
    supplement = OUT / "corporate_actions_supplement.json"
    return action_map(parse_action_cache([cache_path, supplement]), star=True)


def star_exit(name: str, signal: float, state: dict, amount: int, today) -> tuple[str, int] | None:
    entry = state["entry"]
    gain = signal / entry - 1.0
    if gain <= -0.07:
        return "STOP", 0
    if gain >= 0.34:
        return "TPALL", 0
    if gain >= 0.24 and not state["half"]:
        target = int(amount / 2)
        if target >= 200 and amount - target >= 200:
            return "TPHALF", target
        return None
    age = (today - state["entry_date"]).days
    if name == "科创3-1":
        if age >= 60:
            return "TIME60", 0
        if age >= 30 and gain < 0.10:
            return "TIME30", 0
    elif age >= 30:
        return "TIME", 0
    return None


def run_star(name: str, dates: pd.DatetimeIndex, panels: dict, metadata: pd.DataFrame,
             setup: dict, actions: dict, start: pd.Timestamp):
    start = dates[dates >= start][0]
    cash = INITIAL_CASH
    holdings = {}
    receivables = []
    curve = []
    trades = []
    unresolved = []
    for index, date in enumerate(dates):
        if date < start:
            continue
        day = {symbol: frame.loc[date] for symbol, frame in panels.items() if date in frame.index}
        previous = dates[index - 1]
        previous_day = {symbol: frame.loc[previous] for symbol, frame in panels.items() if previous in frame.index}
        pending = []
        for pay, amount in receivables:
            if pay <= date:
                cash += amount
            else:
                pending.append((pay, amount))
        receivables = pending
        for symbol, position in list(holdings.items()):
            row = day.get(symbol)
            for release, quantity in list(position["locked"]):
                if release <= date:
                    position["locked"].remove((release, quantity))
            corporate = actions.get((symbol, date))
            if corporate:
                old = position["qty"]
                dividend = old * corporate["cash"] * 0.8
                if corporate["pay"] <= date:
                    cash += dividend
                else:
                    receivables.append((corporate["pay"], dividend))
                bonus = int(np.floor(old * corporate["stock"] + 1e-8))
                position["qty"] += bonus
                if corporate["release"] > date:
                    position["locked"].append((corporate["release"], bonus))
                if row is not None:
                    position["last"] = float(row.preclose)
            if row is not None and np.isfinite(row.adjust_ratio) and abs(row.adjust_ratio - 1.0) > 1e-5:
                if not corporate:
                    unresolved.append((symbol, str(date.date()), float(row.adjust_ratio)))
                position["state"]["entry"] *= float(row.adjust_ratio)
            out = pd.to_datetime(metadata.loc[symbol, "outDate"], errors="coerce") if symbol in metadata.index else pd.NaT
            if pd.notna(out) and date >= out:
                trades.append({"date": date, "symbol": symbol, "side": "WRITE_OFF", "qty": position["qty"], "price": 0.0, "fee": 0.0})
                del holdings[symbol]

        def equity(use_open=False):
            market = 0.0
            for symbol, position in holdings.items():
                row = day.get(symbol)
                price = float(row.open) if use_open and row is not None and row.open > 0 else position["last"]
                market += position["qty"] * price
            return cash + sum(amount for _, amount in receivables) + market

        def tradable(symbol: str, buy: bool) -> bool:
            row = day.get(symbol)
            if row is None or str(row.tradestatus) != "1" or row.volume <= 0 or row.open <= 0:
                return False
            limit = 1.2 if buy else 0.8
            price_limit = np.floor(row.preclose * limit * 100 + 0.5) / 100
            return row.open < price_limit - 0.001 if buy else row.open > price_limit + 0.001

        used = {}
        fraction = setup["fractions"].get(previous, 0.10)
        for symbol in setup["candidates"].get(previous, []):
            if len(holdings) >= 14:
                break
            if symbol in holdings or not tradable(symbol, True):
                continue
            row = day[symbol]
            price = min(float(row.open) * 1.002, np.floor(row.preclose * 1.2 * 100 + 0.5) / 100)
            desired = int(equity(True) * fraction / price)
            cap = min(50_000, max(0, int(row.volume * 0.25) - used.get(symbol, 0)))
            affordable = int(max(0.0, cash - 5.0) / (price * 1.0003))
            quantity = min(desired, cap, affordable)
            if quantity < 200:
                continue
            amount = quantity * price
            fee = max(5.0, amount * 0.0003)
            if amount + fee > cash + 1e-8:
                continue
            cash -= amount + fee
            used[symbol] = used.get(symbol, 0) + quantity
            holdings[symbol] = {
                "qty": quantity,
                "last": float(row.open),
                "locked": [],
                "state": {"entry": price, "half": False, "entry_date": date.date()},
            }
            trades.append({"date": date, "symbol": symbol, "side": "BUY", "qty": quantity, "price": price, "fee": fee})
        for symbol, position in list(holdings.items()):
            if position["state"]["entry_date"] == date.date() or symbol not in previous_day or not tradable(symbol, False):
                continue
            row = day[symbol]
            signal = float(previous_day[symbol].close) * (float(row.adjust_ratio) if np.isfinite(row.adjust_ratio) else 1.0)
            decision = star_exit(name, signal, position["state"], position["qty"], date.date())
            if decision is None:
                continue
            sellable = position["qty"] - sum(quantity for _, quantity in position["locked"])
            requested = position["qty"] - decision[1]
            cap = min(50_000, max(0, int(row.volume * 0.25) - used.get(symbol, 0)))
            quantity = min(requested, sellable, cap)
            if quantity <= 0 or (quantity < 200 and quantity != sellable):
                continue
            price = max(float(row.open) * 0.998, np.floor(row.preclose * 0.8 * 100 + 0.5) / 100)
            amount = quantity * price
            fee = max(5.0, amount * 0.0003) + amount * (0.0005 if date >= pd.Timestamp("2023-08-28") else 0.001)
            cash += amount - fee
            position["qty"] -= quantity
            used[symbol] = used.get(symbol, 0) + quantity
            if decision[0] == "TPHALF":
                position["state"]["half"] = True
            trades.append({"date": date, "symbol": symbol, "side": decision[0], "qty": quantity, "price": price, "fee": fee})
            if position["qty"] == 0:
                del holdings[symbol]
        market_value = 0.0
        for symbol, position in holdings.items():
            row = day.get(symbol)
            if row is not None and row.close > 0:
                position["last"] = float(row.close)
            market_value += position["qty"] * position["last"]
        total = cash + market_value + sum(amount for _, amount in receivables)
        curve.append({"date": date, "equity": total, "cash": cash, "market_value": market_value, "exposure": market_value / total if total else 0.0})
    if unresolved:
        raise ValueError(f"Unresolved STAR corporate actions: {unresolved[:5]}")
    curve_frame = pd.DataFrame(curve)
    trade_frame = pd.DataFrame(trades)
    metrics = common_metrics(curve_frame, trade_frame, INITIAL_CASH)
    return metrics, curve_frame, trade_frame


def main_prepare_rankings(dates: pd.DatetimeIndex):
    print("MAIN prepare: formal R08/D11 rankings", flush=True)
    sys.modules.setdefault("mindgo_api", types.ModuleType("mindgo_api"))
    r08 = import_file(MAIN_ENTRIES["沪深基准1"], "formal_r08")
    market = pd.read_parquet(ROOT / "strategies/hushen/start_date_study/benchmark.parquet").set_index("date").close
    starts = [dates[dates >= start][0] for start in PERIODS.values()]
    r08_exec = set(starts)
    for start in starts:
        months = dates[dates >= start].to_period("M")
        for month in sorted(set(months)):
            if month.month % 2 == 1:
                r08_exec.add(dates[(dates >= start) & (dates.to_period("M") == month)][0])
    d11_exec = set(starts)
    for start in starts:
        for index in range(dates.get_loc(start), len(dates)):
            if (index - 1) % 20 == 0:
                d11_exec.add(dates[index])
    r08_signals = sorted(dates[dates.get_loc(day) - 1] for day in r08_exec)
    d11_signals = sorted(dates[dates.get_loc(day) - 1] for day in d11_exec)
    d11_factor_dates = sorted({date for signal in d11_signals for date in dates[max(0, dates.get_loc(signal) - 4):dates.get_loc(signal) + 1]})
    raw_files = sorted((MAIN_DATA / "raw").glob("*/*.parquet"))
    symbols = [path.stem for path in raw_files]
    matrices = {key: pd.DataFrame(np.nan, index=d11_factor_dates, columns=symbols, dtype=np.float32) for key in ("cap", "vol", "overnight", "intraday")}
    eligible = pd.DataFrame(False, index=d11_factor_dates, columns=symbols)
    r08_rows = []
    for count, path in enumerate(raw_files, 1):
        symbol = path.stem
        frame = pd.read_parquet(path)
        frame.date = pd.to_datetime(frame.date)
        frame = frame[frame.date <= END].set_index("date").sort_index()
        frame = frame[["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "isST", "tradestatus"]].apply(pd.to_numeric, errors="coerce")
        age = pd.Series(np.arange(len(frame)) + 1, index=frame.index)
        adjusted = (frame.close / frame.preclose).where(lambda values: (values > 0) & np.isfinite(values)).cumprod()
        returns = adjusted.pct_change(fill_method=None)
        log_return = np.log(adjusted.reindex(dates)).diff()
        benchmark_return = np.log(market.reindex(dates)).diff()
        var = log_return.rolling(252, min_periods=220).var()
        benchmark_var = benchmark_return.rolling(252, min_periods=220).var()
        beta = log_return.rolling(252, min_periods=220).cov(benchmark_return) / benchmark_var
        momentum = log_return.rolling(232, min_periods=220).sum().shift(20)
        benchmark_momentum = benchmark_return.rolling(232, min_periods=220).sum().shift(20)
        event = frame.close.shift() / frame.preclose - 1.0
        features = pd.DataFrame(index=dates)
        features["float_cap_proxy"] = frame.volume / (frame.turn.where(frame.turn > 0) / 100) * frame.close
        features["distribution_proxy"] = event.where(event.between(0.0005, 0.08), 0).clip(upper=0.04).rolling(250).sum()
        features["long_risk"] = momentum / (var.shift(20).clip(lower=1e-6).pow(0.5) * np.sqrt(232))
        features["market_adjusted"] = (momentum - beta.shift(20) * benchmark_momentum) / ((var - beta.pow(2) * benchmark_var).shift(20).clip(lower=1e-6).pow(0.5) * np.sqrt(232))
        features["vol60"] = returns.rolling(60).std()
        features["ret5"] = adjusted / adjusted.shift(5) - 1.0
        features["turn20"] = frame.turn.rolling(20).mean()
        ok_r08 = (age >= 250) & frame.isST.eq(0) & frame.tradestatus.eq(1) & returns.rolling(20).std().between(0.001, 0.08) & frame.amount.rolling(20).mean().ge(50_000_000)
        ok_r08 &= frame.preclose.gt(0).rolling(250).sum().eq(250)
        take = features.reindex(r08_signals).loc[ok_r08.reindex(r08_signals, fill_value=False)].copy()
        take["symbol"] = symbol
        take.index.name = "date"
        r08_rows.append(take.reset_index())
        ordinary = (frame.close / frame.preclose - 1.0).where(frame.tradestatus.eq(1) & frame.preclose.gt(0), 0)
        vol = ordinary.rolling(60).std()
        factor_values = {
            "cap": frame.close * frame.volume / (frame.turn / 100).replace(0, np.nan),
            "vol": vol,
            "overnight": np.log(frame.open / frame.preclose).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum(),
            "intraday": np.log(frame.close / frame.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum(),
        }
        for key, values in factor_values.items():
            matrices[key][symbol] = values.reindex(d11_factor_dates).astype(np.float32)
        eligible[symbol] = ((age >= 252) & frame.amount.rolling(20).mean().ge(10_000_000) & frame.close.ge(2) & frame.isST.eq(0) & frame.tradestatus.eq(1) & vol.gt(0.001) & vol.lt(0.09)).reindex(d11_factor_dates, fill_value=False)
        if count % 400 == 0:
            print(f"MAIN features {count}/{len(raw_files)}", flush=True)
    r08_all = pd.concat(r08_rows, ignore_index=True)
    r08_rankings = {str(date.date()): r08.rank_candidates(group).symbol.tolist() for date, group in r08_all.groupby("date")}
    ranks = {key: values.where(eligible).rank(axis=1, pct=True).astype(np.float32) for key, values in matrices.items()}
    daily_score = -0.35 * ranks["cap"] - 0.20 * ranks["vol"] + 0.25 * ranks["overnight"] - 0.20 * ranks["intraday"]
    d11_rankings = {}
    for signal in d11_signals:
        window = dates[max(0, dates.get_loc(signal) - 4):dates.get_loc(signal) + 1]
        smooth = daily_score.reindex(window).mean(axis=0, skipna=True)
        valid_count = daily_score.reindex(window).notna().sum(axis=0)
        smooth = smooth.where(valid_count >= 3).dropna().sort_values(ascending=False, kind="mergesort")
        d11_rankings[str(signal.date())] = smooth.head(100).index.tolist()
    selected = set(symbol for mapping in (r08_rankings, d11_rankings) for values in mapping.values() for symbol in values)
    panels = {}
    for path in raw_files:
        if path.stem not in selected:
            continue
        frame = pd.read_parquet(path)
        frame.date = pd.to_datetime(frame.date)
        frame = frame[frame.date <= END].set_index("date").sort_index()
        frame = frame[["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "isST", "tradestatus"]].apply(pd.to_numeric, errors="coerce")
        frame["volume20"] = frame.volume.rolling(20).mean()
        frame["prev_actual"] = frame.close.shift()
        frame["adjust_ratio"] = frame.preclose / frame.prev_actual
        panels[path.stem] = frame
    validation = {
        "r08_ranking_dates": len(r08_rankings),
        "d11_ranking_dates": len(d11_rankings),
        "candidate_symbols": len(selected),
        "strategy_sha256": {name: sha256(path) for name, path in MAIN_ENTRIES.items()},
    }
    return {"R08": r08_rankings, "D11": d11_rankings}, panels, validation


def main_action_map(panels: dict) -> dict:
    folder = ROOT / "strategies/hushen/start_date_study"
    paths = list(folder.glob("actions_*.json"))
    paths += list((ROOT / "strategies/hushen/test2_weekly/original_202001").glob("action_part_*.json"))
    paths += list((ROOT / "strategies/hushen/test2_weekly/start_dates_202001").glob("action_part_*.json"))
    supplement_path = OUT / "main_corporate_actions_supplement.json"
    paths.append(supplement_path)
    cache = parse_action_cache(paths)
    requests = set()
    for symbol, frame in panels.items():
        events = frame[(frame.index >= "2020-01-01") & np.isfinite(frame.adjust_ratio) & ((frame.adjust_ratio - 1.0).abs() > 1e-5)]
        requests.update((symbol, int(date.year)) for date in events.index)
    missing = [(symbol, year) for symbol, year in sorted(requests) if f"{symbol}/{year}" not in cache]
    if missing:
        import baostock as bs
        if bs.login().error_code != "0":
            raise RuntimeError("BaoStock login failed while completing corporate actions")
        try:
            for index, (symbol, year) in enumerate(missing, 1):
                code = symbol[-2:].lower() + "." + symbol[:6]
                result = bs.query_dividend_data(code=code, year=str(year), yearType="operate")
                if result.error_code != "0":
                    raise RuntimeError(result.error_msg)
                cache[f"{symbol}/{year}"] = result.get_data().to_dict("records")
                if index % 25 == 0:
                    write_json(supplement_path, {key: cache[key] for key in cache if (key.split("/")[0], int(key.split("/")[1])) in set(missing)})
                    print(f"MAIN actions {index}/{len(missing)}", flush=True)
        finally:
            bs.logout()
        requested_keys = {f"{symbol}/{year}" for symbol, year in missing}
        write_json(supplement_path, {key: cache[key] for key in requested_keys})
    return action_map(cache, star=False)


def run_main(name: str, dates: pd.DatetimeIndex, rankings: dict, panels: dict, actions: dict,
             start: pd.Timestamp):
    study = import_file(ROOT / "strategies/hushen/start_date_study/study.py", "formal_main_replay")
    study.FILES = {
        "R08": "supermind_mainboard_baseline_1.py",
        "D11": "supermind_mainboard_baseline_2.py",
    }
    model = "R08" if name == "沪深基准1" else "D11"
    start = dates[dates >= start][0]
    days = {date: {} for date in dates}
    for symbol, frame in panels.items():
        for row in frame.loc[dates[0]:END].itertuples():
            if row.Index in days:
                days[row.Index][symbol] = row
    metadata = pd.read_csv(MAIN_DATA / "metadata/historical_mainboard_universe.csv")
    out_dates = {row.symbol: pd.Timestamp(row.outDate) for row in metadata.itertuples() if pd.notna(row.outDate)}
    account = study.Account(model, start, actions, days, out_dates)
    account.cash = INITIAL_CASH
    account.stock.available_cash = INITIAL_CASH
    account.stock.total_value = INITIAL_CASH
    account.stock.frozen_cash = 0.0
    for index in range(dates.get_loc(start), len(dates)):
        account.step(dates[index], index, dates[index - 1], rankings[model])
    if account.issues:
        raise ValueError(f"Unresolved MAIN corporate actions: {list(account.issues.items())[:5]}")
    curve = pd.DataFrame(account.curve).drop(columns=["model", "start"])
    trades = pd.DataFrame(account.trades)
    if len(trades):
        trades["fee"] = trades[["commission", "transfer", "stamp", "dividend_tax"]].sum(axis=1)
    metrics = common_metrics(curve, trades, INITIAL_CASH)
    metrics["fees"] = float(account.fees + account.tax)
    return metrics, curve, trades


def charts(curves: dict, metrics: pd.DataFrame) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    for period, title in [("2025_latest", "2025年以来五个锁定基准"), ("2020_latest", "2020年以来五个锁定基准")]:
        fig, axes = plt.subplots(2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [2.2, 1]}, layout="constrained")
        for name in STAR_ENTRIES | MAIN_ENTRIES:
            curve = curves[(name, period)].sort_values("date")
            nav = curve.equity / INITIAL_CASH
            drawdown = nav / nav.cummax() - 1.0
            axes[0].plot(curve.date, nav, label=name, color=COLORS[name], lw=1.8)
            axes[1].plot(curve.date, drawdown * 100, label=name, color=COLORS[name], lw=1.2)
        axes[0].axhline(1.0, color="#666666", lw=0.8, ls="--")
        axes[0].set_ylabel("累计净值（初始=1）")
        axes[0].set_title(f"{title} · 50万元独立空仓起步")
        axes[0].legend(ncol=3, frameon=False)
        axes[0].grid(alpha=0.2)
        axes[1].set_ylabel("回撤（%）")
        axes[1].set_xlabel("交易日期")
        axes[1].grid(alpha=0.2)
        fig.text(0.5, 0.005, "本地日线成交近似；保留各策略自身费用、调仓与风控规则，不等同于SuperMind平台或实盘。", ha="center", fontsize=9)
        fig.savefig(OUT / f"nav_drawdown_{period}.png", dpi=170, bbox_inches="tight")
        plt.close(fig)
    primary = metrics[metrics.period == "2025_latest"].set_index("strategy")
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), layout="constrained")
    names = list(STAR_ENTRIES | MAIN_ENTRIES)
    colors = [COLORS[name] for name in names]
    axes[0].barh(names, primary.loc[names, "cagr"] * 100, color=colors)
    axes[0].set(title="年化收益率", xlabel="%")
    axes[1].barh(names, -primary.loc[names, "max_drawdown"] * 100, color=colors)
    axes[1].set(title="最大回撤幅度", xlabel="%")
    axes[2].barh(names, primary.loc[names, "sharpe_rf0"], color=colors)
    axes[2].set(title="Sharpe（无风险利率0）", xlabel="倍")
    for axis in axes:
        axis.grid(axis="x", alpha=0.2)
        axis.invert_yaxis()
    fig.suptitle("2025-01-02—2026-09-30 常见评价指标对比（50万元）")
    fig.savefig(OUT / "metrics_2025_latest.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def markdown_table(frame: pd.DataFrame) -> str:
    lines = [
        "| 基准 | 期末资产 | 累计收益 | 年化收益 | 最大回撤 | 年化波动 | Sharpe | Sortino | Calmar | 平均仓位 | 成交笔数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"| {row.strategy} | {row.final_equity / 10000:.2f}万元 | {row.total_return:.2%} | {row.cagr:.2%} | "
            f"{abs(row.max_drawdown):.2%} | {row.annual_volatility:.2%} | {row.sharpe_rf0:.3f} | "
            f"{row.sortino_rf0:.3f} | {row.calmar:.3f} | {row.average_exposure:.2%} | {row.fills} |"
        )
    return "\n".join(lines)


def report(metrics: pd.DataFrame) -> None:
    primary = metrics[metrics.period == "2025_latest"]
    full = metrics[metrics.period == "2020_latest"]
    text = f"""# 五个锁定基准统一口径本地比较

生成日期：2026-10-06。五个正式入口均保持不变。本报告把每条策略放入独立空仓账户，统一使用50万元初始资金；主比较从各市场2025年第一个交易日开始，补充比较从2020年第一个交易日开始，统一截至本地行情最后日期2026-09-30。

## 2025年以来

![2025年以来净值与回撤](nav_drawdown_2025_latest.png)

![2025年以来指标对比](metrics_2025_latest.png)

{markdown_table(primary)}

## 2020年以来

![2020年以来净值与回撤](nav_drawdown_2020_latest.png)

{markdown_table(full)}

## 共同交易纪律

所有基准只能使用下单时已经获得的数据；遵守A股T+1、停牌、涨跌停、整手/最低买入数量、现金和成交量约束。未成交订单不按理论成交记账，研究候选不得自动覆盖正式入口。

## 口径边界

- 这是本地日线成交近似，不是SuperMind服务器回测或实盘账户记录。
- 科创策略按自身0.20%单边滑点执行；沪深基准1按0.20%、沪深基准2按0.10%单边滑点执行。佣金、最低佣金、印花税、分红送转和容量约束按各自本地账本处理。
- 科创正式入口保留冻结证券池及模型的历史研究偏差；科创2-2的季度熊市模型只覆盖至2026-09-30。
- Sharpe和Sortino使用日收益、252日年化、无风险利率0；Calmar为年化收益除以最大回撤绝对值。
"""
    (OUT / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = {
        "created": "2026-10-06",
        "initial_cash": INITIAL_CASH,
        "end": str(END.date()),
        "periods": {key: [str(value.date()), str(END.date())] for key, value in PERIODS.items()},
        "entries": {name: str(path.relative_to(ROOT)).replace("\\", "/") for name, path in (STAR_ENTRIES | MAIN_ENTRIES).items()},
        "entry_sha256": {name: sha256(path) for name, path in (STAR_ENTRIES | MAIN_ENTRIES).items()},
        "selection_or_training": False,
        "execution": "local daily-bar approximation preserving each frozen strategy's own rules",
    }
    write_json(OUT / "protocol.json", protocol)

    star_dates, star_panels, star_meta, star_setups, star_validation = star_prepare()
    star_actions = star_action_map()
    benchmark = pd.read_parquet(ROOT / "strategies/hushen/start_date_study/benchmark.parquet")
    main_dates = pd.DatetimeIndex(pd.to_datetime(benchmark.date))
    main_dates = main_dates[(main_dates >= "2018-01-01") & (main_dates <= END)]
    main_rankings, main_panels, main_validation = main_prepare_rankings(main_dates)
    main_actions = main_action_map(main_panels)

    metrics_rows = []
    curves = {}
    for period, requested_start in PERIODS.items():
        for name in STAR_ENTRIES:
            curve_path = OUT / f"curve_{period}_{name}.parquet"
            trade_path = OUT / f"trades_{period}_{name}.parquet"
            if curve_path.exists() and trade_path.exists():
                curve = pd.read_parquet(curve_path)
                trades = pd.read_parquet(trade_path)
                metrics = common_metrics(curve, trades, INITIAL_CASH)
                print("REUSE", period, name, flush=True)
            else:
                metrics, curve, trades = run_star(name, star_dates, star_panels, star_meta, star_setups[name], star_actions, requested_start)
            metrics.update(strategy=name, period=period, market="科创")
            metrics_rows.append(metrics)
            curves[(name, period)] = curve
            curve.assign(strategy=name, period=period).to_parquet(curve_path, index=False)
            trades.assign(strategy=name, period=period).to_parquet(trade_path, index=False)
            print("RESULT", period, name, round(metrics["final_equity"], 2), flush=True)
        for name in MAIN_ENTRIES:
            curve_path = OUT / f"curve_{period}_{name}.parquet"
            trade_path = OUT / f"trades_{period}_{name}.parquet"
            if curve_path.exists() and trade_path.exists():
                curve = pd.read_parquet(curve_path)
                trades = pd.read_parquet(trade_path)
                metrics = common_metrics(curve, trades, INITIAL_CASH)
                print("REUSE", period, name, flush=True)
            else:
                metrics, curve, trades = run_main(name, main_dates, main_rankings, main_panels, main_actions, requested_start)
            metrics.update(strategy=name, period=period, market="沪深")
            metrics_rows.append(metrics)
            curves[(name, period)] = curve
            curve.assign(strategy=name, period=period).to_parquet(curve_path, index=False)
            trades.assign(strategy=name, period=period).to_parquet(trade_path, index=False)
            print("RESULT", period, name, round(metrics["final_equity"], 2), flush=True)
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(OUT / "metrics.csv", index=False, encoding="utf-8-sig")
    write_json(OUT / "metrics.json", metrics.to_dict("records"))
    charts(curves, metrics)
    report(metrics)
    validation = {
        "passed": True,
        "star": star_validation,
        "main": main_validation,
        "runs": len(metrics),
        "latest_market_date": str(max(frame.date.max() for frame in curves.values()).date()),
        "entry_hashes_unchanged": all(sha256(path) == protocol["entry_sha256"][name] for name, path in (STAR_ENTRIES | MAIN_ENTRIES).items()),
    }
    write_json(OUT / "validation.json", validation)
    print("COMPLETE", OUT, flush=True)


if __name__ == "__main__":
    main()
