"""Checkpointed historical per-symbol/year action collection in independent SDK processes."""
from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import contextlib
import hashlib
import io
import json
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "datasets/corporate_actions_baostock_v1"
CLIENT = None


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def initialize():
    global CLIENT
    import baostock as bs
    CLIENT = bs
    socket.setdefaulttimeout(12)
    with contextlib.redirect_stdout(io.StringIO()):
        result = CLIENT.login()
    if result.error_code != "0":
        raise RuntimeError("Historical action provider login failed: " + result.error_code)
    atexit.register(logout)


def logout():
    if CLIENT is not None:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                CLIENT.logout()
        except Exception:
            pass


def fetch(job):
    symbol, year = job
    path = STORE / "raw" / symbol / f"{year}.json"
    started = time.perf_counter()
    report = {"symbol": symbol, "year": year, "year_type": "operate", "provider": "BaoStock",
              "status": "started", "complete_corporate_action_ledger": False}
    for attempt in range(2):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                response = CLIENT.query_dividend_data(code=symbol[-2:].lower() + "." + symbol[:6], year=str(year), yearType="operate")
                rows = []
                while response.error_code == "0" and response.next():
                    rows.append(response.get_row_data())
            if response.error_code != "0":
                raise RuntimeError("query_error_" + response.error_code + ": " + str(response.error_msg))
            fields = list(response.fields)
            for values in rows:
                event = dict(zip(fields, values))
                if event.get("code") != symbol[-2:].lower() + "." + symbol[:6]:
                    raise RuntimeError("Provider security code mismatch.")
                date = event.get("dividOperateDate", "")
                if not date or not f"{year}-01-01" <= date <= f"{year}-12-31" or date > "2024-12-31":
                    raise RuntimeError("Provider operate-year boundary mismatch.")
            report.update(status="returned_events" if rows else "returned_empty_not_independent_no_event_proof",
                          fields=fields, rows=rows, attempts=attempt + 1)
            break
        except Exception as exc:
            report.update(status="failed", error=str(exc), attempts=attempt + 1)
            if attempt == 0:
                logout()
                with contextlib.redirect_stdout(io.StringIO()):
                    result = CLIENT.login()
                if result.error_code != "0":
                    break
    report["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    save(path, report)
    # Keep request concurrency bounded; no account or address rotation.
    time.sleep(max(0, 0.15 - (time.perf_counter() - started)))
    return {"symbol": symbol, "year": year, "status": report["status"],
            "rows": len(report.get("rows", [])), "elapsed_seconds": report["elapsed_seconds"]}


def main(limit, workers):
    manifest_path = ROOT / "inputs_pre2025/kline_v1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = [(r["symbol"], year) for r in manifest["files"] for year in range(2018, 2025)]
    contract = {"symbols": len(manifest["files"]), "years": list(range(2018, 2025)), "yearType": "operate",
                "planned_queries": len(jobs), "kline_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "empty_responses_are_not_verified_no_event_statements": True}
    contract_path = STORE / "request.json"
    if contract_path.exists() and json.loads(contract_path.read_text(encoding="utf-8")) != contract:
        raise RuntimeError("Existing detailed collection uses a different universe.")
    save(contract_path, contract)
    cached, pending = [], []
    for symbol, year in jobs:
        path = STORE / "raw" / symbol / f"{year}.json"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status", "").startswith("returned_"):
                cached.append({"symbol": symbol, "year": year, "status": value["status"], "rows": len(value.get("rows", []))})
                continue
            archived = STORE / "failure_history" / f"{symbol}_{year}_{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}.json"
            if not archived.exists():
                save(archived, value)
        pending.append((symbol, year))
    selected = pending[:limit] if limit else pending
    print(json.dumps({"planned_queries": len(jobs), "cached_successful_queries": len(cached), "selected_queries": len(selected)}), flush=True)
    results, started = [], time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, initializer=initialize) as pool:
        iterator = iter(selected)
        running = {}
        for _ in range(min(workers * 2, len(selected))):
            job = next(iterator)
            running[pool.submit(fetch, job)] = job
        while running:
            done, _ = concurrent.futures.wait(running, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED)
            if not done:
                print(json.dumps({"completed_this_run": len(results), "elapsed_seconds": round(time.perf_counter() - started, 1)}), flush=True)
            for future in done:
                running.pop(future)
                results.append(future.result())
                job = next(iterator, None)
                if job is not None:
                    running[pool.submit(fetch, job)] = job
            if done and (len(results) % 100 == 0 or len(results) == len(selected)):
                save(STORE / "progress.json", {"cached": len(cached), "completed_this_run": len(results), "planned": len(jobs), "selected": len(selected)})
                print(json.dumps({"completed_this_run": len(results), "cached": len(cached), "planned": len(jobs),
                                  "elapsed_seconds": round(time.perf_counter() - started, 1),
                                  "failed_this_run": sum(r["status"] == "failed" for r in results)}), flush=True)
    all_results = cached + results
    completed = [r for r in all_results if r["status"].startswith("returned_")]
    report = {"planned_queries": len(jobs), "successful_queries": len(completed),
              "returned_event_rows": sum(r["rows"] for r in completed),
              "event_queries": sum(r["status"] == "returned_events" for r in completed),
              "empty_queries": sum(r["status"] == "returned_empty_not_independent_no_event_proof" for r in completed),
              "failed_this_run": [r for r in results if r["status"] == "failed"],
              "all_planned_queries_returned": len(completed) == len(jobs),
              "elapsed_this_run_seconds": round(time.perf_counter() - started, 2),
              "complete_corporate_action_ledger": False, "approved_for_economic_labels": False}
    save(STORE / "collection_summary.json", report)
    save(ROOT / "audits/corporate_action_detail_collection.json", report)
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    main(args.limit, args.workers)
