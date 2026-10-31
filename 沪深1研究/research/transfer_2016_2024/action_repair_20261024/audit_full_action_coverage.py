"""Audit preclose discontinuities against a specified pre-2025 action snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INPUT = ROOT / "inputs_pre2025"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions", type=Path, default=INPUT / "actions_pre2025.json")
    parser.add_argument("--absolute-tolerance", type=float, default=0.011)
    parser.add_argument("--output", type=Path, default=HERE / "absolute_missing_action_events.csv")
    args = parser.parse_args()

    raw = json.loads(args.actions.read_text(encoding="utf-8"))
    action_dates = {
        (key.split("/")[0], row.get("dividOperateDate", ""))
        for key, rows in raw.items() for row in rows if row.get("dividOperateDate")
    }
    manifest = json.loads((INPUT / "PUBLIC_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    total = 0
    matched = 0
    missing = []
    for entry in manifest["files"]:
        if "path" not in entry:
            continue
        symbol = entry["symbol"]
        frame = pd.read_parquet(ROOT / entry["path"], columns=["date", "close", "preclose"])
        frame["date"] = pd.to_datetime(frame.date)
        frame["prev_close"] = frame.close.shift(1)
        events = frame[(frame.prev_close - frame.preclose).abs() > args.absolute_tolerance]
        total += len(events)
        for row in events.itertuples():
            date = row.date.strftime("%Y-%m-%d")
            if (symbol, date) in action_dates:
                matched += 1
            else:
                missing.append({"symbol": symbol, "year": row.date.year, "date": date,
                                "prev_close": row.prev_close, "preclose": row.preclose})
    pd.DataFrame(missing).to_csv(args.output, index=False, encoding="utf-8-sig")
    print(json.dumps({"absolute_tolerance": args.absolute_tolerance, "events": total,
                      "matched_date": matched, "missing": len(missing),
                      "missing_symbol_years": len({(x['symbol'], x['year']) for x in missing})}))


if __name__ == "__main__":
    main()
