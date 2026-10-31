"""Wait for the protected Hushen backfill, then run one normal catch-up update."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import daily_market_update as daily


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill-run", required=True)
    parser.add_argument("--catch-up-date", required=True)
    parser.add_argument("--poll-seconds", type=int, default=300)
    args = parser.parse_args()

    run_dir = Path(args.backfill_run).resolve()
    audit = run_dir / "audit.json"
    lock = run_dir / "RUNNING.lock"
    daily.log(f"waiting for full-history audit: {audit}")
    while True:
        if audit.exists():
            payload = json.loads(audit.read_text(encoding="utf-8"))
            if payload.get("status") != "ok":
                raise RuntimeError(f"backfill audit is not successful: {audit}")
            break
        if not lock.exists():
            raise RuntimeError(
                f"backfill stopped without a successful audit; catch-up not started: {run_dir}"
            )
        time.sleep(max(30, args.poll_seconds))

    catch_up_audit = ROOT / "K线数据/更新备份与审计" / args.catch_up_date.replace("-", "") / "audit.json"
    if catch_up_audit.exists():
        existing = json.loads(catch_up_audit.read_text(encoding="utf-8"))
        if existing.get("status") == "ok":
            daily.log(f"catch-up already successful: {catch_up_audit}")
            print(json.dumps(existing, ensure_ascii=False, indent=2), flush=True)
            return

    daily.log(f"full-history backfill succeeded; starting catch-up for {args.catch_up_date}")
    result = daily.update(args.catch_up_date, 1)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
