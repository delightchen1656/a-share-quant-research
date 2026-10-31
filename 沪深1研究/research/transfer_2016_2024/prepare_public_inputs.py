"""Provision a sanitized, pre-2025-only input snapshot for isolated development."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json

import pandas as pd


ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
HERE = Path(__file__).resolve().parent
SOURCE = (ROOT / "沪深2研究/results/holdout_restricted/"
          "history_2015_extension/attempt_20261022_2119")
DEST = HERE / "inputs_pre2025"
CUTOFF = pd.Timestamp("2024-12-31")
COLUMNS = ["date", "code", "open", "high", "low", "close", "preclose", "volume",
           "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST", "symbol", "board"]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def one(path: Path) -> dict:
    x = pd.read_parquet(path)
    x["date"] = pd.to_datetime(x.date)
    x = x.loc[x.date <= CUTOFF, COLUMNS].copy()
    if x.empty:
        return {"symbol": path.stem, "rows": 0, "omitted_no_pre2025_rows": True}
    assert x.date.max() <= CUTOFF and x.adjustflag.astype(str).eq("3").all()
    out = DEST / "raw" / path.parent.name / path.name
    out.parent.mkdir(parents=True, exist_ok=True)
    x.to_parquet(out, index=False)
    return {"symbol": path.stem, "rows": len(x), "start": str(x.date.min().date()),
            "end": str(x.date.max().date()), "sha256": sha(out),
            "path": str(out.relative_to(HERE)).replace("\\", "/")}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(SOURCE / "UNIVERSE.csv", dtype=str, keep_default_na=False)
    out_date = pd.to_datetime(meta.outDate, errors="coerce")
    future = out_date > CUTOFF
    meta.loc[future, "outDate"] = ""
    meta["status"] = ((meta.outDate == "") | (pd.to_datetime(meta.outDate, errors="coerce") > CUTOFF)).astype(int).astype(str)
    meta.to_csv(DEST / "universe.csv", index=False, encoding="utf-8-sig")

    cal = pd.read_csv(SOURCE / "CALENDAR.csv")
    cal["calendar_date"] = pd.to_datetime(cal.calendar_date)
    cal = cal.loc[cal.calendar_date <= CUTOFF]
    cal.to_csv(DEST / "calendar.csv", index=False, encoding="utf-8-sig")

    index = pd.read_parquet(SOURCE / "SSE_PRICE_INDEX.parquet")
    index["date"] = pd.to_datetime(index.date)
    index.loc[index.date <= CUTOFF].to_parquet(DEST / "sse_price_index.parquet", index=False)

    actions_source = ROOT / "沪深1研究/backtest/data/actions_merged.json"
    actions = json.loads(actions_source.read_text(encoding="utf-8"))
    safe_actions = {}
    for key, rows in actions.items():
        year = int(key.rsplit("/", 1)[1])
        if year <= 2024:
            safe_actions[key] = [row for row in rows
                                 if not row.get("dividOperateDate") or
                                 pd.Timestamp(row["dividOperateDate"]) <= CUTOFF]
    (DEST / "actions_pre2025.json").write_text(
        json.dumps(safe_actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    paths = sorted((SOURCE / "staging/raw").glob("*/*.parquet"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(one, paths))
    records.sort(key=lambda row: row["symbol"])
    manifest = {
        "status": "sanitized_pre2025_only", "cutoff": str(CUTOFF.date()),
        "warmup_start": "2013-01-01", "research_period": ["2016-01-01", "2024-12-31"],
        "raw_adjustflag": "3", "symbols_total": len(records),
        "symbols_with_rows": sum(row["rows"] > 0 for row in records),
        "calendar_sha256": sha(DEST / "calendar.csv"),
        "universe_sha256": sha(DEST / "universe.csv"),
        "sse_index_sha256": sha(DEST / "sse_price_index.parquet"),
        "actions_sha256": sha(DEST / "actions_pre2025.json"),
        "files": records,
        "isolation_rule": "No row, metadata outcome, action, benchmark value or result after 2024-12-31 is included.",
    }
    (DEST / "PUBLIC_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("READY", len(records), manifest["symbols_with_rows"], flush=True)


if __name__ == "__main__":
    main()
