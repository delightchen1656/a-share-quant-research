"""Independent data preparation; no strategy imports and no model training."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CUTOFF = pd.Timestamp(CONFIG["research_cutoff"])
if CUTOFF > pd.Timestamp("2024-12-31"):
    raise RuntimeError("Research boundary cannot be widened by changing config alone.")
FIELDS = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
          "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST"]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def source_files(source: Path):
    return sorted(p for exchange in ("SH", "SZ") for p in (source / exchange).glob("*.parquet")
                  if re.fullmatch(r"(?:60\d{4}\.SH|68\d{4}\.SH|00\d{4}\.SZ|30\d{4}\.SZ)\.parquet", p.name))


def fingerprints(paths):
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}


def snapshot() -> None:
    source = (ROOT / CONFIG["kline_source"]).resolve()
    target = ROOT / CONFIG["snapshot"]
    if target.exists():
        raise RuntimeError("Snapshot already exists; use verify. Never silently overwrite.")
    stage = target.with_name(target.name + ".staging")
    stage.mkdir(parents=True, exist_ok=False)
    paths = source_files(source)
    if not paths:
        raise RuntimeError("No authorized stock K-line files found.")
    before = fingerprints(paths)
    records, issues, skipped = [], [], []
    for index, p in enumerate(paths, 1):
        table = pq.read_table(p, columns=FIELDS, filters=[("date", "<=", CUTOFF.to_pydatetime())])
        df = table.to_pandas()
        if df.empty:
            skipped.append(p.name)
            continue
        df["date"] = pd.to_datetime(df["date"], errors="raise")
        df = df.sort_values("date").reset_index(drop=True)
        symbol = p.name.removesuffix(".parquet")
        expected_code = symbol[-2:].lower() + "." + symbol[:6]
        fatal = []
        if df["date"].isna().any() or (df["date"] > CUTOFF).any():
            fatal.append("invalid_dates")
        if df["date"].duplicated().any():
            fatal.append("duplicate_dates")
        if not df["code"].eq(expected_code).all():
            fatal.append("code_mismatch")
        if set(df["adjustflag"].dropna().astype(str)) != {"3"}:
            fatal.append("unexpected_raw_adjustflag")
        active = df["tradestatus"].astype(str).eq("1")
        prices = df[["open", "high", "low", "close"]]
        invalid = active & (prices.isna().any(axis=1) | prices.le(0).any(axis=1)
                            | df["high"].lt(prices[["open", "low", "close"]].max(axis=1))
                            | df["low"].gt(prices[["open", "high", "close"]].min(axis=1)))
        if invalid.any():
            fatal.append("invalid_active_ohlc")
        if df[["volume", "amount"]].lt(0).any().any():
            fatal.append("negative_volume_or_amount")
        if fatal:
            issues.append({"symbol": symbol, "fatal": fatal})
            continue
        out = stage / p.name
        df.to_parquet(out, index=False)
        records.append({"symbol": symbol, "rows": len(df), "first_date": str(df["date"].min().date()),
                        "last_date": str(df["date"].max().date()), "source": str(p),
                        "source_sha256": sha256(p), "snapshot_file": p.name,
                        "snapshot_sha256": sha256(out),
                        "suspended_rows": int((~active).sum()),
                        "st_rows": int(df["isST"].astype(str).eq("1").sum()),
                        "null_counts": {c: int(v) for c, v in df.isna().sum().items() if v}})
        if index % 500 == 0:
            print(json.dumps({"progress_files": index}, ensure_ascii=False), flush=True)
    changed = before != fingerprints(source_files(source))
    report = {"cutoff": str(CUTOFF.date()), "source_file_count": len(paths),
              "snapshot_file_count": len(records), "rows": sum(r["rows"] for r in records),
              "date_min": min((r["first_date"] for r in records), default=None),
              "date_max": max((r["last_date"] for r in records), default=None),
              "fatal_issues": issues, "source_changed_during_copy": changed,
              "files_without_pre_cutoff_rows": skipped,
              "limitations": ["historical_universe_completeness_unverified", "volume_units_not_yet_documented",
                              "corporate_action_economic_returns_unverified", "industry_not_yet_whitelisted"],
              "ready_for_model_training": False}
    write_json(ROOT / "audits/kline_snapshot_audit.json", report)
    if issues or changed:
        write_json(stage / "FAILED.json", report)
        raise RuntimeError("Snapshot audit failed; staging retained, nothing promoted.")
    write_json(stage / "manifest.json", {"boundary_version": CONFIG["boundary_version"],
               "cutoff": str(CUTOFF.date()), "columns": FIELDS, "files": records,
               "scope": "only stock files actually present in authorized source; not proven complete market"})
    stage.rename(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def verify() -> None:
    target = ROOT / CONFIG["snapshot"]
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    expected = {r["snapshot_file"] for r in manifest["files"]}
    actual = {p.name for p in target.glob("*.parquet")}
    if expected != actual:
        raise RuntimeError("Snapshot file inventory differs from whitelist.")
    rows = 0
    for r in manifest["files"]:
        p = target / r["snapshot_file"]
        if sha256(p) != r["snapshot_sha256"]:
            raise RuntimeError(f"Hash mismatch: {p.name}")
        dates = pq.read_table(p, columns=["date"]).to_pandas()["date"]
        if len(dates) != r["rows"] or dates.isna().any() or dates.max() > CUTOFF:
            raise RuntimeError(f"Date/row verification failed: {p.name}")
        rows += len(dates)
    result = {"verified": True, "files": len(expected), "rows": rows, "cutoff": str(CUTOFF.date()),
              "model_experiments_enabled": False}
    write_json(ROOT / "audits/kline_snapshot_verification.json", result)
    print(json.dumps(result, ensure_ascii=False))


def probe_industry() -> None:
    import baostock as bs
    socket.setdefaulttimeout(20)
    store = (ROOT / CONFIG["industry_store"]).resolve()
    raw = store / "baostock_probe"
    raw.mkdir(parents=True, exist_ok=True)
    # Historical query parameters are NOT evidence of historical publication availability.
    dates = ["2018-01-02", "2020-12-31", "2022-12-30", "2024-12-31"]
    outcomes = []
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Industry provider login failed: {login.error_code}")
    try:
        for date in dates:
            rs = bs.query_stock_industry(date=date)
            data = []
            while rs.error_code == "0" and rs.next():
                data.append(rs.get_row_data())
            df = pd.DataFrame(data, columns=rs.fields)
            out = raw / f"requested_{date}.csv"
            if out.exists():
                raise RuntimeError(f"Probe already exists: {out.name}")
            df.to_csv(out, index=False, encoding="utf-8-sig")
            updates = pd.to_datetime(df.get("updateDate", pd.Series(dtype=str)), errors="coerce")
            outcome = {"requested_date": date, "error_code": rs.error_code, "rows": len(df),
                       "sha256": sha256(out), "update_date_min": str(updates.min().date()) if updates.notna().any() else None,
                       "update_date_max": str(updates.max().date()) if updates.notna().any() else None,
                       "future_update_rows": int(updates.gt(pd.Timestamp(date)).sum()),
                       "fields": list(df.columns), "approved_for_research": False}
            outcomes.append(outcome)
            write_json(raw / "probe_audit.json", {"provider": "BaoStock", "documentation":
                       "https://www.baostock.com/mainContent?file=stockIndustry.md", "queries": outcomes,
                       "warning": "Date parameters alone do not establish point-in-time membership or publication dates."})
            print(json.dumps(outcome, ensure_ascii=False), flush=True)
    finally:
        bs.logout()
    write_json(ROOT / "audits/industry_provider_probe.json", {"queries": outcomes, "approved_for_research": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["snapshot", "verify", "probe-industry"])
    args = parser.parse_args()
    {"snapshot": snapshot, "verify": verify, "probe-industry": probe_industry}[args.command]()
