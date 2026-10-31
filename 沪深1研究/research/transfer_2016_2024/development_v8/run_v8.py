"""Frozen Hushen1 V8 multi-sleeve research on sanitized pre-2025 inputs only."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import stat
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
HOME = HERE.parents[2]
ROOT = HOME.parents[1]
INPUT = HERE.parent / "inputs_pre2025"
PROTOCOL = HERE.parent / "PROTOCOL_V8.md"
ENTRY = HOME / "supermind_hushen_1.py"
BACKTEST = HOME / "backtest"
SEARCH = HERE / "SEARCH_SPACE.md"
FREEZE = HERE / "FROZEN.json"
MANIFEST = INPUT / "PUBLIC_INPUT_MANIFEST.json"
INITIAL = 100_000.0
EXPOSURE = 0.98
INTERVAL = 20
BUFFER = 1.5
PARTICIPATION = 0.005
MAX_ORDER_SHARES = 1_000_000
ANCHOR = pd.Timestamp("2018-01-02")
MODELS = [
    "baseline",
    "factor_sleeves_k2",
    "factor_sleeves_k3",
    "vintage_sleeves_k2",
    "vintage_sleeves_k3",
    "mixed_sleeves_k2",
]
FACTORS = ("cap", "vol", "overnight", "intraday")
WEIGHTS = (-0.35, -0.20, 0.25, -0.20)
SOURCE_FILES = [
    PROTOCOL,
    ENTRY,
    BACKTEST / "engine.py",
    BACKTEST / "ledger.py",
    BACKTEST / "actions.py",
]
RESULT_FILES = {
    "all_starts.csv",
    "annual_summary.csv",
    "segment_summary.csv",
    "acceptance.json",
    "target_merge_audit.parquet",
    "execution_integrity.json",
    "pressure_all_starts.csv",
    "pressure_summary.csv",
    "report.md",
    "OUTPUT_HASHES.json",
    "PERMANENT_LOCK.json",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def frozen_material() -> dict:
    source_hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in SOURCE_FILES}
    return {
        "boundary_version": "public-pre2025-v2",
        "search_space_sha256": sha(SEARCH),
        "implementation_sha256": sha(Path(__file__)),
        "allowed_source_hashes": source_hashes,
        "input_manifest_sha256": sha(MANIFEST),
        "models": MODELS,
        "results_absent_at_freeze": sorted(name for name in RESULT_FILES if not (HERE / name).exists()),
    }


def freeze() -> None:
    if FREEZE.exists():
        raise RuntimeError("FROZEN.json already exists; V8 is immutable")
    present = sorted(name for name in RESULT_FILES if (HERE / name).exists())
    if present:
        raise RuntimeError("Result artifacts existed before freeze: " + repr(present))
    ast.parse(Path(__file__).read_text(encoding="utf-8"), filename=str(Path(__file__)))
    material = frozen_material()
    if material["results_absent_at_freeze"] != sorted(RESULT_FILES):
        raise RuntimeError("Freeze absence assertion failed")
    material["status"] = "frozen_before_results"
    write_json(FREEZE, material)
    print("FROZEN", material["search_space_sha256"], material["implementation_sha256"], flush=True)


def verify_freeze() -> dict:
    if not FREEZE.exists():
        raise RuntimeError("Run --freeze before --run")
    saved = json.loads(FREEZE.read_text(encoding="utf-8"))
    current = frozen_material()
    for key in ("boundary_version", "search_space_sha256", "implementation_sha256",
                "allowed_source_hashes", "input_manifest_sha256", "models"):
        if current[key] != saved[key]:
            raise RuntimeError(f"Frozen material changed: {key}")
    return saved


def verify_inputs() -> tuple[dict, pd.DatetimeIndex, pd.DataFrame]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "sanitized_pre2025_only"
    assert manifest["cutoff"] == "2024-12-31"
    fixed = {
        "calendar.csv": manifest["calendar_sha256"],
        "universe.csv": manifest["universe_sha256"],
        "sse_price_index.parquet": manifest["sse_index_sha256"],
        "actions_pre2025.json": manifest["actions_sha256"],
    }
    for name, expected in fixed.items():
        if sha(INPUT / name) != expected:
            raise RuntimeError("Input hash mismatch: " + name)
    for n, item in enumerate(manifest["files"], 1):
        if item["rows"] == 0:
            if not item.get("omitted_no_pre2025_rows"):
                raise RuntimeError("Zero-row input lacks omission marker: " + item["symbol"])
            continue
        path = HERE.parent / item["path"].replace("inputs_pre2025/", "inputs_pre2025/")
        if sha(path) != item["sha256"]:
            raise RuntimeError("Raw input hash mismatch: " + item["symbol"])
        if n % 500 == 0:
            print("HASH_INPUT", n, len(manifest["files"]), flush=True)
    calendar = pd.read_csv(INPUT / "calendar.csv")
    dates = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]))
    if dates.max() > pd.Timestamp("2024-12-31"):
        raise RuntimeError("Post-boundary calendar row")
    universe = pd.read_csv(INPUT / "universe.csv", dtype={"status": str})
    universe["ipoDate"] = pd.to_datetime(universe.ipoDate, errors="coerce")
    universe["outDate"] = pd.to_datetime(universe.outDate, errors="coerce")
    if set(universe.board) != {"main"}:
        raise RuntimeError("Non-main-board member in whitelist")
    return manifest, dates, universe


class ResearchData:
    def __init__(self, manifest: dict, dates: pd.DatetimeIndex, universe: pd.DataFrame):
        self.dates = dates
        self.date_to_i = {d: i for i, d in enumerate(dates)}
        records = [item for item in manifest["files"] if item["rows"] > 0]
        self.symbols = [item["symbol"] for item in records]
        self.paths = {item["symbol"]: HERE.parent / item["path"] for item in records}
        self.columns = {s: j for j, s in enumerate(self.symbols)}
        self.universe = universe.set_index("symbol").reindex(self.symbols)
        shape = (len(dates), len(self.symbols))
        self.present = np.zeros(shape, dtype=bool)
        self.raw = {name: np.full(shape, np.nan, dtype=np.float32) for name in
                    ("open", "high", "low", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST")}
        self.volume20 = np.full(shape, np.nan, dtype=np.float32)
        self.prev_actual = np.full(shape, np.nan, dtype=np.float32)
        for j, item in enumerate(records):
            path = self.paths[item["symbol"]]
            x = pd.read_parquet(path)
            x["date"] = pd.to_datetime(x.date)
            observed_end = str(x.date.max().date()) if len(x) else None
            if len(x) != item["rows"] or observed_end != item.get("end"):
                raise RuntimeError("Manifest row/date mismatch: " + item["symbol"])
            x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
            if len(x) and x.index.max() > pd.Timestamp("2024-12-31"):
                raise RuntimeError("Post-boundary raw row: " + item["symbol"])
            ix = dates.get_indexer(x.index)
            ok = ix >= 0
            ix = ix[ok]
            y = x.iloc[np.flatnonzero(ok)]
            for name in self.raw:
                self.raw[name][ix, j] = pd.to_numeric(y[name], errors="raise").to_numpy(dtype=np.float32)
            volume = pd.to_numeric(x.volume, errors="raise")
            self.volume20[ix, j] = volume.rolling(20).mean().iloc[np.flatnonzero(ok)].to_numpy(dtype=np.float32)
            self.prev_actual[ix, j] = pd.to_numeric(x.close, errors="raise").shift().iloc[np.flatnonzero(ok)].to_numpy(dtype=np.float32)
            self.present[ix, j] = True
            if (j + 1) % 400 == 0:
                print("LOAD_INPUT", j + 1, len(self.symbols), flush=True)
        self.outs = {s: d for s, d in self.universe.outDate.items() if pd.notna(d)}
        self.actions_raw = json.loads((INPUT / "actions_pre2025.json").read_text(encoding="utf-8"))
        self.actions, self.action_keys = self._parse_actions()
        self.benchmark = pd.read_parquet(INPUT / "sse_price_index.parquet")
        self.benchmark["date"] = pd.to_datetime(self.benchmark.date)
        self.benchmark = self.benchmark.set_index("date").sort_index()
        if self.benchmark.index.max() > pd.Timestamp("2024-12-31"):
            raise RuntimeError("Post-boundary benchmark row")

    def _parse_actions(self):
        events = {}
        for key, records in self.actions_raw.items():
            symbol, year = key.split("/")
            for record in records:
                if not record.get("dividOperateDate"):
                    continue
                date = pd.Timestamp(record["dividOperateDate"])
                if date > pd.Timestamp("2024-12-31"):
                    raise RuntimeError("Post-boundary action")
                def num(name):
                    value = str(record.get(name, "")).strip()
                    return float(value) if value else 0.0
                events[symbol, date] = {
                    "cash": num("dividCashPsBeforeTax"),
                    "stock": num("dividStocksPs") + num("dividReserveToStockPs"),
                    "taxable_stock": num("dividStocksPs"),
                    "pay": pd.Timestamp(record.get("dividPayDate") or record["dividOperateDate"]),
                    "release": pd.Timestamp(record.get("dividStockMarketDate") or record["dividOperateDate"]),
                }
        return events, set(self.actions_raw)

    @lru_cache(maxsize=200_000)
    def row(self, i: int, symbol: str):
        j = self.columns.get(symbol)
        if j is None or not self.present[i, j]:
            return None
        return NS(**{name: float(values[i, j]) for name, values in self.raw.items()},
                  volume20=float(self.volume20[i, j]), prev_actual=float(self.prev_actual[i, j]))


def build_rankings(data: ResearchData) -> dict[str, dict[str, list[str]]]:
    dates, symbols = data.dates, data.symbols
    shape = data.present.shape
    eligible = np.zeros(shape, dtype=bool)
    values = {name: np.full(shape, np.nan, dtype=np.float32) for name in FACTORS}
    ipo = data.universe.ipoDate.to_numpy()
    out = data.universe.outDate.to_numpy()
    for j, symbol in enumerate(symbols):
        x = pd.read_parquet(data.paths[symbol])
        if x.empty:
            continue
        x["date"] = pd.to_datetime(x.date)
        x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        x = x[["open", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST"]].astype(float)
        rows = dates.get_indexer(x.index)
        valid = rows >= 0
        rows = rows[valid]
        x = x.iloc[np.flatnonzero(valid)]
        close, pre, op = x.close, x.preclose, x.open
        volume, amount, turn, status, is_st = x.volume, x.amount, x.turn, x.tradestatus, x.isST
        ret = (close / pre - 1).where((status == 1) & (pre > 0), 0.0)
        vol = ret.rolling(60).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight = np.log(op / pre).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(close / op).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        cap = close * volume / (turn / 100).replace(0, np.nan)
        age = pd.Series(np.arange(len(close)) + 1, index=close.index)
        ok = ((age >= 252) & (amount.rolling(20).mean() >= 1e7) & (close >= 2) &
              (is_st == 0) & (status == 1) & (vol > .001) & (vol < .09))
        if pd.notna(ipo[j]):
            ok &= ok.index >= pd.Timestamp(ipo[j])
        if pd.notna(out[j]):
            ok &= ok.index < pd.Timestamp(out[j])
        for name, series in (("cap", cap), ("vol", vol), ("overnight", overnight), ("intraday", intraday)):
            values[name][rows, j] = series.to_numpy(dtype=np.float32)
        eligible[rows, j] = ok.to_numpy(dtype=bool)
        if (j + 1) % 400 == 0:
            print("FEATURE", j + 1, len(symbols), flush=True)
    ranked = {}
    for name in FACTORS:
        frame = pd.DataFrame(values[name], index=dates, columns=symbols).where(eligible)
        ranked[name] = frame.rank(axis=1, pct=True, method="average").astype(np.float32)
        del frame, values[name]
        print("RANK", name, flush=True)
    complete = np.ones(shape, dtype=bool)
    combined = np.zeros(shape, dtype=np.float32)
    directional = {}
    for name, weight in zip(FACTORS, WEIGHTS):
        array = ranked[name].to_numpy(dtype=np.float32, copy=False)
        complete &= np.isfinite(array)
        combined += np.nan_to_num(array, nan=0.0) * np.float32(weight)
        direction = 1.0 if name == "overnight" else -1.0
        directional[name] = pd.DataFrame(array * np.float32(direction), index=dates, columns=symbols).rolling(
            5, min_periods=3).mean().where(eligible)
    combined[~complete] = np.nan
    composite = pd.DataFrame(combined, index=dates, columns=symbols).rolling(5, min_periods=3).mean().where(eligible)
    outputs = {"composite": {}, **{name: {} for name in FACTORS}}
    needed = dates[dates >= pd.Timestamp("2015-11-01")]
    for n, date in enumerate(needed, 1):
        outputs["composite"][str(date.date())] = composite.loc[date].dropna().sort_values(
            ascending=False, kind="mergesort").head(100).index.tolist()
        for name in FACTORS:
            outputs[name][str(date.date())] = directional[name].loc[date].dropna().sort_values(
                ascending=False, kind="mergesort").head(100).index.tolist()
        if n % 250 == 0:
            print("RANK_DATE", n, len(needed), flush=True)
    return outputs


@dataclass
class Scenario:
    name: str
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    participation: float = PARTICIPATION


class Account:
    def __init__(self, data: ResearchData, rankings: dict, model: str, start: pd.Timestamp,
                 end: pd.Timestamp, scenario: Scenario):
        self.data, self.rankings, self.model = data, rankings, model
        self.start, self.end, self.scenario = start, end, scenario
        self.cash = INITIAL
        self.holdings = {}
        self.receivables = []
        self.targets = {}
        self.sleeve_selected = {}
        self.previous_close_shares = {}
        self.trades = []
        self.curve = []
        self.issues = {}
        self.reference_diffs = {}
        self.action_key_missing = set()
        self.target_audit = []
        self.capacity_hits = 0
        self.fees = 0.0
        self.dividend_tax = 0.0
        self.first = True

    def available(self, symbol, date):
        return sum(lot["q"] for lot in self.holdings[symbol]["lots"]
                   if lot["release"] <= date and lot["buy"] < date)

    def _corporate(self, date, i):
        pending = []
        for pay, amount in self.receivables:
            if pay <= date:
                self.cash += amount
            else:
                pending.append((pay, amount))
        self.receivables = pending
        for symbol, position in list(self.holdings.items()):
            row = self.data.row(i, symbol)
            action = self.data.actions.get((symbol, date))
            key = f"{symbol}/{date.year}"
            if key not in self.data.action_keys:
                self.action_key_missing.add(key)
            if action:
                old = position["qty"]
                amount = old * action["cash"]
                if action["pay"] <= date:
                    self.cash += amount
                else:
                    self.receivables.append((action["pay"], amount))
                additions = []
                remaining = int(math.floor(old * action["stock"] + 1e-8))
                original_lots = list(position["lots"])
                for j, lot in enumerate(original_lots):
                    bonus = min(remaining, int(math.floor(lot["q"] * action["stock"] + 1e-8)))
                    if j == len(original_lots) - 1:
                        bonus = remaining
                    remaining -= bonus
                    taxable = action["cash"] + action["taxable_stock"] if date <= lot["buy"] + pd.DateOffset(years=1) else 0.0
                    liability = lot["div"] + taxable
                    adjusted = liability * lot["q"] / (lot["q"] + bonus)
                    lot["div"] = adjusted
                    if bonus:
                        additions.append({"q": bonus, "buy": lot["buy"], "release": action["release"], "div": adjusted})
                position["lots"].extend(additions)
                position["lots"].sort(key=lambda lot: (lot["buy"], lot["release"]))
                position["qty"] = sum(lot["q"] for lot in position["lots"])
                if row is not None:
                    position["last"] = row.preclose
                    expected = (row.prev_actual - action["cash"]) / (1 + action["stock"])
                    if abs(row.preclose - expected) > max(.025, row.preclose * .0001):
                        self.reference_diffs[f"{symbol}/{date.date()}"] = [row.prev_actual, row.preclose, action]
            if row is not None and np.isfinite(row.prev_actual) and row.prev_actual > 0:
                ratio = row.preclose / row.prev_actual
                if abs(ratio - 1) > 1e-5 and not action:
                    self.issues[f"{symbol}/{date.date()}"] = float(ratio)
            out = self.data.outs.get(symbol)
            if out is not None and date >= out:
                self.issues[f"{symbol}/{date.date()}"] = "delisting zero-recovery assumption"
                del self.holdings[symbol]
        for symbol, old in self.previous_close_shares.items():
            now = self.holdings.get(symbol, {}).get("qty", 0)
            if old > 0 and now > 0 and old != now and symbol in self.targets:
                self.targets[symbol] = int(math.floor(self.targets[symbol] * now / old + 1e-8))

    @staticmethod
    def _limit(row, buy):
        pct = .05 if row.isST else .10
        high_limit = math.floor(row.preclose * (1 + pct) * 100 + .5) / 100
        low_limit = math.floor(row.preclose * (1 - pct) * 100 + .5) / 100
        if buy:
            value = min(high_limit, row.open * 1.001)
            return min(high_limit, math.ceil(value * 100 - 1e-8) / 100), high_limit, low_limit
        value = max(low_limit, row.open * .999)
        return max(low_limit, math.floor(value * 100 + 1e-8) / 100), high_limit, low_limit

    def _valid_bar(self, row):
        if row is None or row.tradestatus != 1 or not np.isfinite(row.open) or row.open <= 0:
            return False
        _, high, low = self._limit(row, True)
        return 0 < low <= row.open <= high and row.volume > 0

    def _buy_cost_buffer(self, quantity, op):
        value = quantity * (op * 1.001 + .01)
        return value + max(self.scenario.min_commission, value * self.scenario.commission_rate) + value * .00002

    def _sleeves(self, signal_i):
        k = 5 if self.model == "baseline" else (3 if self.model.endswith("k3") else 2)
        signal_key = str(self.data.dates[signal_i].date())
        if self.model == "baseline":
            return [("composite", 1.0, k, self.rankings["composite"][signal_key])]
        if self.model.startswith("factor_sleeves"):
            return [(name, .25, k, self.rankings[name][signal_key]) for name in FACTORS]
        if self.model.startswith("vintage_sleeves"):
            return [(f"vintage_{lag}", .25, k,
                     self.rankings["composite"][str(self.data.dates[signal_i - lag].date())])
                    for lag in (0, 5, 10, 15)]
        if self.model == "mixed_sleeves_k2":
            return [("composite", .50, 2, self.rankings["composite"][signal_key])] + [
                (name, .125, 2, self.rankings[name][signal_key]) for name in FACTORS]
        raise ValueError(self.model)

    def _rebalance(self, date, i, signal_i, nav):
        positions = set(self.holdings)
        pieces = {}
        detail = {}
        for sleeve, weight, k, ranking in self._sleeves(signal_i):
            budget = nav * EXPOSURE * weight / k
            keep = set(ranking[:int(k * BUFFER)])
            prior = self.sleeve_selected.get(sleeve, set())
            def can_select(symbol):
                row = self.data.row(i, symbol)
                if not self._valid_bar(row) or row.isST or row.open >= self._limit(row, True)[1] - 1e-8:
                    return False
                return self._buy_cost_buffer(100, row.open) <= budget
            if self.model == "baseline":
                retained_pool = positions
            else:
                retained_pool = prior & positions
            selected = [s for s in ranking if s in retained_pool and s in keep and can_select(s)][:k]
            for symbol in ranking:
                if len(selected) >= k:
                    break
                if symbol not in selected and can_select(symbol):
                    selected.append(symbol)
            self.sleeve_selected[sleeve] = set(selected)
            for symbol in selected:
                pieces[symbol] = pieces.get(symbol, 0.0) + budget
                detail.setdefault(symbol, []).append({"sleeve": sleeve, "target_amount": budget})
        targets = {symbol: 0 for symbol in positions if symbol not in pieces}
        for symbol, amount in pieces.items():
            row = self.data.row(i, symbol)
            targets[symbol] = int(amount / row.open / 100) * 100
            self.target_audit.append({
                "model": self.model, "requested_start": str(self.start.date()), "date": str(date.date()),
                "symbol": symbol, "sleeve_count": len(detail[symbol]),
                "sleeves": ";".join(item["sleeve"] for item in detail[symbol]),
                "target_amount_sum": amount, "target_shares": targets[symbol],
            })
        self.targets = targets
        self.first = False

    def _order(self, date, i, symbol, quantity, limit, high_limit, low_limit):
        row = self.data.row(i, symbol)
        if row is None or row.tradestatus != 1 or row.volume <= 0:
            return False
        cap = int(row.volume * .25 / 100) * 100
        if abs(quantity) > cap:
            self.capacity_hits += 1
            return False
        if quantity > 0:
            proposed = min(limit, row.open * 1.001, row.high, high_limit)
            if row.open >= high_limit - 1e-8 or limit < row.open - 1e-8 or proposed < max(row.low, low_limit) - 1e-8:
                return False
        else:
            proposed = max(limit, row.open * .999, row.low, low_limit)
            if row.open <= low_limit + 1e-8 or limit > row.open + 1e-8 or proposed > min(row.high, high_limit) + 1e-8:
                return False
        price = round(float(proposed), 2)
        if (quantity > 0 and price > limit + 1e-8) or (quantity < 0 and price < limit - 1e-8):
            return False
        value = round(abs(quantity) * price, 2)
        commission = round(max(self.scenario.min_commission, value * self.scenario.commission_rate), 2)
        transfer = round(value * (.00002 if date < pd.Timestamp("2022-04-29") else .00001), 2)
        stamp = round(value * (.001 if date < pd.Timestamp("2023-08-28") else .0005), 2) if quantity < 0 else 0.0
        fees = commission + transfer + stamp
        divtax = 0.0
        if quantity > 0:
            if value + fees > self.cash + 1e-6 or quantity % 100:
                return False
            self.cash -= value + fees
            position = self.holdings.setdefault(symbol, {"qty": 0, "last": price, "lots": []})
            position["qty"] += quantity
            position["lots"].append({"q": quantity, "buy": date, "release": date + pd.Timedelta(days=1), "div": 0.0})
        else:
            if symbol not in self.holdings or -quantity > self.available(symbol, date):
                return False
            position = self.holdings[symbol]
            remaining = -quantity
            for lot in position["lots"]:
                if lot["release"] > date or lot["buy"] >= date:
                    continue
                q = min(remaining, lot["q"])
                remaining -= q
                lot["q"] -= q
                rate = .2 if date <= lot["buy"] + pd.DateOffset(months=1) else (.1 if date <= lot["buy"] + pd.DateOffset(years=1) else 0.0)
                divtax += q * lot["div"] * rate
                if remaining == 0:
                    break
            if remaining:
                return False
            divtax = round(divtax, 2)
            position["lots"] = [lot for lot in position["lots"] if lot["q"]]
            position["qty"] += quantity
            self.cash += value - fees - divtax
            if not position["qty"]:
                del self.holdings[symbol]
        self.fees += fees
        self.dividend_tax += divtax
        self.trades.append({"date": str(date.date()), "symbol": symbol, "qty": quantity, "price": price,
                            "commission": commission, "transfer": transfer, "stamp": stamp,
                            "dividend_tax": divtax})
        return True

    def run(self):
        dates = self.data.dates
        start_i, end_i = self.data.date_to_i[self.start], self.data.date_to_i[self.end]
        anchor_i = self.data.date_to_i[ANCHOR]
        for i in range(start_i, end_i + 1):
            date = dates[i]
            self._corporate(date, i)
            nav = self.cash + sum(amount for pay, amount in self.receivables)
            for symbol, position in self.holdings.items():
                row = self.data.row(i, symbol)
                nav += position["qty"] * (row.open if self._valid_bar(row) else position["last"])
            shifted = i - anchor_i
            rebalance = self.first or (shifted - 1) % INTERVAL == 0
            if rebalance:
                self._rebalance(date, i, i - 1, nav)
            for symbol in list(self.holdings):
                prev = self.data.row(i - 1, symbol)
                if prev is not None and prev.isST:
                    self.targets[symbol] = 0
            positions = set(self.holdings)
            keys = sorted(self.targets, key=lambda s: (self.targets[s] - self.holdings.get(s, {}).get("qty", 0) >= 0, s))
            cash_budget = self.cash
            for symbol in keys:
                current = self.holdings.get(symbol, {}).get("qty", 0)
                delta = self.targets[symbol] - current
                row = self.data.row(i, symbol)
                if delta == 0 or not self._valid_bar(row):
                    continue
                prev = self.data.row(i - 1, symbol)
                if prev is None or not np.isfinite(prev.volume20):
                    continue
                limit, high_limit, low_limit = self._limit(row, delta > 0)
                cap = min(int(prev.volume20 * self.scenario.participation / 100) * 100, MAX_ORDER_SHARES)
                quantity = min(abs(delta), cap)
                if delta < 0:
                    if row.open <= low_limit + 1e-8:
                        continue
                    quantity = min(quantity, self.available(symbol, date))
                    if quantity != current:
                        quantity = int(quantity // 100) * 100
                    before = self.cash
                    if quantity > 0 and self._order(date, i, symbol, -int(quantity), limit, high_limit, low_limit):
                        cash_budget += max(0.0, self.cash - before)
                else:
                    if row.isST or row.open >= high_limit - 1e-8:
                        continue
                    quantity = int(quantity // 100) * 100
                    available_cash = min(cash_budget, self.cash)
                    while quantity > 0 and self._buy_cost_buffer(quantity, row.open) > available_cash:
                        quantity -= 100
                    if quantity > 0 and self._order(date, i, symbol, int(quantity), limit, high_limit, low_limit):
                        cash_budget -= self._buy_cost_buffer(quantity, row.open)
            market_value = 0.0
            for symbol, position in self.holdings.items():
                row = self.data.row(i, symbol)
                if row is not None and row.close > 0:
                    position["last"] = row.close
                market_value += position["qty"] * position["last"]
                if position["qty"] != sum(lot["q"] for lot in position["lots"]):
                    raise RuntimeError("Lot mismatch")
            equity = self.cash + market_value + sum(amount for pay, amount in self.receivables)
            if self.cash < -.01:
                raise RuntimeError("Negative cash")
            self.curve.append({"date": date, "equity": equity, "exposure": market_value / equity if equity else np.nan})
            self.previous_close_shares = {s: p["qty"] for s, p in self.holdings.items()}
        return self.metrics()

    def metrics(self):
        frame = pd.DataFrame(self.curve)
        nav = frame.equity.to_numpy()
        returns = nav / np.r_[INITIAL, nav[:-1]] - 1
        days = (self.end - self.start).days + 1
        cagr = float((nav[-1] / INITIAL) ** (365.25 / days) - 1)
        bench = self.data.benchmark
        bench_cagr = float((float(bench.loc[self.end, "close"]) / float(bench.loc[self.start, "open"])) ** (365.25 / days) - 1)
        return {
            "model": self.model, "scenario": self.scenario.name, "requested_start": str(self.start.date()),
            "year": self.start.year, "end": str(self.end.date()), "final_equity": float(nav[-1]),
            "total_return": float(nav[-1] / INITIAL - 1), "cagr": cagr, "benchmark_cagr": bench_cagr,
            "excess_cagr": cagr - bench_cagr,
            "max_drawdown": float((1 - nav / np.maximum.accumulate(np.r_[INITIAL, nav])[1:]).max()),
            "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else np.nan,
            "trades": len(self.trades), "transaction_fees": self.fees,
            "dividend_tax": self.dividend_tax, "total_cost": self.fees + self.dividend_tax,
            "average_exposure": float(frame.exposure.mean()), "capacity_hits": self.capacity_hits,
            "unexplained_adjustments": len(self.issues), "action_reference_differences": len(self.reference_diffs),
            "missing_action_year_keys": len(self.action_key_missing),
        }


def simulate_set(data, rankings, models, scenario, collect_targets=True):
    records, targets, integrity = [], [], {}
    for model in models:
        model_issues, model_reference, model_missing = set(), set(), set()
        starts_done = 0
        for year in range(2016, 2025):
            year_dates = data.dates[data.dates.year == year]
            starts = year_dates[year_dates.quarter == 1]
            end = year_dates[-1]
            for start in starts:
                account = Account(data, rankings, model, start, end, scenario)
                record = account.run()
                records.append(record)
                if collect_targets:
                    targets.extend(account.target_audit)
                model_issues.update(account.issues)
                model_reference.update(account.reference_diffs)
                model_missing.update(account.action_key_missing)
                starts_done += 1
            print("SIM", scenario.name, model, year, len(starts), flush=True)
        integrity[model] = {
            "status": "pass" if not model_issues and not model_reference else "fail",
            "unexplained_adjustments": sorted(model_issues),
            "action_reference_differences": sorted(model_reference),
            "missing_action_year_keys_observed": sorted(model_missing),
            "starts": starts_done,
        }
    return pd.DataFrame(records), pd.DataFrame(targets), integrity


def evaluate(results: pd.DataFrame, integrity: dict):
    annual = results.groupby(["model", "year"], as_index=False).agg(
        starts=("requested_start", "size"), median_excess=("excess_cagr", "median"),
        mean_excess=("excess_cagr", "mean"), mean_cagr=("cagr", "mean"),
        minimum_cagr=("cagr", "min"), mean_drawdown=("max_drawdown", "mean"),
        mean_sharpe=("sharpe", "mean"), mean_cost=("total_cost", "mean"))
    baseline = results.loc[results.model.eq("baseline")].set_index("requested_start")
    decisions = {}
    dual_segment = {}
    segments = []
    for model in MODELS:
        sub = results.loc[results.model.eq(model)].copy()
        ann = annual.loc[annual.model.eq(model)].set_index("year")
        matched = sub.set_index("requested_start").join(
            baseline[["excess_cagr", "cagr"]], rsuffix="_baseline")
        matched["excess_improvement"] = matched.excess_cagr - matched.excess_cagr_baseline
        matched["cagr_delta"] = matched.cagr - matched.cagr_baseline
        segment_rows = []
        for label, years in (("2016-2019", range(2016, 2020)), ("2020-2024", range(2020, 2025))):
            x = matched.loc[matched.year.isin(years)]
            b = baseline.loc[baseline.year.isin(years)]
            row = {
                "model": model, "segment": label, "mean_excess": float(x.excess_cagr.mean()),
                "baseline_mean_excess": float(b.excess_cagr.mean()),
                "excess_improvement": float(x.excess_improvement.mean()),
                "mean_cagr": float(x.cagr.mean()), "baseline_mean_cagr": float(b.cagr.mean()),
                "cagr_delta": float(x.cagr_delta.mean()),
            }
            segments.append(row)
            segment_rows.append(row)
        dual_segment[model] = all(row["excess_improvement"] > 0 for row in segment_rows)
        yearly_median = ann.median_excess
        baseline_ann = annual.loc[annual.model.eq("baseline")].set_index("year")
        year_improvement = matched.groupby("year").excess_improvement.agg(["mean", lambda x: float((x > 0).mean())])
        year_improvement.columns = ["mean", "positive_fraction"]
        total_improvement = float(year_improvement["mean"].sum())
        positive_total = float(year_improvement["mean"].clip(lower=0).sum())
        max_contribution = (float(year_improvement["mean"].clip(lower=0).max() / positive_total)
                            if positive_total > 0 else float("inf"))
        loo = {str(year): float(year_improvement.loc[year_improvement.index != year, "mean"].mean())
               for year in year_improvement.index}
        gates = {
            "nine_year_median_excess_positive": bool((yearly_median > 0).all() and len(yearly_median) == 9),
            "both_segment_excess_above_baseline": bool(dual_segment[model]),
            "both_segment_cagr_decline_within_2pp": bool(all(row["cagr_delta"] >= -.02 for row in segment_rows)),
            "at_least_seven_years_majority_start_improvement": bool((year_improvement.positive_fraction > .5).sum() >= 7),
            "yearly_median_excess_std_not_above_baseline": bool(yearly_median.std(ddof=1) <= baseline_ann.median_excess.std(ddof=1) + 1e-15),
            "all_leave_one_year_out_improvement_positive": bool(all(value > 0 for value in loo.values())),
            "single_year_positive_contribution_below_half": bool(max_contribution < .5),
            "execution_integrity": integrity[model]["status"] == "pass",
        }
        decisions[model] = {
            "gates": gates, "yearly_median_excess": {str(k): float(v) for k, v in yearly_median.items()},
            "yearly_improvement_mean": {str(k): float(v) for k, v in year_improvement["mean"].items()},
            "yearly_improvement_positive_fraction": {str(k): float(v) for k, v in year_improvement["positive_fraction"].items()},
            "leave_one_year_out_mean_improvement": loo, "max_single_year_positive_contribution": max_contribution,
            "total_year_improvement_sum": total_improvement,
        }
    for model in ("factor_sleeves_k2", "factor_sleeves_k3"):
        decisions[model]["gates"]["same_structure_k2_k3_dual_segment_support"] = (
            dual_segment["factor_sleeves_k2"] and dual_segment["factor_sleeves_k3"])
    for model in ("vintage_sleeves_k2", "vintage_sleeves_k3"):
        decisions[model]["gates"]["same_structure_k2_k3_dual_segment_support"] = (
            dual_segment["vintage_sleeves_k2"] and dual_segment["vintage_sleeves_k3"])
    decisions["mixed_sleeves_k2"]["gates"]["both_component_families_supported"] = (
        any(dual_segment[m] for m in ("factor_sleeves_k2", "factor_sleeves_k3")) and
        any(dual_segment[m] for m in ("vintage_sleeves_k2", "vintage_sleeves_k3")))
    for model in MODELS:
        decisions[model]["passed"] = model != "baseline" and all(decisions[model]["gates"].values())
        decisions[model]["failed_gates"] = [key for key, value in decisions[model]["gates"].items() if not value]
    passing = [model for model in MODELS[1:] if decisions[model]["passed"]]
    for model in passing:
        ann = annual.loc[annual.model.eq(model)]
        segment_min = min(row["excess_improvement"] for row in segments if row["model"] == model)
        sub = results.loc[results.model.eq(model)]
        decisions[model]["ranking_key"] = [
            float(ann.median_excess.min()), float(segment_min), -float(ann.median_excess.std(ddof=1)),
            float(sub.cagr.mean()), float(sub.cagr.min()), -float(sub.max_drawdown.mean()),
            float(sub.sharpe.mean()), -float(sub.total_cost.mean())]
    passing.sort(key=lambda model: tuple(decisions[model]["ranking_key"]), reverse=True)
    candidates = MODELS[1:]
    def closest_key(model):
        medians = decisions[model]["yearly_median_excess"].values()
        shortfall = sum(-min(value, 0.0) for value in medians)
        return (shortfall, -min(medians), candidates.index(model))
    closest = min(candidates, key=closest_key)
    return annual, pd.DataFrame(segments), {
        "protocol": "V8", "baseline_retained": not bool(passing), "passing_candidates_ranked": passing,
        "closest_hard_gate_candidate": closest, "dual_segment_improvement": dual_segment,
        "models": decisions,
    }


def pressure(data, rankings, selected):
    rows, audits = [], {}
    for scenario in (Scenario("double_commission", .0006, 10.0, PARTICIPATION),
                     Scenario("capacity_40pct", .0003, 5.0, PARTICIPATION * .4)):
        frame, _, integrity = simulate_set(data, rankings, selected, scenario, collect_targets=False)
        rows.append(frame)
        audits[scenario.name] = integrity
    detail = pd.concat(rows, ignore_index=True)
    summary = detail.groupby(["scenario", "model"], as_index=False).agg(
        starts=("requested_start", "size"), mean_cagr=("cagr", "mean"),
        median_cagr=("cagr", "median"), mean_excess=("excess_cagr", "mean"),
        minimum_excess=("excess_cagr", "min"), mean_drawdown=("max_drawdown", "mean"),
        mean_cost=("total_cost", "mean"), capacity_hits=("capacity_hits", "sum"))
    return detail, summary, audits


def report_text(annual, segments, acceptance, integrity, pressure_summary, freeze_data):
    lines = ["# 沪深1 V8 冻结多袖套研发结果", "",
             f"- 搜索空间哈希：`{freeze_data['search_space_sha256']}`",
             f"- 实现哈希：`{freeze_data['implementation_sha256']}`",
             "- 数据边界：2013—2015预热，2016—2024研发评价；仅使用`inputs_pre2025/`。", ""]
    passing = acceptance["passing_candidates_ranked"]
    lines.append("结论：" + ("通过者依次为 " + "、".join(passing) if passing else "没有候选通过全部冻结门槛，保留精确基线。"))
    lines += ["", "## 候选判定", "", "| 模型 | 通过 | 失败门槛 | 执行完整性 |", "|---|---:|---|---|"]
    for model in MODELS:
        item = acceptance["models"][model]
        lines.append(f"| {model} | {'是' if item['passed'] else '否'} | {', '.join(item['failed_gates']) or '-'} | {integrity[model]['status']} |")
    lines += ["", "## 逐年中位年化超额", "", "| 模型 | " + " | ".join(map(str, range(2016, 2025))) + " |",
              "|---|" + "---:|" * 9]
    for model in MODELS:
        values = annual.loc[annual.model.eq(model)].set_index("year").median_excess
        lines.append("| " + model + " | " + " | ".join(f"{values.loc[y]:.2%}" for y in range(2016, 2025)) + " |")
    lines += ["", "## 分段", "", "| 模型 | 分段 | 平均超额 | 基线平均超额 | 超额改善 | 年化相对基线 |", "|---|---|---:|---:|---:|---:|"]
    for row in segments.itertuples(index=False):
        lines.append(f"| {row.model} | {row.segment} | {row.mean_excess:.2%} | {row.baseline_mean_excess:.2%} | {row.excess_improvement:.2%} | {row.cagr_delta:.2%} |")
    lines += ["", "## 压力测试", "", "| 场景 | 模型 | 起点数 | 平均年化 | 平均超额 | 平均回撤 | 平均费用 | 容量拒单 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in pressure_summary.itertuples(index=False):
        lines.append(f"| {row.scenario} | {row.model} | {row.starts} | {row.mean_cagr:.2%} | {row.mean_excess:.2%} | {row.mean_drawdown:.2%} | {row.mean_cost:.2f} | {int(row.capacity_hits)} |")
    lines.append("")
    return "\n".join(lines)


def lock_outputs(freeze_data):
    files = [p for p in HERE.rglob("*") if p.is_file() and p.name not in ("PERMANENT_LOCK.json", "OUTPUT_HASHES.json")]
    hashes = {str(p.relative_to(HERE)).replace("\\", "/"): sha(p) for p in sorted(files)}
    write_json(HERE / "OUTPUT_HASHES.json", {"files": hashes})
    hashes["OUTPUT_HASHES.json"] = sha(HERE / "OUTPUT_HASHES.json")
    write_json(HERE / "PERMANENT_LOCK.json", {
        "status": "permanently_locked", "boundary_version": "public-pre2025-v2",
        "search_space_sha256": freeze_data["search_space_sha256"],
        "implementation_sha256": freeze_data["implementation_sha256"], "files": hashes})
    for path in HERE.rglob("*"):
        if path.is_file():
            os.chmod(path, stat.S_IREAD)


def run():
    freeze_data = verify_freeze()
    unexpected = sorted(name for name in RESULT_FILES if (HERE / name).exists())
    if unexpected:
        raise RuntimeError("Frozen V8 outputs already exist: " + repr(unexpected))
    manifest, dates, universe = verify_inputs()
    data = ResearchData(manifest, dates, universe)
    rankings = build_rankings(data)
    results, targets, integrity = simulate_set(data, rankings, MODELS, Scenario("base"))
    annual, segments, acceptance = evaluate(results, integrity)
    pressure_models = acceptance["passing_candidates_ranked"]
    if pressure_models:
        pressure_models = ["baseline"] + pressure_models
    else:
        pressure_models = ["baseline", acceptance["closest_hard_gate_candidate"]]
    pressure_detail, pressure_summary, pressure_integrity = pressure(data, rankings, pressure_models)
    results.to_csv(HERE / "all_starts.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(HERE / "annual_summary.csv", index=False, encoding="utf-8-sig")
    segments.to_csv(HERE / "segment_summary.csv", index=False, encoding="utf-8-sig")
    targets.to_parquet(HERE / "target_merge_audit.parquet", index=False)
    write_json(HERE / "execution_integrity.json", {"base": integrity, "pressure": pressure_integrity})
    write_json(HERE / "acceptance.json", acceptance)
    pressure_detail.to_csv(HERE / "pressure_all_starts.csv", index=False, encoding="utf-8-sig")
    pressure_summary.to_csv(HERE / "pressure_summary.csv", index=False, encoding="utf-8-sig")
    (HERE / "report.md").write_text(report_text(annual, segments, acceptance, integrity, pressure_summary, freeze_data), encoding="utf-8")
    lock_outputs(freeze_data)
    print("COMPLETE", HERE, flush=True)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    freeze() if args.freeze else run()


if __name__ == "__main__":
    main()
