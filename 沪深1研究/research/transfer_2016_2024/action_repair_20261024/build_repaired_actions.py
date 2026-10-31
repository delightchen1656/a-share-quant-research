"""Build and audit a pre-2025 corporate-action snapshot from frozen BaoStock replies.

The original sanitized file is never modified.  Queried symbol/year keys are
replaced by the corresponding frozen response (including successful empty
responses), and duplicate ex-date rows are resolved against the unadjusted
price reference when one is available.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INPUT = ROOT / "inputs_pre2025"
ORIGINAL = INPUT / "actions_pre2025.json"
PLAN = HERE / "full_market_query_plan.json"
RESPONSES = HERE / "full_responses"
FETCH_MANIFEST = HERE / "FULL_MANIFEST.json"
OUTPUT = INPUT / "actions_pre2025_repaired_20261024.json"
AUDIT_CSV = HERE / "repaired_action_coverage.csv"
MANIFEST = HERE / "REPAIR_MANIFEST.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def number(row: dict, field: str) -> float:
    try:
        return float(row.get(field) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def economic_terms(row: dict) -> tuple[float, float]:
    cash = number(row, "dividCashPsBeforeTax")
    stock = number(row, "dividStocksPs") + number(row, "dividReserveToStockPs")
    return cash, stock


def expected_preclose(prev_close: float, row: dict) -> float:
    cash, stock = economic_terms(row)
    return (prev_close - cash) / (1.0 + stock)


@lru_cache(maxsize=8)
def load_reference(symbol: str) -> dict[str, tuple[float, float]]:
    exchange = "SH" if symbol.endswith(".SH") else "SZ"
    path = INPUT / "raw" / exchange / f"{symbol}.parquet"
    if not path.exists():
        return {}
    frame = pd.read_parquet(path, columns=["date", "close", "preclose"])
    frame["date"] = pd.to_datetime(frame.date)
    frame = frame.sort_values("date")
    frame["prev_actual"] = frame.close.shift(1)
    return {
        row.date.strftime("%Y-%m-%d"): (float(row.prev_actual), float(row.preclose))
        for row in frame.itertuples()
        if pd.notna(row.prev_actual) and pd.notna(row.preclose)
    }


def choose_duplicate(rows: list[dict], reference: tuple[float, float] | None) -> tuple[dict, dict]:
    def completeness(row: dict) -> int:
        return sum(bool(row.get(k)) for k in row)

    scored = []
    for index, row in enumerate(rows):
        cash, stock = economic_terms(row)
        if reference:
            prev_close, preclose = reference
            error = abs(expected_preclose(prev_close, row) - preclose)
        else:
            error = float("inf")
        scored.append((error, -(cash != 0 or stock != 0), -completeness(row), index, row))
    scored.sort(key=lambda item: item[:4])
    selected = scored[0][4]
    detail = {
        "candidates": len(rows),
        "selected_index": scored[0][3],
        "reference_error": None if scored[0][0] == float("inf") else scored[0][0],
    }
    return selected, detail


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    fetch_manifest = json.loads(FETCH_MANIFEST.read_text(encoding="utf-8"))
    expected_names = {f"{symbol}_{year}.json" for symbol, year in plan}
    if set(fetch_manifest) != expected_names:
        missing = sorted(expected_names - set(fetch_manifest))[:10]
        raise RuntimeError(f"Fetch is incomplete: {len(fetch_manifest)}/{len(expected_names)}; sample={missing}")
    for name, item in fetch_manifest.items():
        if sha256(RESPONSES / name) != item["sha256"]:
            raise RuntimeError(f"Response hash mismatch: {name}")

    repaired = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    duplicate_decisions = []
    queried = set()
    for symbol, year_value in plan:
        year = int(year_value)
        key = f"{symbol}/{year}"
        queried.add(key)
        payload = json.loads((RESPONSES / f"{symbol}_{year}.json").read_text(encoding="utf-8"))
        rows = payload["records"]
        grouped: dict[str, list[dict]] = defaultdict(list)
        no_date = []
        for row in rows:
            date = row.get("dividOperateDate", "")
            if date and date <= "2024-12-31":
                grouped[date].append(row)
            elif not date:
                no_date.append(row)
            else:
                raise RuntimeError(f"Post-cutoff row in {key}: {date}")
        reference = load_reference(symbol)
        selected = []
        for date, candidates in sorted(grouped.items()):
            chosen, detail = choose_duplicate(candidates, reference.get(date))
            selected.append(chosen)
            if len(candidates) > 1:
                duplicate_decisions.append({"key": key, "date": date, **detail})
        # Undated rows cannot drive account events, but retain one if this is
        # all the provider returned so the successful query remains auditable.
        if not selected and no_date:
            chosen, detail = choose_duplicate(no_date, None)
            selected.append(chosen)
            if len(no_date) > 1:
                duplicate_decisions.append({"key": key, "date": "", **detail})
        repaired[key] = selected

    # The original snapshot also contains duplicate same-date rows, sometimes
    # with the economically complete record followed by an empty duplicate.
    # Canonicalize every key, not only newly queried keys.
    duplicate_decisions = []
    for key, rows in list(repaired.items()):
        symbol, year_text = key.split("/")
        reference = load_reference(symbol)
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row.get("dividOperateDate", "")].append(row)
        canonical = []
        for date, candidates in sorted(grouped.items()):
            chosen, detail = choose_duplicate(candidates, reference.get(date) if date else None)
            canonical.append(chosen)
            if len(candidates) > 1:
                duplicate_decisions.append({"key": key, "date": date, **detail})
        repaired[key] = canonical

    if any(row.get("dividOperateDate", "") > "2024-12-31" for rows in repaired.values() for row in rows):
        raise RuntimeError("Post-2024 action escaped into repaired snapshot")
    write_json(OUTPUT, dict(sorted(repaired.items())))

    # Full price-reference audit.  A discontinuity is considered explained
    # when the official action reproduces rounded preclose within 1.1 cents.
    events = []
    action_by_symbol_date = {}
    for key, rows in repaired.items():
        symbol, _ = key.split("/")
        for row in rows:
            date = row.get("dividOperateDate", "")
            if date:
                action_by_symbol_date[symbol, date] = row
    public_manifest = json.loads((INPUT / "PUBLIC_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    total_discontinuities = 0
    explained = 0
    for entry in public_manifest["files"]:
        if "path" not in entry:
            continue
        symbol = entry["symbol"]
        path = ROOT / entry["path"]
        frame = pd.read_parquet(path, columns=["date", "close", "preclose"])
        frame["date"] = pd.to_datetime(frame.date)
        frame = frame.sort_values("date")
        frame["prev_actual"] = frame.close.shift(1)
        for row in frame.itertuples():
            if pd.isna(row.prev_actual) or pd.isna(row.preclose):
                continue
            if abs(float(row.preclose) - float(row.prev_actual)) <= 0.011:
                continue
            total_discontinuities += 1
            date = row.date.strftime("%Y-%m-%d")
            action = action_by_symbol_date.get((symbol, date))
            error = None
            if action:
                error = abs(expected_preclose(float(row.prev_actual), action) - float(row.preclose))
            ok = error is not None and error <= 0.011
            explained += int(ok)
            if not ok:
                events.append({
                    "symbol": symbol, "date": date, "year": row.date.year,
                    "prev_close": float(row.prev_actual), "preclose": float(row.preclose),
                    "has_action": bool(action), "reference_error": error,
                })
    pd.DataFrame(events).to_csv(AUDIT_CSV, index=False, encoding="utf-8-sig")
    write_json(MANIFEST, {
        "status": "repaired_pre2025_only",
        "cutoff": "2024-12-31",
        "original_sha256": sha256(ORIGINAL),
        "query_plan_sha256": sha256(PLAN),
        "fetch_manifest_sha256": sha256(FETCH_MANIFEST),
        "output": str(OUTPUT.relative_to(ROOT)),
        "output_sha256": sha256(OUTPUT),
        "queried_keys": len(queried),
        "total_keys": len(repaired),
        "duplicate_decisions": duplicate_decisions,
        "coverage": {
            "price_discontinuities": total_discontinuities,
            "explained_within_0.011": explained,
            "unresolved": len(events),
        },
        "unresolved_csv_sha256": sha256(AUDIT_CSV),
    })
    print(json.dumps({"output": str(OUTPUT), "keys": len(repaired),
                      "duplicates": len(duplicate_decisions), "discontinuities": total_discontinuities,
                      "explained": explained, "unresolved": len(events)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
