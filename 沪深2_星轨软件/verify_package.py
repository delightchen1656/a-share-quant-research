from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main() -> None:
    required = [
        HERE / "CURRENT_SELECTION.json",
        HERE / "runtime/strategy.py",
        HERE / "runtime/frozen_builder.py",
        HERE / "runtime/signal_policy.py",
        HERE / "model/manifest.json",
        HERE / "model/utility.txt",
        HERE / "model/pen025.txt",
        HERE / "tracker/app.py",
        HERE / "tracker/service.py",
        HERE / "tracker/store.py",
        HERE / "tracker/market.py",
        HERE / "tracker/data/ledger.sqlite3",
        ROOT / "sh_sz_market_research/data_pipeline/data",
        ROOT / "data_updates",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit({"missing": missing})
    subprocess.run([sys.executable, "-B", str(HERE / "runtime/verify.py")], check=True)
    selection = json.loads((HERE / "CURRENT_SELECTION.json").read_text(encoding="utf-8"))
    signal_filter = selection["selection"]["signal_filter"]
    if signal_filter != {
        "policy": "original_top3_atr_ge025_no_refill_v1",
        "minimum_atr": 0.025,
        "comparison": ">=",
        "applied_after": "original_daily_top3",
        "refill": False,
        "preserve_original_rank": True,
    }:
        raise SystemExit("current selection is not ATR025-only")
    print(json.dumps({"status": "ok", "package": "沪深2_星轨软件", "market_data": "shared-read-only", "ledger": "local"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
