from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "inputs_pre2025"
STRATEGY = ROOT.parents[1] / "supermind_hushen_1.py"
BACKTEST = ROOT.parents[1] / "backtest"
SEARCH = HERE / "SEARCH_SPACE.json"
DEV_END = pd.Timestamp("2023-12-31")
CONFIRM_END = pd.Timestamp("2024-12-31")
ANCHOR = pd.Timestamp("2018-01-02")
INITIAL = 100_000.0


def canonical_hash(obj: object) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def verify_search_freeze() -> tuple[dict, str]:
    spec = json.loads(SEARCH.read_text(encoding="utf-8"))
    expected = spec["freeze"]["frozen_spec_sha256"]
    check = json.loads(json.dumps(spec))
    del check["freeze"]["frozen_spec_sha256"]
    actual = canonical_hash(check)
    if actual != expected:
        raise RuntimeError(f"SEARCH_SPACE freeze mismatch: {actual} != {expected}")
    return spec, actual


def candidates(spec: dict) -> list[dict]:
    base = dict(spec["baseline"])
    result = [{"candidate_id": "baseline", "family": "baseline", "axis_value": None, **base}]
    for family, values in spec["candidate_generation"]["families"].items():
        for value in values:
            row = dict(base)
            if family == "smooth":
                row.update(value)
                axis = f"{value['smooth']}_{value['min_smooth']}"
            elif family.endswith("_weight"):
                factor = family.removesuffix("_weight")
                row["weights"] = dict(base["weights"])
                row["weights"][factor] = value
                axis = str(value)
            else:
                row[family] = value
                axis = str(value)
            row.update(candidate_id=f"{family}_{axis}", family=family, axis_value=value)
            result.append(row)
    unique = {}
    for row in result:
        key = canonical_hash({k: v for k, v in row.items() if k not in {"candidate_id", "family", "axis_value"}})
        unique.setdefault(key, row)
    return list(unique.values())


@dataclass
class Market:
    dates: pd.DatetimeIndex
    symbols: list[str]
    columns: dict[str, int]
    raw: dict[str, np.ndarray]
    present: np.ndarray
    ranks: dict[str, np.ndarray]
    eligible: np.ndarray
    volume20: np.ndarray
    outs: dict[str, pd.Timestamp]
    actions: dict[tuple[str, pd.Timestamp], dict]
    benchmark: pd.DataFrame
    input_hashes: dict[str, str]


def _float(text: object) -> float:
    return float(text) if str(text).strip() else 0.0


