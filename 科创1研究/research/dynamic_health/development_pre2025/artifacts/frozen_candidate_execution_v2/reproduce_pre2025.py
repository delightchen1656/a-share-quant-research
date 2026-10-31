from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine import add_matured_event_outcomes, canonical_sha256, load_snapshot, metrics, score_candidates, simulate


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce the execution-v2 candidate only on the approved pre-2025 snapshot.")
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    config = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
    raw, qfq = load_snapshot(args.inputs.resolve())
    scored, meta = score_candidates(qfq, root)
    scored = add_matured_event_outcomes(scored, qfq, meta["event_horizon"], meta["event_target"])
    equity, trades, decisions = simulate(
        raw,
        scored,
        config["event_threshold"],
        config["scheme"],
        config["history_start"],
        "2024-12-31",
    )
    result = {
        "scope": "approved inputs_pre2025 only",
        "cutoff": "2024-12-31",
        "change_class": "execution_compliance_fix_not_strategy_upgrade",
        "candidate_config_sha256": canonical_sha256(config),
        "input_manifest_sha256": config["input_manifest_sha256"],
        "metrics": metrics(equity, trades),
        "execution_invariants": {
            "cash_nonnegative": bool((equity.cash >= -1e-8).all()),
            "star_buy_minimum_and_unit": bool(
                trades.empty
                or (
                    trades["initial_shares"].ge(200).all()
                    and trades["initial_shares"].map(lambda x: float(x).is_integer()).all()
                )
            ),
            "trade_share_counts_integer": bool(
                trades.empty
                or (
                    trades["initial_shares"].map(lambda x: float(x).is_integer()).all()
                    and trades["final_sale_shares"].map(lambda x: float(x).is_integer()).all()
                )
            ),
            "t_plus_one": bool(trades.empty or (trades.exit_date > trades.entry_date).all()),
        },
        "rows": {"equity": len(equity), "trades": len(trades), "decisions": len(decisions)},
    }
    if not all(result["execution_invariants"].values()):
        raise AssertionError(result["execution_invariants"])
    output = root / "preboundary_reproduction.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
