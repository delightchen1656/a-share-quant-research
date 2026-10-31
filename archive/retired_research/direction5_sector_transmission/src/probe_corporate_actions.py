"""Bounded provider capability checks. Never create an empty 'complete' action table."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "sources/corporate_action_probe_v1"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def worker(kind, code):
    import baostock as bs
    socket.setdefaulttimeout(12)
    target = OUTPUT / f"{kind}_{code}.json"
    report = {"kind": kind, "code": code, "requested_event_year": 2020,
              "status": "started", "complete_ledger": False}
    save(target, report)
    login = bs.login()
    if login.error_code != "0":
        report.update(status="login_failed", error_code=login.error_code)
        save(target, report)
        return
    if kind == "dividend":
        response = bs.query_dividend_data(code=code, year="2020", yearType="operate")
    else:
        response = bs.query_adjust_factor(code=code, start_date="2020-01-01", end_date="2020-12-31")
    records = []
    while response.error_code == "0" and response.next():
        records.append(response.get_row_data())
    report.update(status="returned" if response.error_code == "0" else "query_failed",
                  error_code=response.error_code, fields=response.fields, rows=records)
    save(target, report)  # preserve the response even if provider logout hangs
    bs.logout()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    jobs = [("dividend", "sh.600000"), ("dividend", "sz.000001"), ("adjust_factor", "sh.600000"),
            ("dividend", "sz.000027"), ("dividend", "sz.000403"), ("dividend", "sz.000597")]
    outcomes = []
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for kind, code in jobs:
        target = OUTPUT / f"{kind}_{code}.json"
        if target.exists():
            report = json.loads(target.read_text(encoding="utf-8"))
            if report.get("status") != "started":
                outcomes.append(report)
                continue
        try:
            process = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", kind, "--code", code],
                                     cwd=ROOT, env=environment, capture_output=True, timeout=40)
            report = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            report["worker_exit_code"] = process.returncode
            if process.returncode and report.get("status") != "returned":
                report["status"] = "worker_failed"
                report["stderr"] = process.stderr.decode("utf-8", errors="replace")[-1800:]
        except subprocess.TimeoutExpired:
            report = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
            if report.get("status") == "returned":
                report["logout_timeout"] = True
            else:
                report.update(kind=kind, code=code, requested_event_year=2020, status="timed_out", complete_ledger=False)
        save(target, report)
        outcomes.append(report)
        save(OUTPUT / "probe_summary.json", {"queries": outcomes, "approved_for_economic_labels": False})
        print(json.dumps({"kind": kind, "code": code, "status": report.get("status"), "rows": len(report.get("rows", []))}), flush=True)
    required = ["dividRegistDate", "dividOperateDate", "dividPayDate", "dividStockMarketDate", "dividCashPsBeforeTax", "dividStocksPs", "dividReserveToStockPs"]
    summary = {"queries": [{"kind": r["kind"], "code": r["code"], "status": r.get("status"),
                            "rows": len(r.get("rows", [])), "fields": r.get("fields", [])} for r in outcomes],
               "dividend_fields_required": required,
               "coverage": "capability_samples_only_not_all_symbols_or_years",
               "additional_sampling_rule": "First three symbols alphabetically with a 2020 reference-price ratio above 1.2 in data-quality diagnostics; not a return or strategy-selection rule.",
               "approved_for_economic_labels": False,
               "adjustment_factors_are_not_a_substitute_for_payment_and_share_listing_dates": True,
               "coverage_and_event_reconciliation_required_before_any_economic_return_labels": True}
    save(ROOT / "audits/corporate_action_provider_capability.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["dividend", "adjust_factor"])
    parser.add_argument("--code")
    args = parser.parse_args()
    worker(args.worker, args.code) if args.worker else main()
