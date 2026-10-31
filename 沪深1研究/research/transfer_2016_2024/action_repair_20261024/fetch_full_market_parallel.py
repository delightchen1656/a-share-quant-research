"""Resume the frozen BaoStock plan in independent process shards."""
from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import socket
import time
from pathlib import Path

import baostock as bs


HERE = Path(__file__).resolve().parent
PLAN = HERE / "full_market_query_plan.json"
RESPONSES = HERE / "full_responses"
MANIFEST = HERE / "FULL_MANIFEST.json"
WORKERS = 1


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def worker(shard_id: int, items: list[list[object]]) -> dict:
    shard_manifest_path = HERE / f"FULL_MANIFEST_SHARD_{shard_id}.json"
    shard_errors_path = HERE / f"FULL_ERRORS_SHARD_{shard_id}.json"
    shard = json.loads(shard_manifest_path.read_text(encoding="utf-8")) if shard_manifest_path.exists() else {}
    errors = json.loads(shard_errors_path.read_text(encoding="utf-8")) if shard_errors_path.exists() else []
    socket.setdefaulttimeout(30)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"shard {shard_id}: {login.error_msg}")
    try:
        for number, (symbol, year) in enumerate(items, 1):
            name = f"{symbol}_{year}.json"
            path = RESPONSES / name
            if name in shard:
                if digest(path) != shard[name]["sha256"]:
                    raise RuntimeError(f"shard {shard_id} hash mismatch: {name}")
                continue
            request = {"code": symbol[-2:].lower() + "." + symbol[:6],
                       "year": str(year), "yearType": "operate"}
            for attempt in range(3):
                try:
                    result = bs.query_dividend_data(**request)
                    if result.error_code != "0":
                        raise RuntimeError(result.error_msg)
                    rows = []
                    while result.next():
                        rows.append(dict(zip(result.fields, result.get_row_data())))
                    if any(row.get("dividOperateDate") and row["dividOperateDate"] > "2024-12-31" for row in rows):
                        raise RuntimeError(f"post-cutoff response: {name}")
                    save(path, {"key": f"{symbol}/{year}", "request": request,
                                "fields": result.fields, "records": rows, "row_count": len(rows),
                                "successful_empty": not rows, "cutoff": "2024-12-31"})
                    shard[name] = {"key": f"{symbol}/{year}", "sha256": digest(path), "rows": len(rows)}
                    save(shard_manifest_path, shard)
                    break
                except Exception as exc:
                    errors.append({"symbol": symbol, "year": year, "attempt": attempt + 1,
                                   "error": repr(exc)})
                    save(shard_errors_path, errors)
                    if attempt == 2:
                        raise
                    time.sleep(1)
            if number % 250 == 0:
                print(json.dumps({"shard": shard_id, "complete": number, "total": len(items)}), flush=True)
            time.sleep(0.01)
    finally:
        bs.logout()
    return {"shard": shard_id, "complete": len(shard)}


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    # Recover every independently committed shard after an interrupted pool.
    for path in sorted(HERE.glob("FULL_MANIFEST_SHARD_*.json")):
        old.update(json.loads(path.read_text(encoding="utf-8")))
    for name, item in old.items():
        if digest(RESPONSES / name) != item["sha256"]:
            raise RuntimeError(f"existing response hash mismatch: {name}")
    save(MANIFEST, dict(sorted(old.items())))
    remaining = [item for item in plan if f"{item[0]}_{item[1]}.json" not in old]
    shards = [remaining[index::WORKERS] for index in range(WORKERS)]
    print(json.dumps({"plan": len(plan), "checkpointed": len(old), "remaining": len(remaining),
                      "workers": WORKERS, "shard_sizes": list(map(len, shards))}), flush=True)
    context = mp.get_context("spawn")
    with context.Pool(WORKERS) as pool:
        completed = pool.starmap(worker, [(index, shard) for index, shard in enumerate(shards)])

    merged = dict(old)
    for index in range(WORKERS):
        path = HERE / f"FULL_MANIFEST_SHARD_{index}.json"
        merged.update(json.loads(path.read_text(encoding="utf-8")))
    expected = {f"{symbol}_{year}.json" for symbol, year in plan}
    if set(merged) != expected:
        raise RuntimeError(f"merged manifest incomplete: {len(merged)}/{len(expected)}")
    for name, item in merged.items():
        if digest(RESPONSES / name) != item["sha256"]:
            raise RuntimeError(f"merged response hash mismatch: {name}")
    save(MANIFEST, dict(sorted(merged.items())))
    print(json.dumps({"requested": len(plan), "complete": len(merged),
                      "keys_with_rows": sum(v["rows"] > 0 for v in merged.values()),
                      "shards": completed}), flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
