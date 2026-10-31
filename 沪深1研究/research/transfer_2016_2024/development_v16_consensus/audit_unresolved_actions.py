"""One-way integrity check: did the frozen candidate hold an unresolved action event?"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNNER = HERE / "run_research.py"


def main() -> None:
    spec = importlib.util.spec_from_file_location("v16_locked_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    unresolved_frame = pd.read_csv(ROOT / "action_repair_20261024" / "repaired_action_coverage.csv")
    unresolved = {(row.symbol, pd.Timestamp(row.date)) for row in unresolved_frame.itertuples()}
    metadata = {(row.symbol, pd.Timestamp(row.date)): {
        "has_action": bool(row.has_action),
        "reference_error": None if pd.isna(row.reference_error) else float(row.reference_error),
    } for row in unresolved_frame.itertuples()}

    hits: Counter[tuple[str, pd.Timestamp]] = Counter()
    OriginalAccount = module.Account

    class AuditAccount(OriginalAccount):
        def corporate(self, date, i):
            for j in self.holdings:
                key = (self.m.symbols[j], date)
                if key in unresolved:
                    hits[key] += 1
            return super().corporate(date, i)

    module.Account = AuditAccount
    market = module.load_market(module.DEV_END)
    lock = json.loads((HERE / "FINAL_LOCK.json").read_text(encoding="utf-8"))
    params = dict(lock["parameters"])
    params.setdefault("family", "locked_consensus")
    params.setdefault("axis_value", 0.0)
    module.run_candidate(market, params, range(2016, 2025))
    records = [
        {"symbol": symbol, "date": str(date.date()), "accounts_exposed": count, **metadata[(symbol, date)]}
        for (symbol, date), count in sorted(hits.items())
    ]
    output = {
        "candidate_sha256": lock["frozen_candidate_sha256"],
        "unresolved_market_events": len(unresolved),
        "held_unresolved_unique_events": len(records),
        "held_unresolved_account_exposures": sum(hits.values()),
        "passed": not records,
        "events": records,
    }
    (HERE / "UNRESOLVED_ACTION_AUDIT.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
