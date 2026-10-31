"""Fetch only the frozen pre-2025 company-action gap plan from BaoStock."""
from __future__ import annotations

import hashlib
import json
import socket
import time
from pathlib import Path

import baostock as bs


HERE = Path(__file__).resolve().parent
PLAN = HERE / "query_plan.json"
RESPONSES = HERE / "responses"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    assert all(len(item) == 2 and 2013 <= int(item[1]) <= 2024 for item in plan)
    frozen = {"queries": plan, "query_plan_sha256": digest(PLAN), "cutoff": "2024-12-31"}
    save(HERE / "FROZEN_QUERY.json", frozen)
    manifest_path = HERE / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    errors = []
    socket.setdefaulttimeout(30)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    try:
        for symbol, year in plan:
            name = f"{symbol}_{year}.json"
            path = RESPONSES / name
            if name in manifest:
                assert digest(path) == manifest[name]["sha256"]
                continue
            request = {"code": symbol[-2:].lower() + "." + symbol[:6], "year": str(year), "yearType": "operate"}
            for attempt in range(3):
                try:
                    result = bs.query_dividend_data(**request)
                    if result.error_code != "0":
                        raise RuntimeError(result.error_msg)
                    rows = []
                    while result.next():
                        rows.append(dict(zip(result.fields, result.get_row_data())))
                    assert all(not row.get("dividOperateDate") or row["dividOperateDate"] <= "2024-12-31" for row in rows)
                    save(path, {"key": f"{symbol}/{year}", "request": request, "fields": result.fields,
                                "records": rows, "row_count": len(rows), "successful_empty": not rows,
                                "cutoff": "2024-12-31"})
                    manifest[name] = {"key": f"{symbol}/{year}", "sha256": digest(path), "rows": len(rows)}
                    save(manifest_path, manifest)
                    break
                except Exception as exc:
                    errors.append({"symbol": symbol, "year": year, "attempt": attempt + 1, "error": repr(exc)})
                    save(HERE / "ERRORS.json", errors)
                    if attempt == 2:
                        raise
                    time.sleep(1)
            time.sleep(0.05)
    finally:
        bs.logout()
    print(json.dumps({"requested": len(plan), "complete": len(manifest),
                      "keys_with_rows": sum(v["rows"] > 0 for v in manifest.values())}))


if __name__ == "__main__":
    main()
