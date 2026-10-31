"""Pre-2025-only, time-ordered transfer research for Hushen-1.

This program is intentionally self-contained inside the authorized development
directory.  It reads only PROTOCOL.md, inputs_pre2025, the frozen search file,
and the explicitly approved execution source files for hashing/audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "inputs_pre2025"
SEARCH = HERE / "SEARCH_SPACE.json"
PROTOCOL = ROOT / "PROTOCOL.md"
STRATEGY = ROOT.parents[1] / "supermind_hushen_1.py"
BACKTEST = ROOT.parents[1] / "backtest"
ALLOWED_SOURCES = [PROTOCOL, STRATEGY, BACKTEST / "engine.py", BACKTEST / "ledger.py", BACKTEST / "actions.py"]
CONFIRMATION_LOCK = HERE / "CONFIRMATION_LOCK.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def cn_round_limit(x: float) -> float:
    return math.floor(x * 100 + 0.5 + 1e-10) / 100


class Market:
    fields = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn"]

    def __init__(self, spec: dict):
        manifest = json.loads((DATA / "PUBLIC_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
        if manifest["cutoff"] != "2024-12-31" or manifest["status"] != "sanitized_pre2025_only":
            raise RuntimeError("Pre-2025 manifest boundary failed")
        cal = pd.read_csv(DATA / "calendar.csv")
        self.dates = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1), "calendar_date"]))
        if self.dates.max() > pd.Timestamp("2024-12-31"):
            raise RuntimeError("Post-2024 calendar row detected")
        records = [r for r in manifest["files"] if int(r.get("rows", 0)) > 0]
        if len(records) != int(manifest["symbols_with_rows"]):
            raise RuntimeError("Manifest populated-symbol count mismatch")
        self.symbols = [r["symbol"] for r in records]
        self.col = {s: i for i, s in enumerate(self.symbols)}
        shape = (len(self.dates), len(self.symbols))
        self.raw = {k: np.full(shape, np.nan, dtype=np.float32) for k in self.fields}
        self.status = np.zeros(shape, dtype=np.int8)
        self.st = np.zeros(shape, dtype=np.int8)
        self.present = np.zeros(shape, dtype=bool)
        self.age = np.zeros(shape, dtype=np.int16)
        for j, record in enumerate(records):
            p = DATA / "raw" / record["symbol"][-2:] / (record["symbol"] + ".parquet")
            if sha(p) != record["sha256"]:
                raise RuntimeError(f"Input hash mismatch: {p}")
            x = pd.read_parquet(p)
            x["date"] = pd.to_datetime(x.date)
            if x.date.max() > pd.Timestamp("2024-12-31"):
                raise RuntimeError(f"Post-2024 quote detected: {p}")
            ix = self.dates.get_indexer(x.date)
            ok = ix >= 0
            ix = ix[ok]
            x = x.loc[ok].reset_index(drop=True)
            for k in self.fields:
                self.raw[k][ix, j] = pd.to_numeric(x[k], errors="raise").to_numpy(np.float32)
            self.status[ix, j] = pd.to_numeric(x.tradestatus, errors="raise").to_numpy(np.int8)
            self.st[ix, j] = pd.to_numeric(x.isST, errors="raise").to_numpy(np.int8)
            self.present[ix, j] = True
            self.age[ix, j] = np.arange(1, len(ix) + 1, dtype=np.int16)
        self.volume20 = self._rolling_mean(self.raw["volume"], 20, 20)
        self.features, self.eligible = self._features(spec)
        self.index = pd.read_parquet(DATA / "sse_price_index.parquet").set_index("date").reindex(self.dates)
        if self.index.index.max() > pd.Timestamp("2024-12-31"):
            raise RuntimeError("Post-2024 benchmark detected")
        meta = pd.read_csv(DATA / "universe.csv")
        self.out = {self.col[r.symbol]: pd.Timestamp(r.outDate) for r in meta.itertuples()
                    if r.symbol in self.col and pd.notna(r.outDate)}
        self.actions = self._load_actions()

    @staticmethod
    def _rolling_sum(a, window, minimum):
        df = pd.DataFrame(a)
        return df.rolling(window, min_periods=minimum).sum().to_numpy(np.float32)

    @staticmethod
    def _rolling_mean(a, window, minimum):
        df = pd.DataFrame(a)
        return df.rolling(window, min_periods=minimum).mean().to_numpy(np.float32)

    @staticmethod
    def _rolling_std(a, window, minimum):
        df = pd.DataFrame(a)
        return df.rolling(window, min_periods=minimum).std().to_numpy(np.float32)

    def _features(self, spec):
        close, pre, op = self.raw["close"], self.raw["preclose"], self.raw["open"]
        with np.errstate(divide="ignore", invalid="ignore"):
            ret = close / pre - 1
            logret = np.log(close / pre)
            overnight = np.log(op / pre)
            intraday = np.log(close / op)
            cap = close * self.raw["volume"] / (self.raw["turn"] / 100)
        ret[(self.status == 0) | ~np.isfinite(ret)] = 0
        for a in (logret, overnight, intraday, cap):
            a[~np.isfinite(a)] = np.nan
        vol60 = self._rolling_std(ret, 60, 60)
        amount20 = self._rolling_mean(self.raw["amount"], 20, 20)
        eligible = ((self.age >= spec["eligibility"]["listed_observations_min"]) &
                    (amount20 >= spec["eligibility"]["amount_20d_min_cny"]) &
                    (close >= spec["eligibility"]["close_min_cny"]) & (self.st == 0) &
                    (self.status == 1) & (vol60 > spec["eligibility"]["volatility_60d_min"]) &
                    (vol60 < spec["eligibility"]["volatility_60d_max"]))
        raw_features = {
            "cap": cap,
            "vol60": vol60,
            "overnight20": self._rolling_sum(np.nan_to_num(overnight, nan=0), 20, 20),
            "intraday20": self._rolling_sum(np.nan_to_num(intraday, nan=0), 20, 20),
            "mom60": self._rolling_sum(np.nan_to_num(logret, nan=0), 60, 60),
            "reversal5": self._rolling_sum(np.nan_to_num(logret, nan=0), 5, 5),
            "turn20": self._rolling_mean(self.raw["turn"], 20, 20),
        }
        ranked = {}
        for name, a in raw_features.items():
            masked = np.where(eligible, a, np.nan)
            ranked[name] = pd.DataFrame(masked).rank(axis=1, pct=True, method="average").to_numpy(np.float32)
        return ranked, eligible

    def _load_actions(self):
        raw = json.loads((DATA / "actions_pre2025.json").read_text(encoding="utf-8"))
        out = {}
        for key, rows in raw.items():
            symbol = key.split("/")[0]
            if symbol not in self.col:
                continue
            for r in rows:
                if not r.get("dividOperateDate"):
                    continue
                d = pd.Timestamp(r["dividOperateDate"])
                if d > pd.Timestamp("2024-12-31"):
                    raise RuntimeError("Post-2024 action detected")
                num = lambda x: float(x) if str(x).strip() else 0.0
                out[(self.col[symbol], d)] = {
                    "cash": num(r.get("dividCashPsBeforeTax", "")),
                    "stock": num(r.get("dividStocksPs", "")) + num(r.get("dividReserveToStockPs", "")),
                    "taxable_stock": num(r.get("dividStocksPs", "")),
                    "pay": pd.Timestamp(r.get("dividPayDate") or r["dividOperateDate"]),
                    "release": pd.Timestamp(r.get("dividStockMarketDate") or r["dividOperateDate"]),
                }
        return out

    def make_rankings(self, signal: dict) -> np.ndarray:
        score = np.zeros(self.eligible.shape, dtype=np.float32)
        valid = np.zeros(self.eligible.shape, dtype=bool)
        for name, weight in signal["weights"].items():
            a = self.features[name]
            score += np.nan_to_num(a, nan=0) * np.float32(weight)
            valid |= np.isfinite(a)
        score[~valid] = np.nan
        smooth = pd.DataFrame(score).rolling(signal["smooth"], min_periods=signal["min_smooth"]).mean().to_numpy(np.float32)
        smooth[~self.eligible] = np.nan
        top = np.full((len(self.dates), 100), -1, dtype=np.int32)
        for i in range(len(self.dates)):
            row = smooth[i]
            ids = np.flatnonzero(np.isfinite(row))
            if not len(ids):
                continue
            order = np.lexsort((np.array(self.symbols, dtype=object)[ids], -row[ids]))[:100]
            chosen = ids[order]
            top[i, :len(chosen)] = chosen
        return top


@dataclass
class Lot:
    qty: int
    buy: pd.Timestamp
    release: pd.Timestamp
    div_basis: float = 0.0


@dataclass
class Position:
    qty: int = 0
    last: float = 0.0
    lots: list[Lot] = field(default_factory=list)


class Simulator:
    def __init__(self, market: Market, ranks: np.ndarray, params: dict):
        self.m, self.ranks, self.p = market, ranks, params

    def run(self, start: pd.Timestamp, end: pd.Timestamp):
        m, p = self.m, self.p
        s0, e0 = m.dates.get_loc(start), m.dates.get_loc(end)
        cash = 100000.0
        holdings: dict[int, Position] = {}
        targets: dict[int, int] = {}
        receivables = []
        fees = tax = turnover = 0.0
        capacity_hits = rejected = unresolved = 0
        navs, exposures, daily_returns = [], [], []
        first = True
        previous_equity = 100000.0

        def available(pos, date):
            return sum(l.qty for l in pos.lots if l.release <= date and l.buy < date)

        for i in range(s0, e0 + 1):
            date = m.dates[i]
            newly_paid = sum(a for d, a in receivables if d <= date)
            cash += newly_paid
            receivables = [(d, a) for d, a in receivables if d > date]
            for j in list(holdings):
                pos = holdings[j]
                act = m.actions.get((j, date))
                if act:
                    amount = pos.qty * act["cash"]
                    if act["pay"] <= date:
                        cash += amount
                    else:
                        receivables.append((act["pay"], amount))
                    remaining = int(math.floor(pos.qty * act["stock"] + 1e-8))
                    additions = []
                    old_lots = list(pos.lots)
                    for n, lot in enumerate(old_lots):
                        bonus = min(remaining, int(math.floor(lot.qty * act["stock"] + 1e-8)))
                        if n == len(old_lots) - 1:
                            bonus = remaining
                        remaining -= bonus
                        taxable = act["cash"] + act["taxable_stock"] if date <= lot.buy + pd.DateOffset(years=1) else 0.0
                        basis = lot.div_basis + taxable
                        adjusted = basis * lot.qty / (lot.qty + bonus) if lot.qty + bonus else 0.0
                        lot.div_basis = adjusted
                        if bonus:
                            additions.append(Lot(bonus, lot.buy, act["release"], adjusted))
                    pos.lots.extend(additions)
                    pos.lots.sort(key=lambda z: (z.buy, z.release))
                    pos.qty = sum(z.qty for z in pos.lots)
                if j in m.out and date >= m.out[j]:
                    unresolved += 1
                    del holdings[j]
                    targets.pop(j, None)
            valid_open = lambda j: (m.present[i, j] and m.status[i, j] == 1 and np.isfinite(m.raw["open"][i, j]) and m.raw["open"][i, j] > 0)
            nav_open = cash + sum(a for _, a in receivables)
            for j, pos in holdings.items():
                nav_open += pos.qty * (float(m.raw["open"][i, j]) if valid_open(j) else pos.last)
            rebalance = first or (i - 1) % p["interval"] == 0
            prev = i - 1
            if rebalance and prev >= 0:
                ranked = [int(j) for j in self.ranks[prev] if j >= 0]
                budget = nav_open * p.get("exposure", 0.98) / p["count"]
                keep = set(ranked[:int(p["count"] * p["buffer"])])
                def limits(j):
                    pct = .05 if m.st[i, j] else .10
                    pre = float(m.raw["preclose"][i, j])
                    return cn_round_limit(pre * (1 + pct)), cn_round_limit(pre * (1 - pct))
                def selectable(j):
                    if not valid_open(j) or m.st[i, j]: return False
                    hi, _ = limits(j); op = float(m.raw["open"][i, j])
                    return op < hi - 1e-8 and 100 * (op * 1.001 + .01) + max(5, 100 * op * 1.001 * .0003) <= budget
                selected = [j for j in ranked if j in holdings and j in keep and selectable(j)][:p["count"]]
                for j in ranked:
                    if len(selected) >= p["count"]: break
                    if j not in selected and selectable(j): selected.append(j)
                targets = {j: 0 for j in holdings if j not in selected}
                for j in selected:
                    targets[j] = int(budget / float(m.raw["open"][i, j]) / 100) * 100
                first = False
            if prev >= 0:
                for j in list(holdings):
                    if m.present[prev, j] and m.st[prev, j]: targets[j] = 0
            keys = sorted(targets, key=lambda j: (targets[j] - holdings.get(j, Position()).qty >= 0, self.m.symbols[j]))
            for j in keys:
                current = holdings.get(j, Position()).qty
                delta = targets[j] - current
                if delta == 0 or not valid_open(j) or prev < 0 or not np.isfinite(m.volume20[prev, j]):
                    continue
                pct = .05 if m.st[i, j] else .10
                pre = float(m.raw["preclose"][i, j]); high_lim = cn_round_limit(pre * (1 + pct)); low_lim = cn_round_limit(pre * (1 - pct))
                op = float(m.raw["open"][i, j])
                cap = int(float(m.volume20[prev, j]) * p.get("participation", .005) / 100) * 100
                qty = min(abs(delta), cap, 1000000)
                if qty < abs(delta): capacity_hits += 1
                if delta < 0:
                    if op <= low_lim + 1e-8: rejected += 1; continue
                    pos = holdings[j]
                    qty = min(qty, available(pos, date))
                    if qty != current: qty = qty // 100 * 100
                    if qty <= 0: continue
                    limit = max(low_lim, math.floor(max(low_lim, op * .999) * 100 + 1e-8) / 100)
                    price = round(max(limit, op * .999, float(m.raw["low"][i, j]), low_lim), 2)
                    if price > min(float(m.raw["high"][i, j]), high_lim) + 1e-8: rejected += 1; continue
                    value = qty * price; commission = round(max(5, value * .0003), 2)
                    transfer = round(value * (.00002 if date < pd.Timestamp("2022-04-29") else .00001), 2)
                    stamp = round(value * (.001 if date < pd.Timestamp("2023-08-28") else .0005), 2)
                    remaining, divtax = qty, 0.0
                    for lot in pos.lots:
                        if lot.release > date or lot.buy >= date: continue
                        q = min(remaining, lot.qty); remaining -= q; lot.qty -= q
                        rate = .2 if date <= lot.buy + pd.DateOffset(months=1) else (.1 if date <= lot.buy + pd.DateOffset(years=1) else 0)
                        divtax += q * lot.div_basis * rate
                        if not remaining: break
                    if remaining: raise AssertionError("T+1 lot accounting")
                    divtax = round(divtax, 2); pos.lots = [z for z in pos.lots if z.qty]; pos.qty -= qty
                    cash += value - commission - transfer - stamp - divtax
                    fees += commission + transfer + stamp; tax += divtax; turnover += value
                    if not pos.qty: del holdings[j]
                else:
                    if m.st[i, j] or op >= high_lim - 1e-8: rejected += 1; continue
                    qty = qty // 100 * 100
                    if qty <= 0: continue
                    limit = min(high_lim, math.ceil(min(high_lim, op * 1.001) * 100 - 1e-8) / 100)
                    price = round(min(limit, op * 1.001, float(m.raw["high"][i, j]), high_lim), 2)
                    if price < max(float(m.raw["low"][i, j]), low_lim) - 1e-8: rejected += 1; continue
                    while qty > 0:
                        value = qty * price; commission = round(max(5, value * .0003), 2)
                        transfer = round(value * (.00002 if date < pd.Timestamp("2022-04-29") else .00001), 2)
                        if value + commission + transfer <= cash + 1e-6: break
                        qty -= 100
                    if qty <= 0: continue
                    value = qty * price; commission = round(max(5, value * .0003), 2)
                    transfer = round(value * (.00002 if date < pd.Timestamp("2022-04-29") else .00001), 2)
                    cash -= value + commission + transfer; fees += commission + transfer; turnover += value
                    pos = holdings.setdefault(j, Position(last=price)); pos.qty += qty
                    pos.lots.append(Lot(qty, date, date + pd.Timedelta(days=1), 0.0))
            market_value = 0.0
            for j, pos in holdings.items():
                if m.present[i, j] and np.isfinite(m.raw["close"][i, j]) and m.raw["close"][i, j] > 0:
                    pos.last = float(m.raw["close"][i, j])
                market_value += pos.qty * pos.last
            equity = cash + market_value + sum(a for _, a in receivables)
            navs.append(equity); exposures.append(market_value / equity if equity else 0)
            daily_returns.append(equity / previous_equity - 1); previous_equity = equity
        nav = np.asarray(navs); dr = np.asarray(daily_returns)
        days = (end - start).days + 1
        total = nav[-1] / 100000 - 1
        cagr = (nav[-1] / 100000) ** (365.25 / days) - 1
        peak = np.maximum.accumulate(np.r_[100000.0, nav])[1:]
        dd = float(np.max(1 - nav / peak))
        sharpe = float(dr.mean() / dr.std(ddof=1) * np.sqrt(252)) if dr.std(ddof=1) > 0 else np.nan
        benchmark = float(m.index.loc[end, "close"] / m.index.loc[start, "open"] - 1)
        return {
            "requested_start": str(start.date()), "end": str(end.date()), "year": int(start.year),
            "total_return": float(total), "benchmark_return": benchmark, "excess_return": float(total - benchmark),
            "cagr": float(cagr), "max_drawdown": dd, "sharpe": sharpe,
            "transaction_cost": float(fees + tax), "turnover_cny": float(turnover),
            "average_exposure": float(np.mean(exposures)), "capacity_hits": capacity_hits,
            "rejected_orders": rejected, "unresolved_delistings": unresolved,
        }


def configs_for_stage_b(top_signals, spec):
    out = []
    for sid in top_signals:
        for count in spec["stage_b_execution_grid"]["count"]:
            for interval in spec["stage_b_execution_grid"]["interval"]:
                for buffer in spec["stage_b_execution_grid"]["buffer"]:
                    out.append({"id": f"{sid}_C{count}_I{interval}_B{buffer:g}", "signal": sid, "count": count,
                                "interval": interval, "buffer": buffer, "exposure": .98, "participation": .005, "drift": False})
    return out


def summarize(rows: pd.DataFrame):
    annual = rows.groupby("year", as_index=False).agg(
        median_excess=("excess_return", "median"), mean_excess=("excess_return", "mean"),
        median_cagr=("cagr", "median"), minimum_cagr=("cagr", "min"), starts=("requested_start", "count"))
    return {
        "minimum_year_median_excess": float(annual.median_excess.min()),
        "year_median_excess_std": float(annual.median_excess.std(ddof=0)),
        "mean_excess": float(rows.excess_return.mean()), "minimum_cagr": float(rows.cagr.min()),
        "mean_cagr": float(rows.cagr.mean()), "worst_drawdown": float(rows.max_drawdown.max()),
        "mean_sharpe": float(rows.sharpe.mean()), "mean_cost": float(rows.transaction_cost.mean()),
        "capacity_hits": int(rows.capacity_hits.sum()), "unresolved_delistings": int(rows.unresolved_delistings.sum()),
        "annual": annual.to_dict("records"),
    }


def objective(summary):
    return (summary["minimum_year_median_excess"], -summary["year_median_excess_std"], summary["mean_excess"],
            summary["minimum_cagr"], summary["mean_cagr"], -summary["worst_drawdown"],
            summary["mean_sharpe"], -summary["mean_cost"])


def starts_for_year(market, year):
    x = market.dates[(market.dates.year == year) & (market.dates.month <= 3)]
    end = market.dates[market.dates.year == year][-1]
    return [(d, end) for d in x]


def evaluate(market, rankings, config, years):
    sim = Simulator(market, rankings[config["signal"]], config)
    rows = []
    for year in years:
        for start, end in starts_for_year(market, year):
            row = sim.run(start, end); row.update(candidate=config["id"], signal=config["signal"])
            rows.append(row)
    return rows


def baseline_config(spec):
    x = dict(spec["stage_a_execution"])
    return {"id": "B0", "signal": "B0", **x}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["development", "confirm", "all"], default="all")
    args = ap.parse_args()
    if CONFIRMATION_LOCK.exists():
        raise RuntimeError("Confirmation lock exists: no rerun or post-confirmation tuning is permitted")
    spec = json.loads(SEARCH.read_text(encoding="utf-8"))
    search_hash = sha(SEARCH)
    market = Market(spec)
    signals = {s["id"]: s for s in spec["signal_candidates"]}
    rankings = {sid: market.make_rankings(sig) for sid, sig in signals.items()}
    dev_years = spec["development_years"]
    stage_a_rows = []
    stage_a_summaries = {}
    for sid in signals:
        cfg = {"id": sid, "signal": sid, **spec["stage_a_execution"]}
        rows = evaluate(market, rankings, cfg, dev_years); stage_a_rows.extend(rows)
        stage_a_summaries[sid] = summarize(pd.DataFrame(rows))
        print("STAGE_A", sid, objective(stage_a_summaries[sid]), flush=True)
    pd.DataFrame(stage_a_rows).to_csv(HERE / "stage_a_all_starts_2016_2023.csv", index=False)
    dump(HERE / "stage_a_summary_2016_2023.json", stage_a_summaries)
    top = sorted(signals, key=lambda k: objective(stage_a_summaries[k]), reverse=True)[:3]
    if "B0" not in top: top.append("B0")
    stage_b_rows, stage_b_summaries, stage_b_configs = [], {}, configs_for_stage_b(top, spec)
    for cfg in stage_b_configs:
        rows = evaluate(market, rankings, cfg, dev_years); stage_b_rows.extend(rows)
        stage_b_summaries[cfg["id"]] = summarize(pd.DataFrame(rows))
        print("STAGE_B", cfg["id"], objective(stage_b_summaries[cfg["id"]]), flush=True)
    bdf = pd.DataFrame(stage_b_rows); bdf.to_csv(HERE / "stage_b_all_starts_2016_2023.csv", index=False)
    dump(HERE / "stage_b_summary_2016_2023.json", stage_b_summaries)
    base_id = "B0_C5_I20_B1.5"
    base_rows = bdf[bdf.candidate.eq(base_id)].copy(); base_summary = stage_b_summaries[base_id]
    decisions = []
    for cfg in stage_b_configs:
        cid = cfg["id"]; rows = bdf[bdf.candidate.eq(cid)].copy(); summ = stage_b_summaries[cid]
        merged = rows.merge(base_rows[["requested_start", "excess_return"]], on="requested_start", suffixes=("", "_base"))
        wins = float((merged.excess_return > merged.excess_return_base).mean())
        ann = pd.DataFrame(summ["annual"]).merge(pd.DataFrame(base_summary["annual"]), on="year", suffixes=("", "_base"))
        year_wins = int((ann.median_excess > ann.median_excess_base).sum())
        improvements = (ann.median_excess - ann.median_excess_base).clip(lower=0)
        max_share = float(improvements.max() / improvements.sum()) if improvements.sum() > 0 else 1.0
        primary_improved = summ["minimum_year_median_excess"] > base_summary["minimum_year_median_excess"]
        std_ok = summ["year_median_excess_std"] <= base_summary["year_median_excess_std"] or primary_improved
        decisions.append({"candidate": cid, "signal": cfg["signal"], "start_win_fraction": wins, "year_wins": year_wins,
                          "positive_improvement_max_year_share": max_share, "primary_improved": bool(primary_improved),
                          "std_acceptable": bool(std_ok), "objective": objective(summ)})
    ddf = pd.DataFrame(decisions)
    viable = ddf[(ddf.year_wins >= spec["stability_rules"]["majority_years_excess_vs_baseline"]) &
                 (ddf.start_win_fraction >= spec["stability_rules"]["majority_starts_excess_vs_baseline_fraction"]) &
                 (ddf.positive_improvement_max_year_share <= spec["stability_rules"]["no_single_year_contribution_share_above"]) &
                 ddf.primary_improved & ddf.std_acceptable]
    if len(viable):
        viable_ids = set(viable.candidate)
        neighborhood = []
        for cfg in stage_b_configs:
            if cfg["id"] not in viable_ids: continue
            peers = [x for x in stage_b_configs if x["signal"] == cfg["signal"] and x["id"] in viable_ids and x["id"] != cfg["id"]]
            if peers: neighborhood.append(cfg["id"])
        viable = viable[viable.candidate.isin(neighborhood)]
    selected_id = max(viable.candidate, key=lambda x: objective(stage_b_summaries[x])) if len(viable) else base_id
    selected_cfg = next(x for x in stage_b_configs if x["id"] == selected_id)
    ddf["selected_for_confirmation"] = ddf.candidate.eq(selected_id)
    ddf.to_csv(HERE / "selection_2016_2023.csv", index=False)
    if args.phase == "development":
        dump(HERE / "DEVELOPMENT_SELECTION.json", {"selected": selected_cfg, "search_space_sha256": search_hash})
        return
    confirmation_rows = []
    for cfg in [next(x for x in stage_b_configs if x["id"] == base_id), selected_cfg]:
        confirmation_rows.extend(evaluate(market, rankings, cfg, [spec["confirmation_year"]]))
    cdf = pd.DataFrame(confirmation_rows); cdf.to_csv(HERE / "confirmation_2024_all_starts.csv", index=False)
    cs = {cid: summarize(cdf[cdf.candidate.eq(cid)]) for cid in cdf.candidate.unique()}
    dump(HERE / "confirmation_2024_summary.json", cs)
    if selected_id == base_id:
        confirmed = False
        reason = "No development candidate passed the frozen stability rules; retain original baseline."
    else:
        cand = cdf[cdf.candidate.eq(selected_id)]; base = cdf[cdf.candidate.eq(base_id)]
        joined = cand.merge(base[["requested_start", "excess_return", "cagr"]], on="requested_start", suffixes=("", "_base"))
        confirmed = (cand.excess_return.median() >= base.excess_return.median() and
                     float((joined.excess_return - joined.excess_return_base).min()) >= spec["confirmation_gate"]["worst_start_excess_tolerance"] and
                     cand.cagr.median() >= base.cagr.median())
        reason = "Passed frozen 2024 confirmation gate." if confirmed else "Failed frozen 2024 confirmation gate; retain original baseline."
    final_cfg = selected_cfg if confirmed else next(x for x in stage_b_configs if x["id"] == base_id)
    final_signal = signals[final_cfg["signal"]]
    code_hashes = {str(p.relative_to(ROOT.parents[2])).replace("\\", "/"): sha(p) for p in [Path(__file__), SEARCH, *ALLOWED_SOURCES]}
    frozen_core = {"boundary_version": spec["boundary_version"], "candidate_id": final_cfg["id"],
                   "signal": final_signal, "execution": final_cfg, "promoted": bool(confirmed),
                   "decision_reason": reason, "data_cutoff": spec["data_cutoff"], "code_hashes": code_hashes}
    frozen_hash = canonical_hash(frozen_core)
    frozen = {**frozen_core, "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "frozen_hash": frozen_hash,
              "post_2024_data_used": False, "production_modified": False}
    dump(HERE / "FROZEN_CANDIDATE.json", frozen)
    lock = {"locked_at_utc": frozen["frozen_at_utc"], "frozen_hash": frozen_hash,
            "rule": "2024 confirmation was viewed; development and tuning are permanently closed."}
    dump(CONFIRMATION_LOCK, lock)
    input_hashes = {"manifest": sha(DATA / "PUBLIC_INPUT_MANIFEST.json"), "calendar": sha(DATA / "calendar.csv"),
                    "universe": sha(DATA / "universe.csv"), "sse_price_index": sha(DATA / "sse_price_index.parquet"),
                    "actions": sha(DATA / "actions_pre2025.json")}
    audit = {"status": "complete", "boundary_version": spec["boundary_version"], "allowed_cutoff": spec["data_cutoff"],
             "confirmation_locked": True, "search_space_sha256": search_hash, "frozen_hash": frozen_hash,
             "input_hashes": input_hashes, "code_hashes": code_hashes, "python": sys.version,
             "platform": platform.platform(), "development_candidates": len(stage_a_summaries) + len(stage_b_summaries),
             "development_start_runs": len(stage_a_rows) + len(stage_b_rows), "confirmation_start_runs": len(cdf),
             "files": ["SEARCH_SPACE.json", "run_research.py", "stage_a_all_starts_2016_2023.csv",
                       "stage_a_summary_2016_2023.json", "stage_b_all_starts_2016_2023.csv",
                       "stage_b_summary_2016_2023.json", "selection_2016_2023.csv",
                       "confirmation_2024_all_starts.csv", "confirmation_2024_summary.json",
                       "FROZEN_CANDIDATE.json", "CONFIRMATION_LOCK.json", "REPORT.md"]}
    dump(HERE / "AUDIT.json", audit)
    report = f"""# 沪深1跨时间迁移研发报告\n\n- 隔离边界：`{spec['boundary_version']}`；只使用截至 `{spec['data_cutoff']}` 的公开输入。\n- 研发/选择：2016–2023，每年第一季度全部交易日起点；2024仅执行一次最终确认。\n- 冻结搜索空间哈希：`{search_hash}`。\n- 最终冻结候选：`{final_cfg['id']}`。\n- 是否晋级新候选：`{str(bool(confirmed)).lower()}`。\n- 决策：{reason}\n- 冻结哈希：`{frozen_hash}`。\n\n完整公式与执行参数见 `FROZEN_CANDIDATE.json`；所有逐起点结果、逐年汇总、候选失败与选择证据见同目录 CSV/JSON。2024 确认结果查看后已写入 `CONFIRMATION_LOCK.json`，不得继续调参。当前生产入口、tracking 和其他策略均未修改。\n"""
    (HERE / "REPORT.md").write_text(report, encoding="utf-8")
    print("FINAL", final_cfg["id"], confirmed, frozen_hash, flush=True)


if __name__ == "__main__":
    main()
