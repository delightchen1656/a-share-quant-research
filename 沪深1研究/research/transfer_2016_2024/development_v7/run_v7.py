from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
INPUT = BASE / "inputs_pre2025"
PROTOCOL = BASE / "PROTOCOL_V7.md"
SEARCH = HERE / "SEARCH_SPACE.json"
FREEZE = HERE / "PRE_RUN_FREEZE.json"
ENTRY = BASE.parents[1] / "supermind_hushen_1.py"
BACKTEST = BASE.parents[1] / "backtest"

FACTORS = ["cap", "vol60", "overnight20", "intraday20"]
DIRECTION = np.array([-1.0, -1.0, 1.0, -1.0], dtype=np.float64)
BASE_ABS = np.array([0.35, 0.20, 0.25, 0.20], dtype=np.float64)
BASE_SIGNED = BASE_ABS * DIRECTION
MODELS = {
    "baseline": None,
    "online_w504_m025": (504, 0.25),
    "online_w504_m050": (504, 0.50),
    "online_w756_m025": (756, 0.25),
    "online_w756_m050": (756, 0.50),
}
SCENARIOS = ["normal", "double_commission", "capacity_40pct"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(payload)
    os.replace(temp, path)


def write_json_once(path: Path, value) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"Refuse to overwrite non-identical locked output: {path.name}")
        return
    atomic_bytes(path, payload)


def write_text_once(path: Path, text: str) -> None:
    payload = text.encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"Refuse to overwrite non-identical locked output: {path.name}")
        return
    atomic_bytes(path, payload)


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def write_csv_once(path: Path, frame: pd.DataFrame) -> None:
    payload = csv_bytes(frame)
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"Refuse to overwrite non-identical locked output: {path.name}")
        return
    atomic_bytes(path, payload)


def validate_pre_run_freeze() -> dict:
    if not FREEZE.is_file():
        raise RuntimeError("PRE_RUN_FREEZE.json must exist before any result is generated")
    frozen = read_json(FREEZE)
    expected = {
        "SEARCH_SPACE.json": sha256(SEARCH),
        "run_v7.py": sha256(Path(__file__)),
        "PROTOCOL_V7.md": sha256(PROTOCOL),
        "PUBLIC_INPUT_MANIFEST.json": sha256(INPUT / "PUBLIC_INPUT_MANIFEST.json"),
        "supermind_hushen_1.py": sha256(ENTRY),
        "backtest/engine.py": sha256(BACKTEST / "engine.py"),
        "backtest/ledger.py": sha256(BACKTEST / "ledger.py"),
        "backtest/actions.py": sha256(BACKTEST / "actions.py"),
    }
    if frozen.get("status") != "frozen_before_results" or frozen.get("sha256") != expected:
        raise RuntimeError("Pre-run freeze hash mismatch")
    if (HERE / "FINAL_LOCK.json").exists():
        raise RuntimeError("V7 is already locked; refusing to overwrite the run")
    return frozen


def validate_inputs() -> tuple[dict, pd.DatetimeIndex, pd.DataFrame]:
    manifest = read_json(INPUT / "PUBLIC_INPUT_MANIFEST.json")
    assert manifest["status"] == "sanitized_pre2025_only"
    assert manifest["cutoff"] == "2024-12-31"
    fixed = {
        "calendar.csv": manifest["calendar_sha256"],
        "universe.csv": manifest["universe_sha256"],
        "sse_price_index.parquet": manifest["sse_index_sha256"],
        "actions_pre2025.json": manifest["actions_sha256"],
    }
    for name, expected in fixed.items():
        actual = sha256(INPUT / name)
        if actual != expected:
            raise RuntimeError(f"Input hash mismatch: {name}")
    calendar = pd.read_csv(INPUT / "calendar.csv")
    calendar["calendar_date"] = pd.to_datetime(calendar.calendar_date)
    dates = pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.astype(int).eq(1), "calendar_date"])
    dates = dates[(dates >= "2013-01-01") & (dates <= "2024-12-31")]
    if dates[0] != pd.Timestamp("2013-01-04") or dates[-1] != pd.Timestamp("2024-12-31"):
        raise RuntimeError("Unexpected pre-2025 calendar coverage")
    universe = pd.read_csv(INPUT / "universe.csv", dtype=str, keep_default_na=False)
    universe = universe.loc[universe.board.eq("main")].sort_values("symbol").reset_index(drop=True)
    if not universe.symbol.is_unique:
        raise RuntimeError("Universe symbols are not unique")
    if len(manifest["files"]) != int(manifest["symbols_total"]):
        raise RuntimeError("Raw manifest total symbol count mismatch")
    records = {item["symbol"]: item for item in manifest["files"] if int(item["rows"]) > 0}
    if len(records) != int(manifest["symbols_with_rows"]):
        raise RuntimeError("Raw manifest symbol count mismatch")
    return manifest, dates, universe


def raw_path(symbol: str) -> Path:
    return INPUT / "raw" / symbol[-2:] / f"{symbol}.parquet"


def make_forward20(close: np.ndarray, preclose: np.ndarray) -> np.ndarray:
    ratio = close / preclose
    valid = np.isfinite(ratio) & (ratio > 0)
    logs = np.where(valid, np.log(ratio), 0.0)
    prefix = np.r_[0.0, np.cumsum(logs, dtype=np.float64)]
    count = np.r_[0, np.cumsum(valid.astype(np.int32))]
    result = np.full(len(close), np.nan, dtype=np.float32)
    if len(close) > 20:
        sums = prefix[21:] - prefix[1:-20]
        counts = count[21:] - count[1:-20]
        values = np.expm1(sums)
        values[counts != 20] = np.nan
        result[: len(values)] = values.astype(np.float32)
    return result