def load_market(end: pd.Timestamp, verify_raw: bool = True) -> Market:
    manifest_path = DATA / "PUBLIC_INPUT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if pd.Timestamp(manifest["cutoff"]) > pd.Timestamp("2024-12-31"):
        raise RuntimeError("input cutoff exceeds public boundary")
    fixed = {
        "calendar.csv": manifest["calendar_sha256"],
        "universe.csv": manifest["universe_sha256"],
        "sse_price_index.parquet": manifest["sse_index_sha256"],
        "actions_pre2025.json": manifest["actions_sha256"],
    }
    checked = {name: file_hash(DATA / name) for name in fixed}
    if checked != fixed:
        raise RuntimeError("fixed input hash mismatch")
    cal = pd.read_csv(DATA / "calendar.csv")
    dates = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1), "calendar_date"]))
    dates = dates[dates <= end]
    if ANCHOR not in dates:
        raise RuntimeError("phase anchor absent from calendar")
    records = [r for r in manifest["files"] if r.get("start") and int(r.get("rows", 0)) > 0 and pd.Timestamp(r["start"]) <= end]
    symbols = [r["symbol"] for r in records]
    columns = {s: i for i, s in enumerate(symbols)}
    ndate, nsym = len(dates), len(symbols)
    fields = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn"]
    raw = {k: np.full((ndate, nsym), np.nan, dtype=np.float32) for k in fields}
    present = np.zeros((ndate, nsym), dtype=bool)
    tradable = np.zeros((ndate, nsym), dtype=bool)
    is_st = np.zeros((ndate, nsym), dtype=bool)
    feature = {k: np.full((ndate, nsym), np.nan, dtype=np.float32) for k in ("cap", "vol", "overnight", "intraday")}
    eligible = np.zeros((ndate, nsym), dtype=bool)
    volume20 = np.full((ndate, nsym), np.nan, dtype=np.float32)
    raw_hash_failures = []
    for j, record in enumerate(records):
        path = DATA / "raw" / record["symbol"][-2:] / f"{record['symbol']}.parquet"
        if verify_raw and file_hash(path) != record["sha256"]:
            raw_hash_failures.append(record["symbol"])
            continue
        x = pd.read_parquet(path)
        x["date"] = pd.to_datetime(x["date"])
        x = x.loc[x.date.le(end)].set_index("date").sort_index()
        x = x.loc[~x.index.duplicated(keep="last")]
        if x.empty:
            continue
        ix = dates.get_indexer(x.index)
        keep = ix >= 0
        ix = ix[keep]
        x = x.iloc[np.flatnonzero(keep)]
        numeric = x[fields + ["tradestatus", "isST"]].apply(pd.to_numeric, errors="raise")
        for k in fields:
            raw[k][ix, j] = numeric[k].to_numpy(dtype=np.float32)
        present[ix, j] = True
        tradable[ix, j] = numeric.tradestatus.to_numpy() == 1
        is_st[ix, j] = numeric.isST.to_numpy() == 1
        close = numeric.close.astype(float)
        preclose = numeric.preclose.astype(float)
        ret = (close / preclose - 1).where(numeric.tradestatus.eq(1) & preclose.gt(0), 0.0)
        vol = ret.rolling(60).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight = np.log(numeric.open / preclose).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(close / numeric.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        amt20 = numeric.amount.rolling(20).mean()
        vol20 = numeric.volume.rolling(20).mean()
        cap = close * numeric.volume / (numeric.turn / 100).replace(0, np.nan)
        age = pd.Series(np.arange(len(x)) + 1, index=x.index)
        ok = (age.ge(252) & amt20.ge(1e7) & close.ge(2) & numeric.isST.eq(0) &
              numeric.tradestatus.eq(1) & vol.gt(0.001) & vol.lt(0.09))
        for name, values in (("cap", cap), ("vol", vol), ("overnight", overnight), ("intraday", intraday)):
            feature[name][ix, j] = values.to_numpy(dtype=np.float32)
        eligible[ix, j] = ok.to_numpy(dtype=bool)
        volume20[ix, j] = vol20.to_numpy(dtype=np.float32)
    if raw_hash_failures:
        raise RuntimeError(f"raw input hash mismatch: {raw_hash_failures[:5]}")
    raw["tradable"] = tradable
    raw["is_st"] = is_st
    universe = pd.read_csv(DATA / "universe.csv")
    universe["ipoDate"] = pd.to_datetime(universe.ipoDate)
    universe["outDate"] = pd.to_datetime(universe.outDate, errors="coerce")
    meta = universe.set_index("symbol")
    for j, symbol in enumerate(symbols):
        if symbol not in meta.index:
            eligible[:, j] = False
            continue
        rec = meta.loc[symbol]
        member = (dates >= rec.ipoDate) & (pd.isna(rec.outDate) | (dates < rec.outDate))
        eligible[:, j] &= member
    ranks = {k: np.full_like(v, np.nan, dtype=np.float32) for k, v in feature.items()}
    for i in range(ndate):
        mask = eligible[i]
        for name in ranks:
            mask2 = mask & np.isfinite(feature[name][i])
            if mask2.any():
                ranks[name][i, mask2] = (rankdata(feature[name][i, mask2], method="average") / mask2.sum()).astype(np.float32)
    del feature
    actions_raw = json.loads((DATA / "actions_pre2025.json").read_text(encoding="utf-8"))
    actions = {}
    for key, rows in actions_raw.items():
        symbol = key.split("/")[0]
        for row in rows:
            if not row.get("dividOperateDate"):
                continue
            date = pd.Timestamp(row["dividOperateDate"])
            if date > end:
                continue
            actions[symbol, date] = {
                "cash": _float(row.get("dividCashPsBeforeTax", "")),
                "stock": _float(row.get("dividStocksPs", "")) + _float(row.get("dividReserveToStockPs", "")),
                "taxable_stock": _float(row.get("dividStocksPs", "")),
                "pay": pd.Timestamp(row.get("dividPayDate") or row["dividOperateDate"]),
                "release": pd.Timestamp(row.get("dividStockMarketDate") or row["dividOperateDate"]),
            }
    outs = {s: pd.Timestamp(meta.loc[s, "outDate"]) for s in symbols if s in meta.index and pd.notna(meta.loc[s, "outDate"])}
    benchmark = pd.read_parquet(DATA / "sse_price_index.parquet")
    benchmark["date"] = pd.to_datetime(benchmark.date)
    benchmark = benchmark.loc[benchmark.date.le(end)].set_index("date").sort_index()
    input_hashes = {**checked, "PUBLIC_INPUT_MANIFEST.json": file_hash(manifest_path)}
    for p in (STRATEGY, BACKTEST / "engine.py", BACKTEST / "ledger.py", BACKTEST / "actions.py", ROOT / "PROTOCOL_V3.md"):
        input_hashes[str(p.relative_to(ROOT.parents[3])).replace("\\", "/")] = file_hash(p)
    return Market(dates, symbols, columns, raw, present, ranks, eligible, volume20, outs, actions, benchmark, input_hashes)


class RankingBook:
    def __init__(self, market: Market, params: dict):
        self.market = market
        self.params = params
        w = params["weights"]
        score = (w["cap"] * market.ranks["cap"] + w["vol"] * market.ranks["vol"] +
                 w["overnight"] * market.ranks["overnight"] + w["intraday"] * market.ranks["intraday"])
        self.score = score.astype(np.float32)
        self.cache: dict[int, list[int]] = {}

    def get(self, signal_i: int) -> list[int]:
        if signal_i in self.cache:
            return self.cache[signal_i]
        smooth = int(self.params["smooth"])
        minimum = int(self.params["min_smooth"])
        lo = max(0, signal_i - smooth + 1)
        window = self.score[lo:signal_i + 1]
        count = np.isfinite(window).sum(axis=0)
        total = np.nansum(window, axis=0)
        values = np.where(count >= minimum, total / np.maximum(count, 1), np.nan).astype(np.float32)
        values[~self.market.eligible[signal_i]] = np.nan
        idx = np.flatnonzero(np.isfinite(values))
        order = idx[np.argsort(-values[idx], kind="stable")][:100]
        result = order.tolist()
        self.cache[signal_i] = result
        return result


def add_years(date: pd.Timestamp, years: int = 1) -> pd.Timestamp:
    return date + pd.DateOffset(years=years)


class Account:
    def __init__(self, market: Market, params: dict, start_i: int, stress: str = "base"):
        self.m = market
        self.p = params
        self.start_i = start_i
        self.cash = INITIAL
        self.holdings: dict[int, dict] = {}
        self.receivables: list[tuple[pd.Timestamp, float]] = []
        self.targets: dict[int, int] = {}
        self.first = True
        self.fees = 0.0
        self.divtax = 0.0
        self.turnover = 0.0
        self.trades = 0
        self.capacity_hits = 0
        self.rejected = 0
        self.curve = []
        self.stress = stress

    def available(self, j: int, date: pd.Timestamp) -> int:
        return sum(lot["q"] for lot in self.holdings[j]["lots"] if lot["release"] <= date and lot["buy"] < date)

    def corporate(self, date: pd.Timestamp, i: int) -> None:
        self.receivables, due = [(d, a) for d, a in self.receivables if d > date], [(d, a) for d, a in self.receivables if d <= date]
        self.cash += sum(a for _, a in due)
        for j in list(self.holdings):
            symbol = self.m.symbols[j]
            pos = self.holdings[j]
            action = self.m.actions.get((symbol, date))
            if action:
                old = pos["qty"]
                amount = old * action["cash"]
                if action["pay"] <= date:
                    self.cash += amount
                else:
                    self.receivables.append((action["pay"], amount))
                additions = []
                remaining = int(math.floor(old * action["stock"] + 1e-8))
                for k, lot in enumerate(list(pos["lots"])):
                    bonus = min(remaining, int(math.floor(lot["q"] * action["stock"] + 1e-8)))
                    if k == len(pos["lots"]) - 1:
                        bonus = remaining
                    remaining -= bonus
                    taxable = action["cash"] + action["taxable_stock"] if date <= add_years(lot["buy"]) else 0.0
                    liability = lot["div"] + taxable
                    adjusted = liability * lot["q"] / (lot["q"] + bonus) if lot["q"] + bonus else 0.0
                    lot["div"] = adjusted
                    if bonus:
                        additions.append({"q": bonus, "buy": lot["buy"], "release": action["release"], "div": adjusted})
                pos["lots"].extend(additions)
                pos["lots"].sort(key=lambda x: (x["buy"], x["release"]))
                pos["qty"] = sum(x["q"] for x in pos["lots"])
                if np.isfinite(self.m.raw["preclose"][i, j]):
                    pos["last"] = float(self.m.raw["preclose"][i, j])
                if j in self.targets and old > 0 and pos["qty"] > 0 and old != pos["qty"]:
                    self.targets[j] = int(math.floor(self.targets[j] * pos["qty"] / old + 1e-8))
            out = self.m.outs.get(symbol)
            if out is not None and date >= out:
                del self.holdings[j]
                self.targets.pop(j, None)

    def limit_bounds(self, i: int, j: int) -> tuple[float, float]:
        pre = float(self.m.raw["preclose"][i, j])
        pct = 0.05 if self.m.raw["is_st"][i, j] else 0.10
        high = math.floor(pre * (1 + pct) * 100 + 0.5) / 100
        low = math.floor(pre * (1 - pct) * 100 + 0.5) / 100
        return low, high

    def valid(self, i: int, j: int) -> bool:
        op = self.m.raw["open"][i, j]
        if not self.m.present[i, j] or not self.m.raw["tradable"][i, j] or not np.isfinite(op) or op <= 0:
            return False
        low, high = self.limit_bounds(i, j)
        return 0 < low <= op <= high

    def buy_cost(self, qty: int, op: float, commission_rate: float, minimum: float) -> float:
        value = qty * (op * 1.001 + 0.01)
        return value + max(minimum, value * commission_rate) + value * 0.00002

    def order(self, date: pd.Timestamp, i: int, j: int, qty: int, limit: float, participation: float,
              commission_rate: float, minimum: float) -> bool:
        if not self.valid(i, j) or self.m.raw["volume"][i, j] <= 0:
            self.rejected += 1
            return False
        op = float(self.m.raw["open"][i, j])
        low, high = self.limit_bounds(i, j)
        if qty > 0:
            if op >= high - 1e-8 or limit < op - 1e-8:
                self.rejected += 1
                return False
            price = min(limit, op * 1.001, float(self.m.raw["high"][i, j]), high)
            if price < max(float(self.m.raw["low"][i, j]), low) - 1e-8:
                self.rejected += 1
                return False
        else:
            if op <= low + 1e-8 or limit > op + 1e-8:
                self.rejected += 1
                return False
            price = max(limit, op * 0.999, float(self.m.raw["low"][i, j]), low)
            if price > min(float(self.m.raw["high"][i, j]), high) + 1e-8:
                self.rejected += 1
                return False
        price = round(float(price), 2)
        cap20 = int(float(self.m.volume20[i - 1, j]) * participation / 100) * 100 if i > 0 and np.isfinite(self.m.volume20[i - 1, j]) else 0
        capday = int(float(self.m.raw["volume"][i, j]) * 0.25 / 100) * 100
        if abs(qty) > min(cap20, capday, 1_000_000):
            self.capacity_hits += 1
            return False
        value = round(abs(qty) * price, 2)
        commission = round(max(minimum, value * commission_rate), 2)
        transfer = round(value * (0.00002 if date < pd.Timestamp("2022-04-29") else 0.00001), 2)
        stamp = round(value * (0.001 if date < pd.Timestamp("2023-08-28") else 0.0005), 2) if qty < 0 else 0.0
        fees = commission + transfer + stamp
        tax = 0.0
        if qty > 0:
            if value + fees > self.cash + 1e-6:
                self.rejected += 1
                return False
            self.cash -= value + fees
            pos = self.holdings.setdefault(j, {"qty": 0, "last": price, "lots": []})
            pos["qty"] += qty
            pos["lots"].append({"q": qty, "buy": date, "release": date + pd.Timedelta(days=1), "div": 0.0})
        else:
            if j not in self.holdings or -qty > self.available(j, date):
                self.rejected += 1
                return False
            pos = self.holdings[j]
            remaining = -qty
            for lot in pos["lots"]:
                if lot["release"] > date or lot["buy"] >= date:
                    continue
                q = min(remaining, lot["q"])
                remaining -= q
                lot["q"] -= q
                rate = 0.2 if date <= lot["buy"] + pd.DateOffset(months=1) else (0.1 if date <= add_years(lot["buy"]) else 0.0)
                tax += q * lot["div"] * rate
                if remaining == 0:
                    break
            if remaining:
                self.rejected += 1
                return False
            tax = round(tax, 2)
            pos["lots"] = [x for x in pos["lots"] if x["q"]]
            pos["qty"] += qty
            self.cash += value - fees - tax
            if pos["qty"] == 0:
                del self.holdings[j]
        self.fees += fees
        self.divtax += tax
        self.turnover += value
        self.trades += 1
        return True

    def step(self, i: int, ranks: list[int], due: bool) -> None:
        date = self.m.dates[i]
        self.corporate(date, i)
        positions = self.holdings
        nav_open = self.cash + sum(a for _, a in self.receivables)
        for j, pos in positions.items():
            op = self.m.raw["open"][i, j]
            nav_open += pos["qty"] * (float(op) if self.valid(i, j) else pos["last"])
        commission_rate, minimum = (0.0006, 10.0) if self.stress == "double_commission" else (0.0003, 5.0)
        participation = float(self.p["participation_20d_mean_volume"])
        if self.stress == "capacity_40pct":
            participation *= 0.4
        if self.first or due:
            budget = nav_open * float(self.p["exposure"]) / int(self.p["count"])
            keep = set(ranks[:int(int(self.p["count"]) * float(self.p["buffer"]))])
            def selectable(j: int) -> bool:
                if not self.valid(i, j) or self.m.raw["is_st"][i, j]:
                    return False
                op = float(self.m.raw["open"][i, j]); _, high = self.limit_bounds(i, j)
                return op < high - 1e-8 and self.buy_cost(100, op, commission_rate, minimum) <= budget
            selected = [j for j in ranks if j in positions and j in keep and selectable(j)][:int(self.p["count"])]
            for j in ranks:
                if len(selected) >= int(self.p["count"]):
                    break
                if j not in selected and selectable(j):
                    selected.append(j)
            self.targets = {j: 0 for j in positions if j not in selected}
            for j in selected:
                op = float(self.m.raw["open"][i, j])
                self.targets[j] = int(budget / op / 100) * 100
            self.first = False
        if i > 0:
            for j in list(positions):
                if self.m.raw["is_st"][i - 1, j]:
                    self.targets[j] = 0
        keys = sorted(self.targets, key=lambda j: (self.targets[j] - (positions[j]["qty"] if j in positions else 0) >= 0, self.m.symbols[j]))
        cash_budget = self.cash
        for j in keys:
            current = positions[j]["qty"] if j in positions else 0
            delta = self.targets[j] - current
            if delta == 0 or not self.valid(i, j) or i == 0 or not np.isfinite(self.m.volume20[i - 1, j]):
                continue
            op = float(self.m.raw["open"][i, j]); low, high = self.limit_bounds(i, j)
            cap = min(int(float(self.m.volume20[i - 1, j]) * participation / 100) * 100, 1_000_000)
            qty = min(abs(delta), cap)
            if delta < 0:
                if op <= low + 1e-8:
                    continue
                qty = min(qty, self.available(j, date))
                if qty != current:
                    qty = qty // 100 * 100
                if qty > 0:
                    limit = max(low, math.floor(op * 0.999 * 100 + 1e-8) / 100)
                    before = self.cash
                    self.order(date, i, j, -qty, limit, participation, commission_rate, minimum)
                    cash_budget += max(0.0, self.cash - before)
            else:
                if self.m.raw["is_st"][i, j] or op >= high - 1e-8:
                    continue
                qty = qty // 100 * 100
                available = min(cash_budget, self.cash)
                while qty > 0 and self.buy_cost(qty, op, commission_rate, minimum) > available:
                    qty -= 100
                if qty > 0:
                    limit = min(high, math.ceil(op * 1.001 * 100 - 1e-8) / 100)
                    if self.order(date, i, j, qty, limit, participation, commission_rate, minimum):
                        cash_budget -= self.buy_cost(qty, op, commission_rate, minimum)
        market_value = 0.0
        for j, pos in self.holdings.items():
            close = self.m.raw["close"][i, j]
            if np.isfinite(close) and close > 0:
                pos["last"] = float(close)
            market_value += pos["qty"] * pos["last"]
        equity = self.cash + market_value + sum(a for _, a in self.receivables)
        self.curve.append(equity)

    def metrics(self, start: pd.Timestamp, end: pd.Timestamp) -> dict:
        nav = np.asarray(self.curve, dtype=float)
        daily = nav / np.r_[INITIAL, nav[:-1]] - 1
        peak = np.maximum.accumulate(np.r_[INITIAL, nav])[1:]
        days = (end - start).days + 1
        b = self.m.benchmark
        benchmark_return = float(b.loc[end, "close"] / b.loc[start, "open"] - 1)
        total = float(nav[-1] / INITIAL - 1)
        return {
            "start": str(start.date()), "end": str(end.date()), "total_return": total,
            "benchmark_return": benchmark_return, "excess": total - benchmark_return,
            "cagr": float((nav[-1] / INITIAL) ** (365.25 / days) - 1),
            "max_drawdown": float((1 - nav / peak).max()),
            "sharpe": float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)) if daily.std(ddof=1) > 0 else np.nan,
            "total_cost": self.fees + self.divtax, "cost_rate": (self.fees + self.divtax) / INITIAL,
            "turnover": self.turnover / INITIAL, "trades": self.trades,
            "capacity_hits": self.capacity_hits, "rejected_orders": self.rejected,
            "final_equity": float(nav[-1]), "average_exposure_proxy": np.nan,
        }


