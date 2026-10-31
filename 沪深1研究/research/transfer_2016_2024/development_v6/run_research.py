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
DEV_END = pd.Timestamp("2024-12-31")
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
    base["weights"] = dict(base["weights"])
    result = [{"candidate_id": "baseline", "family": "baseline", "axis_value": None, **base}]
    for family, changes in spec["candidate_families"].items():
        for value in changes:
            row = dict(base)
            row["weights"] = dict(base["weights"])
            if "weights" in value:
                row["weights"].update(value["weights"])
                axis = float(next(iter(value["weights"].values())))
            else:
                row.update(value)
                if "breadth_threshold" in value:
                    axis = float(value["breadth_threshold"])
                elif "risk_off_multiplier" in value:
                    axis = float(value["risk_off_multiplier"])
                else:
                    axis = float(next(iter(value.values())))
            label = str(axis).replace(".", "p")
            row.update(candidate_id=f"{family}_{label}", family=family, axis_value=axis)
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
    feature = {k: np.full((ndate, nsym), np.nan, dtype=np.float32) for k in ("cap", "vol", "overnight", "intraday", "mom60", "mom120")}
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
        logret = np.log1p(ret.clip(lower=-0.99))
        mom60 = logret.rolling(60).sum()
        mom120 = logret.rolling(120).sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight = np.log(numeric.open / preclose).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(close / numeric.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        amt20 = numeric.amount.rolling(20).mean()
        vol20 = numeric.volume.rolling(20).mean()
        cap = close * numeric.volume / (numeric.turn / 100).replace(0, np.nan)
        age = pd.Series(np.arange(len(x)) + 1, index=x.index)
        ok = (age.ge(252) & amt20.ge(1e7) & close.ge(2) & numeric.isST.eq(0) &
              numeric.tradestatus.eq(1) & vol.gt(0.001) & vol.lt(0.09))
        for name, values in (("cap", cap), ("vol", vol), ("overnight", overnight), ("intraday", intraday),
                             ("mom60", mom60), ("mom120", mom120)):
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
    raw["vol_value"] = feature["vol"]
    raw["mom60_value"] = feature["mom60"]
    raw["mom120_value"] = feature["mom120"]
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
    for p in (STRATEGY, BACKTEST / "engine.py", BACKTEST / "ledger.py", BACKTEST / "actions.py", ROOT / "PROTOCOL_V6.md"):
        input_hashes[str(p.relative_to(ROOT.parents[3])).replace("\\", "/")] = file_hash(p)
    return Market(dates, symbols, columns, raw, present, ranks, eligible, volume20, outs, actions, benchmark, input_hashes)


class RankingBook:
    def __init__(self, market: Market, params: dict):
        self.market = market
        self.params = params
        w = params["weights"]
        score = (w["cap"] * market.ranks["cap"] + w["vol"] * market.ranks["vol"] +
                 w["overnight"] * market.ranks["overnight"] + w["intraday"] * market.ranks["intraday"])
        if w.get("mom60", 0.0):
            score = score + w["mom60"] * market.ranks["mom60"]
        if w.get("mom120", 0.0):
            score = score + w["mom120"] * market.ranks["mom120"]
        self.score = score.astype(np.float32)
        self.cache: dict[int, list[int]] = {}
        self.base_cache: dict[int, list[int]] = {}

    def base_get(self, signal_i: int) -> list[int]:
        if signal_i in self.base_cache:
            return self.base_cache[signal_i]
        if signal_i < 0:
            return []
        smooth = int(self.params["smooth"])
        minimum = int(self.params["min_smooth"])
        lo = max(0, signal_i - smooth + 1)
        window = self.score[lo:signal_i + 1]
        count = np.isfinite(window).sum(axis=0)
        total = np.nansum(window, axis=0)
        values = np.where(count >= minimum, total / np.maximum(count, 1), np.nan).astype(np.float32)
        values[~self.market.eligible[signal_i]] = np.nan
        trend_days = int(self.params.get("trend_days", 0))
        if trend_days:
            trend = self.market.raw[f"mom{trend_days}_value"][signal_i]
            values[~np.isfinite(trend) | (trend <= 0)] = np.nan
        max_vol_rank = float(self.params.get("max_vol_rank", 1.0))
        if max_vol_rank < 1.0:
            vrank = self.market.ranks["vol"][signal_i]
            values[~np.isfinite(vrank) | (vrank > max_vol_rank)] = np.nan
        idx = np.flatnonzero(np.isfinite(values))
        order = idx[np.argsort(-values[idx], kind="stable")][:100]
        result = order.tolist()
        self.base_cache[signal_i] = result
        return result

    def get(self, signal_i: int) -> list[int]:
        if signal_i in self.cache:
            return self.cache[signal_i]
        result = self.base_get(signal_i)
        lag = int(self.params.get("rank_lag_days", 0))
        if lag:
            old = set(self.base_get(signal_i - lag))
            result = [j for j in result if j in old]
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

    def step(self, i: int, ranks: list[int], due: bool, risk_multiplier: float = 1.0) -> None:
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
            count_target = int(self.p["count"])
            total_budget = nav_open * float(self.p["exposure"]) * float(risk_multiplier)
            inv_power = float(self.p.get("allocation_inv_vol_power", 0.0))
            affordability_budget = total_budget * ((2.0 / count_target) if inv_power else (1.0 / count_target))
            keep = set(ranks[:int(int(self.p["count"]) * float(self.p["buffer"]))])
            def selectable(j: int) -> bool:
                if not self.valid(i, j) or self.m.raw["is_st"][i, j]:
                    return False
                op = float(self.m.raw["open"][i, j]); _, high = self.limit_bounds(i, j)
                return op < high - 1e-8 and self.buy_cost(100, op, commission_rate, minimum) <= affordability_budget
            selected = [j for j in ranks if j in positions and j in keep and selectable(j)][:int(self.p["count"])]
            for j in ranks:
                if len(selected) >= int(self.p["count"]):
                    break
                if j not in selected and selectable(j):
                    selected.append(j)
            self.targets = {j: 0 for j in positions if j not in selected}
            weights = np.full(len(selected), 1.0 / len(selected)) if selected else np.array([])
            if inv_power and selected:
                vols = np.array([self.m.raw["vol_value"][i - 1, j] if i > 0 else np.nan for j in selected], dtype=float)
                fallback = np.nanmedian(vols)
                vols = np.where(np.isfinite(vols) & (vols > 0), vols, fallback)
                raw_weight = np.power(vols, -inv_power)
                weights = raw_weight / raw_weight.sum()
                cap_weight = min(1.0, 2.0 / len(selected))
                for _ in range(len(selected)):
                    over = weights > cap_weight
                    if not over.any():
                        break
                    fixed = float(over.sum()) * cap_weight
                    weights[over] = cap_weight
                    under = ~over
                    if under.any() and weights[under].sum() > 0:
                        weights[under] *= (1.0 - fixed) / weights[under].sum()
            for j, weight in zip(selected, weights):
                op = float(self.m.raw["open"][i, j])
                self.targets[j] = int(total_budget * float(weight) / op / 100) * 100
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
    benchmark_close = market.benchmark["close"].reindex(market.dates).ffill()
    market_ma_days = int(params.get("market_ma_days", 0))
    benchmark_ma = benchmark_close.rolling(market_ma_days, min_periods=market_ma_days).mean() if market_ma_days else None
    benchmark_vol60 = benchmark_close.pct_change().rolling(60, min_periods=60).std() * np.sqrt(252)
    market_vol_target = float(params.get("market_vol_target", 0.0))
    breadth_threshold = float(params.get("breadth_threshold", 0.0))
    rows = []
    for start_i in start_indices(market, years):
        start = market.dates[start_i]
        year_ix = np.flatnonzero(market.dates.year == start.year)
        end_i = int(year_ix[-1])
        account = Account(market, params, start_i, stress)
        for i in range(start_i, end_i + 1):
            scheduled = due_on(market, i, int(params["interval"]))
            ranks = book.get(i - 1) if account.first or scheduled else []
            risk_multiplier = 1.0
            if market_ma_days and i > 0:
                signal_date = market.dates[i - 1]
                ma = benchmark_ma.loc[signal_date]
                if not np.isfinite(ma) or benchmark_close.loc[signal_date] < ma:
                    risk_multiplier = float(params["risk_off_multiplier"])
            if market_vol_target and i > 0:
                vol = benchmark_vol60.loc[market.dates[i - 1]]
                if np.isfinite(vol) and vol > 0:
                    risk_multiplier *= min(1.0, market_vol_target / float(vol))
            if breadth_threshold and i > 0:
                mask = market.eligible[i - 1] & np.isfinite(market.raw["mom120_value"][i - 1])
                breadth = float((market.raw["mom120_value"][i - 1, mask] > 0).mean()) if mask.any() else 0.0
                if breadth < breadth_threshold:
                    risk_multiplier *= float(params["risk_off_multiplier"])
            account.step(i, ranks, scheduled, risk_multiplier)
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


def block_table(all_starts: pd.DataFrame) -> pd.DataFrame:
    tagged = all_starts.copy()
    tagged["block"] = np.where(tagged.year.le(2019), "2016_2019", "2020_2024")
    return (tagged.groupby(["candidate_id", "block"], as_index=False)
            .agg(starts=("start", "size"), years=("year", "nunique"), mean_cagr=("cagr", "mean"),
                 min_cagr=("cagr", "min"), mean_excess=("excess", "mean"),
                 mean_drawdown=("max_drawdown", "mean"), mean_sharpe=("sharpe", "mean"),
                 mean_cost_rate=("cost_rate", "mean"), mean_turnover=("turnover", "mean"),
                 mean_final_equity=("final_equity", "mean")))


def gate_and_select(all_starts: pd.DataFrame, yearly: pd.DataFrame, summary: pd.DataFrame,
                    blocks: pd.DataFrame, params: list[dict]) -> tuple[pd.DataFrame, dict]:
    base_starts = all_starts.loc[all_starts.candidate_id.eq("baseline")].set_index("start")
    base_year = yearly.loc[yearly.candidate_id.eq("baseline")].set_index("year")
    base_summary = summary.loc[summary.candidate_id.eq("baseline")].iloc[0]
    base_blocks = blocks.loc[blocks.candidate_id.eq("baseline")].set_index("block")
    pmap = {p["candidate_id"]: p for p in params}
    family_order: dict[str, list[dict]] = {}
    for p in params:
        if p["family"] != "baseline":
            family_order.setdefault(p["family"], []).append(p)
    for family in family_order:
        family_order[family].sort(key=lambda p: float(p["axis_value"]))
    block_gain_by_id: dict[str, pd.Series] = {}
    for cid in summary.candidate_id:
        cb = blocks.loc[blocks.candidate_id.eq(cid)].set_index("block")
        block_gain_by_id[cid] = cb.mean_excess - base_blocks.mean_excess
    records = []
    for _, row in summary.iterrows():
        cid = row.candidate_id
        cb = blocks.loc[blocks.candidate_id.eq(cid)].set_index("block")
        if cid == "baseline":
            records.append({"candidate_id": cid, "passed": True, "failure_reasons": "", "neighbor_ids": "",
                            "early_mean_excess_gain": 0.0, "late_mean_excess_gain": 0.0,
                            "min_block_excess_gain": 0.0, "min_block_mean_excess": float(cb.mean_excess.min())})
            continue
        starts = all_starts.loc[all_starts.candidate_id.eq(cid)].set_index("start")
        annual = yearly.loc[yearly.candidate_id.eq(cid)].set_index("year")
        diff = starts.excess - base_starts.excess
        annual_diff = annual.median_excess - base_year.median_excess
        loo = [diff.loc[starts.year.ne(year)].mean() for year in sorted(starts.year.unique())]
        yearly_gain = (all_starts.loc[all_starts.candidate_id.eq(cid)].groupby("year").excess.sum() -
                       all_starts.loc[all_starts.candidate_id.eq("baseline")].groupby("year").excess.sum())
        positive = yearly_gain.clip(lower=0)
        share = float(positive.max() / positive.sum()) if positive.sum() > 0 else 1.0
        bgain = cb.mean_excess - base_blocks.mean_excess
        cgain = cb.mean_cagr - base_blocks.mean_cagr
        family = pmap[cid]["family"]
        ordered = family_order[family]
        pos = [p["candidate_id"] for p in ordered].index(cid)
        neighbors = [ordered[k]["candidate_id"] for k in (pos - 1, pos + 1) if 0 <= k < len(ordered)]
        neighbor_ok = len(neighbors) == 2 and all((block_gain_by_id[nid] > 0).all() for nid in neighbors)
        reasons = []
        if not (bgain > 0).all(): reasons.append("both_block_excess")
        if not (cgain >= -0.02).all(): reasons.append("both_block_cagr")
        if row.worst_year_median_excess < base_summary.worst_year_median_excess: reasons.append("worst_year")
        if row.year_median_excess_std > base_summary.year_median_excess_std: reasons.append("cross_year_std")
        if int((annual_diff > 0).sum()) < 6: reasons.append("majority_years")
        if float((diff > 0).mean()) <= 0.50: reasons.append("majority_starts")
        if not all(x > 0 for x in loo): reasons.append("leave_one_year_out")
        if share >= 0.50: reasons.append("single_year_dependence")
        if not neighbor_ok: reasons.append("neighbor_stability")
        if cid != "rank_persistence_10p0": reasons.append("neighborhood_probe_only")
        records.append({"candidate_id": cid, "passed": not reasons, "failure_reasons": ";".join(reasons),
                        "years_improved": int((annual_diff > 0).sum()),
                        "starts_improved_fraction": float((diff > 0).mean()),
                        "min_loo_mean_excess_gain": float(min(loo)),
                        "largest_year_positive_gain_share": share, "neighbor_ids": ";".join(neighbors),
                        "early_mean_excess_gain": float(bgain.loc["2016_2019"]),
                        "late_mean_excess_gain": float(bgain.loc["2020_2024"]),
                        "min_block_excess_gain": float(bgain.min()),
                        "min_block_mean_excess": float(cb.mean_excess.min())})
    merged = summary.merge(pd.DataFrame(records), on="candidate_id", how="left")
    passed = merged.loc[merged.passed & merged.candidate_id.ne("baseline")].copy()
    if passed.empty:
        selected_id = "baseline"
    else:
        passed = passed.sort_values(
            ["min_block_excess_gain", "worst_year_median_excess", "year_median_excess_std",
             "min_block_mean_excess", "mean_cagr", "mean_drawdown", "mean_sharpe", "mean_cost_rate"],
            ascending=[False, False, True, False, False, True, False, True], kind="mergesort")
        selected_id = passed.iloc[0].candidate_id
    return merged, pmap[selected_id]


def make_report(frozen: dict, evaluated: pd.DataFrame, blocks: pd.DataFrame) -> None:
    base = evaluated.loc[evaluated.candidate_id.eq("baseline")].iloc[0]
    chosen = evaluated.loc[evaluated.candidate_id.eq(frozen["selected_candidate_id"])].iloc[0]
    bb = blocks.loc[blocks.candidate_id.eq("baseline")].set_index("block")
    lines = [
        "# 沪深1排名持续性邻域审计 V6", "",
        f"- 搜索空间哈希：`{frozen['search_space_sha256']}`",
        f"- 冻结候选：`{frozen['selected_candidate_id']}`",
        f"- 最终决定：`{frozen['final_decision']}`",
        f"- 候选哈希：`{frozen['frozen_candidate_sha256']}`", "",
        "## 精确基线分段评估", "",
        "| 区间 | 起点数 | 平均年化 | 最低年化 | 平均超额 | 平均回撤 | 平均Sharpe | 平均期末资产 |", 
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for block in ("2016_2019", "2020_2024"):
        x = bb.loc[block]
        lines.append(f"| {block.replace('_', '—')} | {int(x.starts)} | {x.mean_cagr:.2%} | {x.min_cagr:.2%} | {x.mean_excess:.2%} | {x.mean_drawdown:.2%} | {x.mean_sharpe:.3f} | {x.mean_final_equity:,.2f} |")
    lines += ["", "## 探索结果", "",
              f"共评估{len(evaluated)}组冻结候选。通过全部迁移门槛的非基线候选为{int((evaluated.passed & evaluated.candidate_id.ne('baseline')).sum())}组。",
              f"冻结结果为 `{frozen['selected_candidate_id']}`；最差年度中位超额 {chosen.worst_year_median_excess:.2%}，跨年标准差 {chosen.year_median_excess_std:.2%}，全期平均年化 {chosen.mean_cagr:.2%}。", "",
              "所有逐起点、逐年度、分区间、压力测试和失败原因均保存在本目录。2025年以后没有参与本轮研发。", ""]
    (HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def develop() -> None:
    if (HERE / "FINAL_LOCK.json").exists():
        raise RuntimeError("research is permanently locked; results cannot be overwritten")
    spec, freeze_hash = verify_search_freeze()
    market = load_market(DEV_END)
    params = candidates(spec)
    frames = []
    for n, p in enumerate(params, 1):
        print(f"DEVELOP {n}/{len(params)} {p['candidate_id']}", flush=True)
        frames.append(run_candidate(market, p, range(2016, 2025)))
    all_starts = pd.concat(frames, ignore_index=True)
    yearly, summary = summary_table(all_starts)
    blocks = block_table(all_starts)
    evaluated, selected = gate_and_select(all_starts, yearly, summary, blocks, params)
    all_starts.to_csv(HERE / "development_all_starts.csv", index=False)
    yearly.to_csv(HERE / "development_yearly.csv", index=False)
    blocks.to_csv(HERE / "development_blocks.csv", index=False)
    evaluated.to_csv(HERE / "candidate_summary.csv", index=False)
    blocks.loc[blocks.candidate_id.eq("baseline")].to_csv(HERE / "baseline_block_assessment.csv", index=False)
    selected_id = selected["candidate_id"]
    stress_ids = ["baseline"] if selected_id == "baseline" else ["baseline", selected_id]
    pmap = {p["candidate_id"]: p for p in params}
    stress_frames = []
    for stress in ("double_commission", "capacity_40pct"):
        for cid in stress_ids:
            stress_frames.append(run_candidate(market, pmap[cid], range(2016, 2025), stress))
    stress = pd.concat(stress_frames, ignore_index=True)
    stress.to_csv(HERE / "development_stress_all_starts.csv", index=False)
    stress_yearly, stress_summary = summary_table(stress)
    stress_yearly.to_csv(HERE / "development_stress_yearly.csv", index=False)
    stress_summary.to_csv(HERE / "development_stress_summary.csv", index=False)
    frozen = {
        "schema_version": 1, "permanently_locked": True, "search_space_sha256": freeze_hash,
        "selected_candidate_id": selected_id,
        "final_decision": "retain_baseline" if selected_id == "baseline" else "candidate_frozen_pending_one_way_post_boundary_audit",
        "parameters": {k: v for k, v in selected.items() if k not in {"family", "axis_value"}},
        "development_summary": evaluated.loc[evaluated.candidate_id.eq(selected_id)].iloc[0].to_dict(),
        "development_last_date": str(market.dates[-1].date()),
        "result_files": ["development_all_starts.csv", "development_yearly.csv", "development_blocks.csv",
                         "candidate_summary.csv", "baseline_block_assessment.csv", "development_stress_all_starts.csv",
                         "development_stress_yearly.csv", "development_stress_summary.csv"]
    }
    frozen["frozen_candidate_sha256"] = canonical_hash(frozen)
    write_json(HERE / "FINAL_LOCK.json", frozen)
    make_report(frozen, evaluated, blocks)
    artifacts = ["SEARCH_SPACE.json", "run_research.py", "FINAL_LOCK.json", "REPORT.md"] + frozen["result_files"]
    audit = {
        "stage": "development_permanently_locked", "search_space_sha256": freeze_hash,
        "candidate_sha256": frozen["frozen_candidate_sha256"], "input_hashes": market.input_hashes,
        "raw_files_verified": len(market.symbols), "development_last_date": str(market.dates[-1].date()),
        "phase_anchor": str(ANCHOR.date()), "factor_missing_propagation": True,
        "candidate_count": len(params), "start_rows": len(all_starts),
        "nonbaseline_passed": int((evaluated.passed & evaluated.candidate_id.ne("baseline")).sum()),
        "artifact_sha256": {name: file_hash(HERE / name) for name in artifacts}
    }
    write_json(HERE / "AUDIT.json", audit)
    print(f"LOCKED {frozen['final_decision']} {frozen['frozen_candidate_sha256']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["develop"])
    parser.add_argument("--skip-raw-hash", action="store_true", help="reserved; hashes remain mandatory")
    args = parser.parse_args()
    develop()


if __name__ == "__main__":
    main()