def build_factor_ranks(manifest: dict, dates: pd.DatetimeIndex, universe: pd.DataFrame):
    symbols = universe.symbol.tolist()
    columns = {s: i for i, s in enumerate(symbols)}
    shape = (len(dates), len(symbols))
    eligible = np.zeros(shape, dtype=bool)
    future20 = np.full(shape, np.nan, dtype=np.float32)
    values = {name: np.full(shape, np.nan, dtype=np.float32) for name in FACTORS}
    records = {item["symbol"]: item for item in manifest["files"] if int(item["rows"]) > 0}
    checked = 0
    for row in universe.itertuples(index=False):
        symbol = row.symbol
        if symbol not in records:
            continue
        path = raw_path(symbol)
        if sha256(path) != records[symbol]["sha256"]:
            raise RuntimeError(f"Raw input hash mismatch: {symbol}")
        checked += 1
        x = pd.read_parquet(path)
        x["date"] = pd.to_datetime(x.date)
        x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        cols = ["open", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST"]
        x = x[cols].apply(pd.to_numeric, errors="raise")
        pos = dates.get_indexer(x.index)
        take = pos >= 0
        if not take.any():
            continue
        x = x.iloc[np.flatnonzero(take)]
        pos = pos[take]
        daily = (x.close / x.preclose - 1.0).where((x.tradestatus == 1) & (x.preclose > 0), 0.0)
        vol = daily.rolling(60).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight = np.log(x.open / x.preclose).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(x.close / x.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        amount20 = x.amount.rolling(20).mean()
        cap = x.close * x.volume / (x.turn / 100.0).replace(0, np.nan)
        age = pd.Series(np.arange(len(x)) + 1, index=x.index)
        listed = pd.Series(True, index=x.index)
        if row.ipoDate:
            listed &= listed.index >= pd.Timestamp(row.ipoDate)
        if row.outDate:
            listed &= listed.index < pd.Timestamp(row.outDate)
        ok = (listed & (age >= 252) & (amount20 >= 1e7) & (x.close >= 2) &
              (x.isST == 0) & (x.tradestatus == 1) & (vol > 0.001) & (vol < 0.09))
        j = columns[symbol]
        for name, series in [("cap", cap), ("vol60", vol), ("overnight20", overnight), ("intraday20", intraday)]:
            values[name][pos, j] = series.to_numpy(dtype=np.float32)
        eligible[pos, j] = ok.to_numpy(dtype=bool)
        aligned_close = np.full(len(dates), np.nan, dtype=np.float64)
        aligned_preclose = np.full(len(dates), np.nan, dtype=np.float64)
        aligned_close[pos] = x.close.to_numpy(float)
        aligned_preclose[pos] = x.preclose.to_numpy(float)
        future20[:, j] = make_forward20(aligned_close, aligned_preclose)
        if checked % 400 == 0:
            print("FACTOR_INPUT", checked, len(records), flush=True)
    if checked != len(records):
        raise RuntimeError(f"Not all manifested raw inputs were checked: {checked}/{len(records)}")
    ranks = {}
    for name in FACTORS:
        ranked = pd.DataFrame(values.pop(name), index=dates, columns=symbols).where(eligible).rank(
            axis=1, pct=True, method="average")
        ranks[name] = ranked.to_numpy(dtype=np.float32)
        print("FACTOR_RANK", name, flush=True)
    return symbols, eligible, future20, ranks, checked


def build_ic_history(dates, eligible, future20, ranks):
    records = []
    ic_rows = []
    sample_indices = []
    for source in range(0, len(dates) - 20, 5):
        valid = eligible[source] & np.isfinite(future20[source])
        for name in FACTORS:
            valid &= np.isfinite(ranks[name][source])
        count = int(valid.sum())
        if count < 30:
            continue
        y = pd.Series(future20[source, valid]).rank(pct=True, method="average").to_numpy()
        y_std = y.std(ddof=1)
        ics = []
        for name in FACTORS:
            x = ranks[name][source, valid].astype(np.float64)
            value = float(np.corrcoef(x, y)[0, 1]) if x.std(ddof=1) > 0 and y_std > 0 else np.nan
            ics.append(value)
        if not np.isfinite(ics).all():
            continue
        sample_indices.append(source)
        ic_rows.append(ics)
        record = {
            "source_date": str(dates[source].date()),
            "completion_date": str(dates[source + 20].date()),
            "source_index": source,
            "completion_index": source + 20,
            "cross_section": count,
        }
        record.update({f"ic_{name}": value for name, value in zip(FACTORS, ics)})
        records.append(record)
    return pd.DataFrame(records), np.asarray(sample_indices), np.asarray(ic_rows, dtype=np.float64)


def online_weights(dates, sample_indices, ic_values, window, mix):
    result = np.empty((len(dates), 4), dtype=np.float64)
    section_counts = np.zeros(len(dates), dtype=np.int32)
    fallback = np.zeros(len(dates), dtype=bool)
    completed = sample_indices + 20
    for current in range(len(dates)):
        use = (completed <= current) & (sample_indices >= current - window + 1)
        count = int(use.sum())
        section_counts[current] = count
        reliability = BASE_ABS.copy()
        if count >= 60:
            medians = np.median(ic_values[use] * DIRECTION[None, :], axis=0)
            clipped = np.maximum(medians, 0.0)
            if clipped.sum() > 0:
                reliability = clipped / clipped.sum()
            else:
                fallback[current] = True
        else:
            fallback[current] = True
        absolute = (1.0 - mix) * BASE_ABS + mix * reliability
        result[current] = absolute * DIRECTION
    return result, section_counts, fallback


def extract_rankings(dates, symbols, eligible, factor_ranks, weight_matrix):
    score = np.zeros(eligible.shape, dtype=np.float32)
    complete = eligible.copy()
    for j, name in enumerate(FACTORS):
        component = factor_ranks[name]
        complete &= np.isfinite(component)
        score += np.nan_to_num(component, nan=0.0) * weight_matrix[:, j:j + 1].astype(np.float32)
    score[~complete] = np.nan
    smooth = pd.DataFrame(score, index=dates, columns=symbols).rolling(5, min_periods=3).mean()
    smooth = smooth.where(eligible)
    output = {}
    ranking_hash = hashlib.sha256()
    for i, day in enumerate(dates):
        if day < pd.Timestamp("2015-12-01"):
            continue
        ranked = smooth.iloc[i].dropna().sort_values(ascending=False, kind="mergesort").head(100).index.tolist()
        if len(ranked) < 100:
            raise RuntimeError(f"Fewer than 100 eligible rankings on {day.date()}")
        output[str(day.date())] = ranked
        ranking_hash.update(str(day.date()).encode())
        ranking_hash.update(("|".join(ranked) + "\n").encode())
    return output, ranking_hash.hexdigest()


def build_all_rankings(dates, symbols, eligible, ranks, sample_indices, ic_values):
    all_rankings = {}
    hashes = {}
    weight_records = []
    baseline_weights = np.repeat(BASE_SIGNED[None, :], len(dates), axis=0)
    all_rankings["baseline"], hashes["baseline"] = extract_rankings(
        dates, symbols, eligible, ranks, baseline_weights)
    for model, spec in MODELS.items():
        if spec is None:
            continue
        window, mix = spec
        weights, counts, fallback = online_weights(dates, sample_indices, ic_values, window, mix)
        all_rankings[model], hashes[model] = extract_rankings(dates, symbols, eligible, ranks, weights)
        for i, day in enumerate(dates):
            if day < pd.Timestamp("2015-12-01"):
                continue
            row = {"model": model, "date": str(day.date()), "window": window, "mix": mix,
                   "ic_sections": int(counts[i]), "fallback": bool(fallback[i])}
            row.update({f"weight_{name}": float(weights[i, j]) for j, name in enumerate(FACTORS)})
            weight_records.append(row)
        print("MODEL_RANK", model, flush=True)
    return all_rankings, hashes, pd.DataFrame(weight_records)


class ActionBook:
    def __init__(self):
        raw = read_json(INPUT / "actions_pre2025.json")
        self.events = {}
        for key, records in raw.items():
            symbol = key.split("/", 1)[0]
            for record in records:
                if not record.get("dividOperateDate"):
                    continue
                def number(name):
                    value = str(record.get(name, "")).strip()
                    return float(value) if value else 0.0
                day = pd.Timestamp(record["dividOperateDate"])
                if day > pd.Timestamp("2024-12-31"):
                    raise RuntimeError("Post-2024 action in sanitized input")
                self.events[(symbol, day)] = {
                    "cash": number("dividCashPsBeforeTax"),
                    "stock": number("dividStocksPs") + number("dividReserveToStockPs"),
                    "taxable_stock": number("dividStocksPs"),
                    "pay": pd.Timestamp(record.get("dividPayDate") or record["dividOperateDate"]),
                    "release": pd.Timestamp(record.get("dividStockMarketDate") or record["dividOperateDate"]),
                }


class Market:
    FIELDS = ["open", "high", "low", "close", "preclose", "volume", "isST", "tradestatus"]

    def __init__(self, dates, universe, symbols):
        self.dates = dates
        self.index = {day: i for i, day in enumerate(dates)}
        self.symbols = sorted(symbols)
        self.columns = {s: j for j, s in enumerate(self.symbols)}
        shape = (len(dates), len(self.symbols))
        self.data = {name: np.full(shape, np.nan, dtype=np.float64) for name in self.FIELDS}
        self.volume20 = np.full(shape, np.nan, dtype=np.float64)
        self.prev_actual = np.full(shape, np.nan, dtype=np.float64)
        self.present = np.zeros(shape, dtype=bool)
        for j, symbol in enumerate(self.symbols):
            x = pd.read_parquet(raw_path(symbol))
            x["date"] = pd.to_datetime(x.date)
            x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
            x = x[self.FIELDS].apply(pd.to_numeric, errors="raise")
            pos = dates.get_indexer(x.index)
            valid = pos >= 0
            x = x.iloc[np.flatnonzero(valid)]
            pos = pos[valid]
            for name in self.FIELDS:
                self.data[name][pos, j] = x[name].to_numpy(float)
            self.volume20[pos, j] = x.volume.rolling(20).mean().to_numpy(float)
            self.prev_actual[pos, j] = x.close.shift().to_numpy(float)
            self.present[pos, j] = True
        meta = universe.set_index("symbol")
        self.outs = {s: pd.Timestamp(meta.loc[s, "outDate"]) for s in self.symbols if meta.loc[s, "outDate"]}
        self.actions = ActionBook()
        bench = pd.read_parquet(INPUT / "sse_price_index.parquet")
        bench["date"] = pd.to_datetime(bench.date)
        self.benchmark = bench.set_index("date").sort_index()

    def row(self, date, symbol):
        j = self.columns.get(symbol)
        if j is None:
            return None
        i = self.index[date]
        if not self.present[i, j]:
            return None
        return {name: self.data[name][i, j] for name in self.FIELDS} | {
            "volume20": self.volume20[i, j], "prev_actual": self.prev_actual[i, j]
        }


@dataclass
class Lot:
    quantity: int
    buy: pd.Timestamp
    release: pd.Timestamp
    dividend_basis: float = 0.0


@dataclass
class Position:
    quantity: int
    last: float
    lots: list[Lot] = field(default_factory=list)


class Account:
    def __init__(self, market: Market, rankings: dict, start, end, model, scenario):
        self.market = market
        self.rankings = rankings
        self.start = pd.Timestamp(start)
        self.end = pd.Timestamp(end)
        self.model = model
        self.scenario = scenario
        self.cash = 100000.0
        self.receivables = []
        self.holdings = {}
        self.targets = {}
        self.close_quantity = {}
        self.first = True
        self.fees = 0.0
        self.tax = 0.0
        self.trades = 0
        self.rejected = 0
        self.capacity_hits = 0
        self.issues = {}
        self.reference = {}
        self.curve = []
        self.commission_rate = 0.0006 if scenario == "double_commission" else 0.0003
        self.min_commission = 10.0 if scenario == "double_commission" else 5.0
        self.capacity_scale = 0.4 if scenario == "capacity_40pct" else 1.0
        self.anchor = self.market.index[pd.Timestamp("2018-01-02")]

    def available(self, symbol, date):
        return sum(lot.quantity for lot in self.holdings[symbol].lots if lot.release <= date and lot.buy < date)

    def limits(self, row):
        pct = 0.05 if bool(row["isST"]) else 0.10
        high = math.floor(row["preclose"] * (1.0 + pct) * 100.0 + 0.5) / 100.0
        low = math.floor(row["preclose"] * (1.0 - pct) * 100.0 + 0.5) / 100.0
        return high, low

    def valid_bar(self, row):
        if row is None or int(row["tradestatus"]) != 1:
            return False
        high, low = self.limits(row)
        return np.isfinite(row["open"]) and row["open"] > 0 and 0 < low <= row["open"] <= high

    def equity_at_open(self, date):
        value = self.cash + sum(amount for _, amount in self.receivables)
        for symbol, position in self.holdings.items():
            row = self.market.row(date, symbol)
            price = row["open"] if self.valid_bar(row) else position.last
            value += position.quantity * price
        return value

    def corporate(self, date):
        pending = []
        for pay, amount in self.receivables:
            if pay <= date:
                self.cash += amount
            else:
                pending.append((pay, amount))
        self.receivables = pending
        for symbol in list(self.holdings):
            position = self.holdings[symbol]
            row = self.market.row(date, symbol)
            action = self.market.actions.events.get((symbol, date))
            if action:
                old = position.quantity
                cash = old * action["cash"]
                if action["pay"] <= date:
                    self.cash += cash
                else:
                    self.receivables.append((action["pay"], cash))
                additions = []
                remaining = int(math.floor(old * action["stock"] + 1e-8))
                original_lots = list(position.lots)
                for number, lot in enumerate(original_lots):
                    bonus = min(remaining, int(math.floor(lot.quantity * action["stock"] + 1e-8)))
                    if number == len(original_lots) - 1:
                        bonus = remaining
                    remaining -= bonus
                    taxable = (action["cash"] + action["taxable_stock"]) if date <= lot.buy + pd.DateOffset(years=1) else 0.0
                    liability = lot.dividend_basis + taxable
                    lot.dividend_basis = liability * lot.quantity / (lot.quantity + bonus)
                    if bonus:
                        additions.append(Lot(bonus, lot.buy, action["release"], lot.dividend_basis))
                position.lots.extend(additions)
                position.lots.sort(key=lambda lot: (lot.buy, lot.release))
                position.quantity = sum(lot.quantity for lot in position.lots)
                if row is not None:
                    position.last = row["preclose"]
                    expected = (row["prev_actual"] - action["cash"]) / (1.0 + action["stock"])
                    if np.isfinite(expected) and abs(row["preclose"] - expected) > max(0.025, row["preclose"] * 0.0001):
                        self.reference[f"{symbol}/{date.date()}"] = [row["prev_actual"], row["preclose"], action]
            elif row is not None and np.isfinite(row["prev_actual"]) and row["prev_actual"] > 0:
                ratio = row["preclose"] / row["prev_actual"]
                if abs(ratio - 1.0) > 1e-5:
                    self.issues[f"{symbol}/{date.date()}"] = float(ratio)
            out = self.market.outs.get(symbol)
            if out is not None and date >= out:
                self.issues[f"{symbol}/{date.date()}"] = "delisting zero-recovery assumption"
                del self.holdings[symbol]
        for symbol, previous in self.close_quantity.items():
            current = self.holdings[symbol].quantity if symbol in self.holdings else 0
            if previous > 0 and current > 0 and previous != current and symbol in self.targets:
                self.targets[symbol] = int(math.floor(self.targets[symbol] * current / previous + 1e-8))

    def buy_cost_buffer(self, quantity, open_price):
        value = quantity * (open_price * 1.001 + 0.01)
        return value + max(self.min_commission, value * self.commission_rate) + value * 0.00002

    def order(self, date, symbol, quantity, limit):
        row = self.market.row(date, symbol)
        if row is None or int(row["tradestatus"]) != 1 or row["volume"] <= 0:
            self.rejected += 1
            return False
        high_limit, low_limit = self.limits(row)
        if quantity > 0:
            if row["open"] >= high_limit - 1e-8 or limit < row["open"] - 1e-8:
                self.rejected += 1
                return False
            proposed = min(limit, row["open"] * 1.001, row["high"], high_limit)
            if proposed < max(row["low"], low_limit) - 1e-8:
                self.rejected += 1
                return False
        else:
            if row["open"] <= low_limit + 1e-8 or limit > row["open"] + 1e-8:
                self.rejected += 1
                return False
            proposed = max(limit, row["open"] * 0.999, row["low"], low_limit)
            if proposed > min(row["high"], high_limit) + 1e-8:
                self.rejected += 1
                return False
        price = round(float(proposed), 2)
        if (quantity > 0 and price > limit + 1e-8) or (quantity < 0 and price < limit - 1e-8):
            self.rejected += 1
            return False
        daily_cap = int(row["volume"] * 0.25 * self.capacity_scale / 100.0) * 100
        if abs(quantity) > daily_cap:
            self.capacity_hits += 1
            self.rejected += 1
            return False
        value = round(abs(quantity) * price, 2)
        commission = round(max(self.min_commission, value * self.commission_rate), 2)
        transfer_rate = 0.00002 if date < pd.Timestamp("2022-04-29") else 0.00001
        transfer = round(value * transfer_rate, 2)
        stamp_rate = 0.001 if date < pd.Timestamp("2023-08-28") else 0.0005
        stamp = round(value * stamp_rate, 2) if quantity < 0 else 0.0
        fees = commission + transfer + stamp
        dividend_tax = 0.0
        if quantity > 0:
            if value + fees > self.cash + 1e-6:
                self.rejected += 1
                return False
            if quantity % 100:
                raise RuntimeError("Buy is not an integer lot")
            self.cash -= value + fees
            position = self.holdings.setdefault(symbol, Position(0, price, []))
            position.quantity += quantity
            position.last = price
            position.lots.append(Lot(quantity, date, date + pd.Timedelta(days=1), 0.0))
        else:
            if symbol not in self.holdings or -quantity > self.available(symbol, date):
                self.rejected += 1
                return False
            position = self.holdings[symbol]
            remaining = -quantity
            for lot in position.lots:
                if lot.release > date or lot.buy >= date:
                    continue
                take = min(remaining, lot.quantity)
                remaining -= take
                lot.quantity -= take
                rate = 0.2 if date <= lot.buy + pd.DateOffset(months=1) else (0.1 if date <= lot.buy + pd.DateOffset(years=1) else 0.0)
                dividend_tax += take * lot.dividend_basis * rate
                if remaining == 0:
                    break
            if remaining:
                raise RuntimeError("FIFO availability mismatch")
            dividend_tax = round(dividend_tax, 2)
            position.lots = [lot for lot in position.lots if lot.quantity]
            position.quantity += quantity
            position.last = price
            self.cash += value - fees - dividend_tax
            if position.quantity == 0:
                del self.holdings[symbol]
        self.fees += fees
        self.tax += dividend_tax
        self.trades += 1
        return True

    def run_day(self, date):
        self.corporate(date)
        actual = self.market.index[date]
        previous_date = self.market.dates[actual - 1]
        signal = str(previous_date.date())
        shifted = actual - self.anchor
        rebalance = self.first or (shifted - 1) % 20 == 0
        nav_open = self.equity_at_open(date)
        ranks = self.rankings[signal]
        if rebalance:
            budget = nav_open * 0.98 / 5.0
            keep = set(ranks[:7])
            def selectable(symbol):
                row = self.market.row(date, symbol)
                return (self.valid_bar(row) and not bool(row["isST"]) and
                        row["open"] < self.limits(row)[0] - 1e-8 and
                        self.buy_cost_buffer(100, row["open"]) <= budget)
            selected = [s for s in ranks if s in self.holdings and s in keep and selectable(s)][:5]
            for symbol in ranks:
                if len(selected) >= 5:
                    break
                if symbol not in selected and selectable(symbol):
                    selected.append(symbol)
            targets = {s: 0 for s in self.holdings if s not in selected}
            for symbol in selected:
                row = self.market.row(date, symbol)
                targets[symbol] = int(budget / row["open"] / 100.0) * 100
            self.targets = targets
            self.first = False
        for symbol in self.holdings:
            prior = self.market.row(previous_date, symbol)
            if prior is not None and bool(prior["isST"]):
                self.targets[symbol] = 0
        cash_budget = self.cash
        def delta(symbol):
            return self.targets[symbol] - (self.holdings[symbol].quantity if symbol in self.holdings else 0)
        for symbol in sorted(self.targets, key=lambda s: (delta(s) >= 0, s)):
            current = self.holdings[symbol].quantity if symbol in self.holdings else 0
            difference = self.targets[symbol] - current
            row = self.market.row(date, symbol)
            if difference == 0 or not self.valid_bar(row):
                continue
            prior = self.market.row(previous_date, symbol)
            average_volume = prior["volume20"] if prior is not None else np.nan
            if not np.isfinite(average_volume):
                continue
            average_cap = int(average_volume * 0.005 * self.capacity_scale / 100.0) * 100
            quantity = min(abs(difference), average_cap, 1000000)
            high_limit, low_limit = self.limits(row)
            if difference < 0:
                if row["open"] <= low_limit + 1e-8:
                    continue
                quantity = min(quantity, self.available(symbol, date))
                if quantity != current:
                    quantity = int(quantity // 100) * 100
                if quantity > 0:
                    limit = max(low_limit, math.floor(row["open"] * 0.999 * 100.0 + 1e-8) / 100.0)
                    before = self.cash
                    if self.order(date, symbol, -int(quantity), limit):
                        cash_budget += max(0.0, self.cash - before)
            else:
                if bool(row["isST"]) or row["open"] >= high_limit - 1e-8:
                    continue
                quantity = int(quantity // 100) * 100
                available = min(cash_budget, self.cash)
                while quantity > 0 and self.buy_cost_buffer(quantity, row["open"]) > available:
                    quantity -= 100
                if quantity > 0:
                    limit = min(high_limit, math.ceil(row["open"] * 1.001 * 100.0 - 1e-8) / 100.0)
                    if self.order(date, symbol, int(quantity), limit):
                        cash_budget -= self.buy_cost_buffer(quantity, row["open"])
        market_value = 0.0
        for symbol, position in self.holdings.items():
            row = self.market.row(date, symbol)
            if row is not None and np.isfinite(row["close"]) and row["close"] > 0:
                position.last = row["close"]
            if position.quantity != sum(lot.quantity for lot in position.lots):
                raise RuntimeError("Position lot mismatch")
            market_value += position.quantity * position.last
        equity = self.cash + market_value + sum(amount for _, amount in self.receivables)
        if self.cash < -0.01:
            raise RuntimeError("Negative cash")
        self.curve.append(equity)
        self.close_quantity = {s: p.quantity for s, p in self.holdings.items()}

    def result(self):
        sessions = self.market.dates[(self.market.dates >= self.start) & (self.market.dates <= self.end)]
        for date in sessions:
            self.run_day(date)
        nav = np.asarray(self.curve, dtype=np.float64)
        returns = nav / np.r_[100000.0, nav[:-1]] - 1.0
        days = (sessions[-1] - sessions[0]).days + 1
        total = nav[-1] / 100000.0 - 1.0
        cagr = (nav[-1] / 100000.0) ** (365.25 / days) - 1.0
        peak = np.maximum.accumulate(np.r_[100000.0, nav])[1:]
        drawdown = float((1.0 - nav / peak).max())
        sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else np.nan
        bench = self.market.benchmark
        bench_total = float(bench.loc[sessions[-1], "close"] / bench.loc[sessions[0], "open"] - 1.0)
        bench_cagr = (1.0 + bench_total) ** (365.25 / days) - 1.0
        return {
            "model": self.model, "scenario": self.scenario,
            "requested_start": str(self.start.date()), "actual_start": str(sessions[0].date()),
            "end": str(sessions[-1].date()), "year": int(sessions[0].year),
            "final_equity": float(nav[-1]), "total_return": float(total), "cagr": float(cagr),
            "benchmark_total_return": bench_total, "benchmark_cagr": float(bench_cagr),
            "excess_cagr": float(cagr - bench_cagr), "max_drawdown": drawdown,
            "sharpe": sharpe, "trades": self.trades, "transaction_fees": self.fees,
            "dividend_tax": self.tax, "total_cost": self.fees + self.tax,
            "rejected_orders": self.rejected, "capacity_hits": self.capacity_hits,
            "unresolved_actions": len(self.issues), "reference_differences": len(self.reference),
        }


def all_starts(dates):
    starts = []
    for year in range(2016, 2025):
        current = dates[(dates.year == year) & (dates.month <= 3)]
        if len(current) == 0:
            raise RuntimeError(f"No Q1 starts for {year}")
        starts.extend(current.tolist())
    return pd.DatetimeIndex(starts)


def run_backtests(market, rankings):
    partial = HERE / "start_results.partial.csv"
    completed_output = HERE / "start_results.csv"
    resume = partial if partial.exists() else completed_output
    if resume.exists():
        done_frame = pd.read_csv(resume)
        results = done_frame.to_dict("records")
        done = set(zip(done_frame.model, done_frame.scenario, done_frame.requested_start))
    else:
        results, done = [], set()
    starts = all_starts(market.dates)
    total = len(starts) * len(MODELS) * len(SCENARIOS)
    completed = len(done)
    for scenario in SCENARIOS:
        for model in MODELS:
            for start in starts:
                key = (model, scenario, str(start.date()))
                if key in done:
                    continue
                end = market.dates[market.dates.year == start.year][-1]
                account = Account(market, rankings[model], start, end, model, scenario)
                results.append(account.result())
                done.add(key)
                completed += 1
                if completed % 25 == 0 or completed == total:
                    frame = pd.DataFrame(results).sort_values(["scenario", "model", "requested_start"])
                    atomic_bytes(partial, csv_bytes(frame))
                    print("BACKTEST", completed, total, flush=True)
    frame = pd.DataFrame(results).sort_values(["scenario", "model", "requested_start"]).reset_index(drop=True)
    if len(frame) != total or frame[["model", "scenario", "requested_start"]].duplicated().any():
        raise RuntimeError("Backtest result key mismatch")
    return frame


def evaluate(results):
    normal = results.loc[results.scenario.eq("normal")].copy()
    annual = normal.groupby(["model", "year"], as_index=False).agg(
        starts=("requested_start", "size"), median_excess=("excess_cagr", "median"),
        mean_excess=("excess_cagr", "mean"), mean_cagr=("cagr", "mean"),
        min_cagr=("cagr", "min"), mean_drawdown=("max_drawdown", "mean"),
        mean_sharpe=("sharpe", "mean"), mean_cost=("total_cost", "mean"),
        unresolved_actions=("unresolved_actions", "sum"), reference_differences=("reference_differences", "sum"))
    annual["segment"] = np.where(annual.year <= 2019, "2016-2019", "2020-2024")
    baseline_annual = annual.loc[annual.model.eq("baseline"), ["year", "median_excess", "mean_excess", "mean_cagr"]].rename(
        columns={"median_excess": "baseline_median_excess", "mean_excess": "baseline_mean_excess", "mean_cagr": "baseline_mean_cagr"})
    annual = annual.merge(baseline_annual, on="year", how="left")
    annual["median_excess_improvement"] = annual.median_excess - annual.baseline_median_excess
    annual["mean_excess_improvement"] = annual.mean_excess - annual.baseline_mean_excess
    annual["mean_cagr_delta"] = annual.mean_cagr - annual.baseline_mean_cagr
    segment = normal.assign(segment=np.where(normal.year <= 2019, "2016-2019", "2020-2024")).groupby(
        ["model", "segment"], as_index=False).agg(mean_excess=("excess_cagr", "mean"), mean_cagr=("cagr", "mean"))
    base_segment = segment.loc[segment.model.eq("baseline"), ["segment", "mean_excess", "mean_cagr"]].rename(
        columns={"mean_excess": "baseline_mean_excess", "mean_cagr": "baseline_mean_cagr"})
    segment = segment.merge(base_segment, on="segment", how="left")
    segment["excess_improvement"] = segment.mean_excess - segment.baseline_mean_excess
    segment["cagr_delta"] = segment.mean_cagr - segment.baseline_mean_cagr
    base_start = normal.loc[normal.model.eq("baseline"), ["requested_start", "excess_cagr"]].rename(columns={"excess_cagr": "baseline_excess"})
    gates = []
    sibling = {"online_w504_m025": "online_w504_m050", "online_w504_m050": "online_w504_m025",
               "online_w756_m025": "online_w756_m050", "online_w756_m050": "online_w756_m025"}
    baseline_std = annual.loc[annual.model.eq("baseline"), "median_excess"].std(ddof=1)
    for model in MODELS:
        if model == "baseline":
            continue
        a = annual.loc[annual.model.eq(model)].sort_values("year")
        s = segment.loc[segment.model.eq(model)].sort_values("segment")
        paired = normal.loc[normal.model.eq(model), ["requested_start", "year", "excess_cagr"]].merge(base_start, on="requested_start")
        paired["improvement"] = paired.excess_cagr - paired.baseline_excess
        loo = {str(year): float(paired.loc[paired.year.ne(year), "improvement"].mean()) for year in range(2016, 2025)}
        positives = a.mean_excess_improvement.clip(lower=0)
        contribution = float(positives.max() / positives.sum()) if positives.sum() > 0 else np.inf
        sib = segment.loc[segment.model.eq(sibling[model])]
        checks = {
            "all_nine_annual_median_excess_positive": bool(len(a) == 9 and (a.median_excess > 0).all()),
            "both_segments_excess_above_baseline": bool(len(s) == 2 and (s.excess_improvement > 0).all()),
            "both_segments_cagr_drop_within_2pp": bool(len(s) == 2 and (s.cagr_delta >= -0.02).all()),
            "at_least_seven_years_median_excess_improved": bool((a.median_excess_improvement > 0).sum() >= 7),
            "more_than_half_starts_improved": bool((paired.improvement > 0).mean() > 0.5),
            "annual_median_excess_std_not_above_baseline": bool(a.median_excess.std(ddof=1) <= baseline_std + 1e-15),
            "all_leave_one_year_out_improvements_positive": bool(all(value > 0 for value in loo.values())),
            "single_year_positive_contribution_below_50pct": bool(contribution < 0.5),
            "sibling_improves_both_segments": bool(len(sib) == 2 and (sib.excess_improvement > 0).all()),
            "execution_integrity_clean": bool((a.unresolved_actions.sum() + a.reference_differences.sum()) == 0),
        }
        failures = [name for name, passed in checks.items() if not passed]
        full = normal.loc[normal.model.eq(model)]
        gates.append({
            "model": model, "passed": len(failures) == 0, "failure_reasons": ";".join(failures),
            **checks, "worst_annual_median_excess": float(a.median_excess.min()),
            "min_segment_excess_improvement": float(s.excess_improvement.min()),
            "annual_median_excess_std": float(a.median_excess.std(ddof=1)),
            "full_mean_cagr": float(full.cagr.mean()), "minimum_start_cagr": float(full.cagr.min()),
            "mean_max_drawdown": float(full.max_drawdown.mean()), "mean_sharpe": float(full.sharpe.mean()),
            "mean_total_cost": float(full.total_cost.mean()), "improved_years": int((a.median_excess_improvement > 0).sum()),
            "improved_start_fraction": float((paired.improvement > 0).mean()),
            "largest_positive_year_contribution": contribution,
            "leave_one_year_out_min_improvement": float(min(loo.values())),
        })
    gates = pd.DataFrame(gates)
    passers = gates.loc[gates.passed].sort_values(
        ["worst_annual_median_excess", "min_segment_excess_improvement", "annual_median_excess_std",
         "full_mean_cagr", "minimum_start_cagr", "mean_max_drawdown", "mean_sharpe", "mean_total_cost"],
        ascending=[False, False, True, False, False, True, False, True]).copy()
    passers.insert(0, "rank", np.arange(1, len(passers) + 1))
    stress = results.groupby(["model", "scenario"], as_index=False).agg(
        starts=("requested_start", "size"), mean_cagr=("cagr", "mean"), median_excess=("excess_cagr", "median"),
        minimum_cagr=("cagr", "min"), mean_drawdown=("max_drawdown", "mean"),
        mean_sharpe=("sharpe", "mean"), mean_cost=("total_cost", "mean"),
        unresolved_actions=("unresolved_actions", "sum"), reference_differences=("reference_differences", "sum"))
    return annual, segment, gates, passers, stress


def markdown_report(results, annual, segment, gates, passers, stress, audit):
    passed = passers.model.tolist()
    lines = ["# 沪深1 V7 在线冻结因子权重研究", "", f"结论：{'有候选通过：' + ', '.join(passed) if passed else '没有候选通过；按协议保留精确基线。'}", "",
             f"- 白名单边界：2013—2024；评价为 2016—2024 每年第一季度全部交易日起点，共 {results.requested_start.nunique()} 个。",
             "- 候选：504/756 交易日 IC 窗口 × 0.25/0.50 混合；未搜索协议外参数。",
             "- 标签：随后 20 个交易日 close/preclose 经济收益，只有完成日不晚于当前信号日的截面可进入在线权重。",
             "- 执行：前一完整日信号、下一开盘、整手、T+1、停牌、涨跌停、成交量、历史费率与公司行动。",
             "- 压力：双倍佣金与 40% 容量；全部候选及基线均已运行。", "", "## 门槛结果", "",
             "| 候选 | 通过 | 最差年度中位超额 | 较弱分段超额改善 | 改善年度 | 改善起点占比 | 失败原因 |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for row in gates.itertuples(index=False):
        lines.append(f"| {row.model} | {'是' if row.passed else '否'} | {row.worst_annual_median_excess:.2%} | {row.min_segment_excess_improvement:.2%} | {row.improved_years} | {row.improved_start_fraction:.2%} | {row.failure_reasons or '—'} |")
    lines += ["", "## 分段结果（正常费用）", "", "| 模型 | 分段 | 平均年化 | 平均年化超额 | 相对基线超额改善 | 相对基线年化变化 |", "|---|---|---:|---:|---:|---:|"]
    for row in segment.itertuples(index=False):
        lines.append(f"| {row.model} | {row.segment} | {row.mean_cagr:.2%} | {row.mean_excess:.2%} | {row.excess_improvement:.2%} | {row.cagr_delta:.2%} |")
    lines += ["", "## 压力汇总", "", "| 模型 | 场景 | 平均年化 | 中位超额 | 最低年化 | 平均回撤 | 平均成本 | 完整性问题 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in stress.itertuples(index=False):
        issues = int(row.unresolved_actions + row.reference_differences)
        lines.append(f"| {row.model} | {row.scenario} | {row.mean_cagr:.2%} | {row.median_excess:.2%} | {row.minimum_cagr:.2%} | {row.mean_drawdown:.2%} | {row.mean_cost:.2f} | {issues} |")
    lines += ["", "## 审计", "", f"- 代码哈希：`{audit['code_sha256']}`", f"- 搜索空间哈希：`{audit['search_space_sha256']}`",
              f"- 排名集合哈希：`{canonical_hash(audit['ranking_sha256'])}`", "- 逐起点、逐年度、分段、门槛、压力和失败原因见同目录 CSV。", ""]
    return "\n".join(lines)


def finalize_lock():
    names = ["SEARCH_SPACE.json", "run_v7.py", "PRE_RUN_FREEZE.json", "PRE_RUN_FREEZE_ATTEMPT1.json",
             "PRE_RUN_FAILURES.json", "ic_history.csv", "weight_history.csv",
             "start_results.csv", "annual_summary.csv", "segment_summary.csv", "gate_results.csv",
             "candidate_ranking.csv", "stress_summary.csv", "AUDIT.json", "REPORT.md"]
    hashes = {name: sha256(HERE / name) for name in names}
    write_json_once(HERE / "FINAL_LOCK.json", {"status": "permanently_locked", "sha256": hashes,
                                                "aggregate_sha256": canonical_hash(hashes)})


def main():
    frozen = validate_pre_run_freeze()
    manifest, dates, universe = validate_inputs()
    symbols, eligible, future20, factor_ranks, checked = build_factor_ranks(manifest, dates, universe)
    ic_frame, sample_indices, ic_values = build_ic_history(dates, eligible, future20, factor_ranks)
    rankings, ranking_hashes, weights = build_all_rankings(
        dates, symbols, eligible, factor_ranks, sample_indices, ic_values)
    write_csv_once(HERE / "ic_history.csv", ic_frame)
    write_csv_once(HERE / "weight_history.csv", weights)
    runtime_symbols = sorted({symbol for model in rankings.values() for values in model.values() for symbol in values})
    del eligible, future20, factor_ranks
    market = Market(dates, universe, runtime_symbols)
    results = run_backtests(market, rankings)
    annual, segment, gates, passers, stress = evaluate(results)
    write_csv_once(HERE / "start_results.csv", results)
    partial = HERE / "start_results.partial.csv"
    if partial.exists():
        partial.unlink()
    write_csv_once(HERE / "annual_summary.csv", annual)
    write_csv_once(HERE / "segment_summary.csv", segment)
    write_csv_once(HERE / "gate_results.csv", gates)
    write_csv_once(HERE / "candidate_ranking.csv", passers)
    write_csv_once(HERE / "stress_summary.csv", stress)
    audit = {
        "status": "complete", "instruction_boundary_version": "public-pre2025-v2",
        "post_2024_data_read": False, "pre_run_freeze": frozen,
        "code_sha256": sha256(Path(__file__)), "search_space_sha256": sha256(SEARCH),
        "input_manifest_sha256": sha256(INPUT / "PUBLIC_INPUT_MANIFEST.json"),
        "raw_files_hash_verified": checked, "raw_manifest_files": len(manifest["files"]),
        "calendar_start": str(dates[0].date()), "calendar_end": str(dates[-1].date()),
        "ic_sections": len(ic_frame), "runtime_symbols": len(runtime_symbols),
        "ranking_sha256": ranking_hashes, "models": list(MODELS), "scenarios": SCENARIOS,
        "q1_starts": int(results.requested_start.nunique()), "result_rows": len(results),
        "passed_candidates": passers.model.tolist(),
        "selection": passers.model.iloc[0] if len(passers) else "baseline",
        "no_gate_relaxation": True,
    }
    write_json_once(HERE / "AUDIT.json", audit)
    write_text_once(HERE / "REPORT.md", markdown_report(results, annual, segment, gates, passers, stress, audit))
    finalize_lock()
    print("COMPLETE", audit["selection"], "passed", audit["passed_candidates"], flush=True)


if __name__ == "__main__":
    main()