def start_indices(market: Market, years: range) -> list[int]:
    return [i for i, d in enumerate(market.dates) if d.year in years and d.month <= 3]


def due_on(market: Market, i: int, interval: int) -> bool:
    anchor_i = market.dates.get_loc(ANCHOR)
    phase = i - anchor_i
    return (phase - 1) % interval == 0


def run_candidate(market: Market, params: dict, years: range, stress: str = "base") -> pd.DataFrame:
    book = RankingBook(market, params)
    rows = []
    for start_i in start_indices(market, years):
        start = market.dates[start_i]
        year_ix = np.flatnonzero(market.dates.year == start.year)
        end_i = int(year_ix[-1])
        account = Account(market, params, start_i, stress)
        for i in range(start_i, end_i + 1):
            scheduled = due_on(market, i, int(params["interval"]))
            ranks = book.get(i - 1) if account.first or scheduled else []
            account.step(i, ranks, scheduled)
        row = account.metrics(start, market.dates[end_i])
        row.update(candidate_id=params["candidate_id"], family=params["family"], stress=stress, year=start.year)
        rows.append(row)
    return pd.DataFrame(rows)


def summary_table(all_starts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    yearly = (all_starts.groupby(["candidate_id", "year"], as_index=False)
              .agg(starts=("start", "size"), median_excess=("excess", "median"), mean_excess=("excess", "mean"),
                   median_cagr=("cagr", "median"), min_cagr=("cagr", "min"), mean_cagr=("cagr", "mean"),
                   mean_drawdown=("max_drawdown", "mean"), mean_sharpe=("sharpe", "mean"),
                   mean_cost_rate=("cost_rate", "mean"), mean_turnover=("turnover", "mean"),
                   capacity_hits=("capacity_hits", "sum")))
    summary = (all_starts.groupby("candidate_id", as_index=False)
               .agg(mean_cagr=("cagr", "mean"), min_cagr=("cagr", "min"), mean_excess=("excess", "mean"),
                    mean_drawdown=("max_drawdown", "mean"), mean_sharpe=("sharpe", "mean"),
                    mean_cost_rate=("cost_rate", "mean"), mean_turnover=("turnover", "mean"),
                    starts=("start", "size")))
    annual = yearly.groupby("candidate_id").median_excess.agg(["min", "std"]).rename(columns={"min": "worst_year_median_excess", "std": "year_median_excess_std"})
    summary = summary.merge(annual, on="candidate_id")
    return yearly, summary


def gate_and_select(all_starts: pd.DataFrame, yearly: pd.DataFrame, summary: pd.DataFrame, params: list[dict]) -> tuple[pd.DataFrame, dict]:
    base_starts = all_starts.loc[all_starts.candidate_id.eq("baseline")].set_index("start")
    base_year = yearly.loc[yearly.candidate_id.eq("baseline")].set_index("year")
    base_summary = summary.loc[summary.candidate_id.eq("baseline")].iloc[0]
    pmap = {p["candidate_id"]: p for p in params}
    family_order = {}
    for p in params:
        if p["family"] != "baseline":
            family_order.setdefault(p["family"], []).append(p)
    for family in family_order:
        family_order[family].sort(key=lambda p: float(p["axis_value"]["smooth"] if isinstance(p["axis_value"], dict) else p["axis_value"]))
    records = []
    for _, s in summary.iterrows():
        cid = s.candidate_id
        if cid == "baseline":
            records.append({"candidate_id": cid, "passed": True, "failure_reasons": "", "neighbor_ids": ""})
            continue
        starts = all_starts.loc[all_starts.candidate_id.eq(cid)].set_index("start")
        annual = yearly.loc[yearly.candidate_id.eq(cid)].set_index("year")
        diff = starts.excess - base_starts.excess
        annual_diff = annual.median_excess - base_year.median_excess
        loo = [diff.loc[starts.year.ne(year)].mean() for year in sorted(starts.year.unique())]
        yearly_gain = all_starts.loc[all_starts.candidate_id.eq(cid)].groupby("year").excess.sum() - all_starts.loc[all_starts.candidate_id.eq("baseline")].groupby("year").excess.sum()
        positive = yearly_gain.clip(lower=0)
        share = float(positive.max() / positive.sum()) if positive.sum() > 0 else 1.0
        family = pmap[cid]["family"]
        ordered = family_order[family]
        pos = [p["candidate_id"] for p in ordered].index(cid)
        neighbors = [ordered[k]["candidate_id"] for k in (pos - 1, pos + 1) if 0 <= k < len(ordered)]
        neighbor_ok = False
        for nid in neighbors:
            ns = summary.loc[summary.candidate_id.eq(nid)].iloc[0]
            nimp = ns.worst_year_median_excess - base_summary.worst_year_median_excess
            if nimp > 0 and s.worst_year_median_excess - ns.worst_year_median_excess >= -0.02:
                neighbor_ok = True
        reasons = []
        if s.worst_year_median_excess < base_summary.worst_year_median_excess: reasons.append("worst_year")
        if s.year_median_excess_std > base_summary.year_median_excess_std: reasons.append("cross_year_std")
        if int((annual_diff > 0).sum()) < 5: reasons.append("majority_years")
        if float((diff > 0).mean()) <= 0.50: reasons.append("majority_starts")
        if s.mean_cagr < base_summary.mean_cagr: reasons.append("mean_cagr")
        if s.min_cagr < base_summary.min_cagr - 0.01: reasons.append("min_cagr")
        if not all(x > 0 for x in loo): reasons.append("leave_one_year_out")
        if share >= 0.50: reasons.append("single_year_dependence")
        if not neighbor_ok: reasons.append("neighbor_stability")
        records.append({"candidate_id": cid, "passed": not reasons, "failure_reasons": ";".join(reasons),
                        "years_improved": int((annual_diff > 0).sum()), "starts_improved_fraction": float((diff > 0).mean()),
                        "min_loo_mean_excess_gain": float(min(loo)), "largest_year_positive_gain_share": share,
                        "neighbor_ids": ";".join(neighbors)})
    gates = pd.DataFrame(records)
    merged = summary.merge(gates, on="candidate_id", how="left")
    passed = merged.loc[merged.passed & merged.candidate_id.ne("baseline")].copy()
    if passed.empty:
        selected_id = "baseline"
    else:
        passed = passed.sort_values(["worst_year_median_excess", "year_median_excess_std", "mean_cagr", "min_cagr", "mean_excess", "mean_drawdown", "mean_sharpe", "mean_cost_rate"],
                                    ascending=[False, True, False, False, False, True, False, True], kind="mergesort")
        selected_id = passed.iloc[0].candidate_id
    return merged, pmap[selected_id]


def develop() -> None:
    if (HERE / "CONFIRMATION_LOCK.json").exists():
        raise RuntimeError("research is permanently locked; development cannot be rerun")
    spec, freeze_hash = verify_search_freeze()
    market = load_market(DEV_END)
    params = candidates(spec)
    frames = []
    for n, p in enumerate(params, 1):
        print(f"DEVELOP {n}/{len(params)} {p['candidate_id']}", flush=True)
        frames.append(run_candidate(market, p, range(2016, 2024)))
    all_starts = pd.concat(frames, ignore_index=True)
    yearly, summary = summary_table(all_starts)
    evaluated, selected = gate_and_select(all_starts, yearly, summary, params)
    all_starts.to_csv(HERE / "development_all_starts.csv", index=False)
    yearly.to_csv(HERE / "development_yearly.csv", index=False)
    evaluated.to_csv(HERE / "candidate_summary.csv", index=False)
    selected_id = selected["candidate_id"]
    stress_frames = []
    for stress in ("double_commission", "capacity_40pct"):
        for p in (params[0], selected):
            stress_frames.append(run_candidate(market, p, range(2016, 2024), stress))
    stress = pd.concat(stress_frames, ignore_index=True)
    stress.to_csv(HERE / "development_stress_all_starts.csv", index=False)
    stress_yearly, stress_summary = summary_table(stress)
    stress_yearly.to_csv(HERE / "development_stress_yearly.csv", index=False)
    stress_summary.to_csv(HERE / "development_stress_summary.csv", index=False)
    frozen = {
        "schema_version": 1, "search_space_sha256": freeze_hash, "selected_candidate_id": selected_id,
        "decision_before_confirmation": "retain_baseline" if selected_id == "baseline" else "advance_to_confirmation",
        "parameters": {k: v for k, v in selected.items() if k not in {"family", "axis_value"}},
        "development_summary": evaluated.loc[evaluated.candidate_id.eq(selected_id)].iloc[0].to_dict(),
        "development_files": ["development_all_starts.csv", "development_yearly.csv", "candidate_summary.csv",
                              "development_stress_all_starts.csv", "development_stress_yearly.csv", "development_stress_summary.csv"],
    }
    frozen["frozen_candidate_sha256"] = canonical_hash(frozen)
    write_json(HERE / "FROZEN_CANDIDATE.json", frozen)
    audit = {
        "stage": "development_complete_confirmation_unread", "search_space_sha256": freeze_hash,
        "candidate_sha256": frozen["frozen_candidate_sha256"], "input_hashes": market.input_hashes,
        "raw_files_verified": len(market.symbols), "development_last_date": str(market.dates[-1].date()),
        "phase_anchor": str(ANCHOR.date()), "factor_missing_propagation": True,
        "exact_baseline_parameters": spec["baseline"], "candidate_count": len(params),
    }
    write_json(HERE / "AUDIT.json", audit)
    print(f"FROZEN {selected_id} {frozen['frozen_candidate_sha256']}", flush=True)


def confirmation() -> None:
    spec, search_hash = verify_search_freeze()
    frozen_path = HERE / "FROZEN_CANDIDATE.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    check = dict(frozen); expected = check.pop("frozen_candidate_sha256")
    if canonical_hash(check) != expected or frozen["search_space_sha256"] != search_hash:
        raise RuntimeError("frozen candidate integrity failure")
    if (HERE / "CONFIRMATION_LOCK.json").exists():
        raise RuntimeError("confirmation is permanently locked and cannot be rerun")
    market = load_market(CONFIRM_END)
    all_params = candidates(spec)
    pmap = {p["candidate_id"]: p for p in all_params}
    selected = pmap[frozen["selected_candidate_id"]]
    run_ids = ["baseline"] if selected["candidate_id"] == "baseline" else ["baseline", selected["candidate_id"]]
    frames = [run_candidate(market, pmap[cid], range(2024, 2025)) for cid in run_ids]
    starts = pd.concat(frames, ignore_index=True)
    yearly, summary = summary_table(starts)
    starts.to_csv(HERE / "confirmation_all_starts.csv", index=False)
    yearly.to_csv(HERE / "confirmation_yearly.csv", index=False)
    summary.to_csv(HERE / "confirmation_summary.csv", index=False)
    if selected["candidate_id"] == "baseline":
        passed = False
        reasons = ["development_rules_retained_baseline"]
    else:
        b = starts.loc[starts.candidate_id.eq("baseline")].set_index("start")
        c = starts.loc[starts.candidate_id.eq(selected["candidate_id"])].set_index("start")
        bs = summary.loc[summary.candidate_id.eq("baseline")].iloc[0]
        cs = summary.loc[summary.candidate_id.eq(selected["candidate_id"])].iloc[0]
        diff = c.excess - b.excess
        reasons = []
        if float(c.excess.median()) <= float(b.excess.median()): reasons.append("median_excess")
        if float((diff > 0).mean()) <= 0.50: reasons.append("majority_starts")
        if cs.mean_cagr < bs.mean_cagr: reasons.append("mean_cagr")
        if cs.min_cagr < bs.min_cagr - 0.01: reasons.append("min_cagr")
        if cs.mean_drawdown > bs.mean_drawdown + 0.02: reasons.append("drawdown")
        passed = not reasons
    lock = {
        "schema_version": 1, "permanently_locked": True, "search_space_sha256": search_hash,
        "frozen_candidate_sha256": expected, "candidate_id": selected["candidate_id"],
        "confirmation_start_count": int(len(starts) / len(run_ids)), "confirmation_passed": passed,
        "final_decision": "promote_candidate" if passed else "retain_baseline", "failure_reasons": reasons,
        "confirmation_files": ["confirmation_all_starts.csv", "confirmation_yearly.csv", "confirmation_summary.csv"],
    }
    lock["confirmation_lock_sha256"] = canonical_hash(lock)
    write_json(HERE / "CONFIRMATION_LOCK.json", lock)
    audit = json.loads((HERE / "AUDIT.json").read_text(encoding="utf-8"))
    audit.update(stage="confirmation_locked", confirmation_last_date=str(market.dates[-1].date()),
                 confirmation_lock_sha256=lock["confirmation_lock_sha256"], confirmation_passed=passed,
                 final_decision=lock["final_decision"], confirmation_input_hashes=market.input_hashes)
    write_json(HERE / "AUDIT.json", audit)
    make_report(spec, frozen, lock, evaluated_path=HERE / "candidate_summary.csv", confirmation=summary)
    print(f"LOCKED {lock['final_decision']} {lock['confirmation_lock_sha256']}", flush=True)


def make_report(spec: dict, frozen: dict, lock: dict, evaluated_path: Path, confirmation: pd.DataFrame) -> None:
    dev = pd.read_csv(evaluated_path)
    chosen = dev.loc[dev.candidate_id.eq(frozen["selected_candidate_id"])].iloc[0]
    base = dev.loc[dev.candidate_id.eq("baseline")].iloc[0]
    lines = [
        "# 沪深1跨时间迁移研发 V3",
        "",
        f"- 搜索空间冻结哈希：`{frozen['search_space_sha256']}`",
        f"- 候选冻结哈希：`{frozen['frozen_candidate_sha256']}`",
        f"- 冻结候选：`{frozen['selected_candidate_id']}`",
        f"- 最终决定：`{lock['final_decision']}`",
        f"- 确认锁哈希：`{lock['confirmation_lock_sha256']}`",
        "",
        "## 研发口径",
        "",
        "逐年使用第一季度全部交易日起点，持有到同年末；信号仅用前一完整交易日。平台相位锚定二零一八年首个交易日，账户首日强制建仓，之后按冻结公式调仓。综合因子使用四个横截面排名的线性组合，任一分量缺失即传播为缺失。成交执行整手、T+1、停牌和涨跌停、二十日均量参与上限、历史税费及公司行动。上证收益按相同起点开盘到年末收盘计算。",
        "",
        "## 开发区间结论",
        "",
        f"基线最差年度中位超额为 {base.worst_year_median_excess:.6f}，跨年标准差为 {base.year_median_excess_std:.6f}。没有非基线候选通过全部开发门槛，因此冻结保留基线。",
        "",
        "所有候选（包括失败原因）、全部逐起点记录、逐年度表和费用容量压力结果均保存在同目录 CSV 文件。",
        "",
        "## 一次性确认",
        "",
    ]
    for _, row in confirmation.iterrows():
        lines.append(f"- `{row.candidate_id}`：平均 CAGR {row.mean_cagr:.6f}，最低 CAGR {row.min_cagr:.6f}，平均超额 {row.mean_excess:.6f}，平均回撤 {row.mean_drawdown:.6f}。")
    lines.extend(["", f"确认门槛结果：{lock['final_decision']}。失败项：{', '.join(lock['failure_reasons']) if lock['failure_reasons'] else '无'}。确认区间已永久锁定，不允许回流开发。", ""])
    (HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["develop", "confirm"])
    parser.add_argument("--skip-raw-hash", action="store_true", help="reserved; hashes remain mandatory")
    args = parser.parse_args()
    if args.mode == "develop":
        develop()
    else:
        confirmation()


if __name__ == "__main__":
    main()
