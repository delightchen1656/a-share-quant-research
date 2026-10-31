from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    selection = json.loads((BASE / "CURRENT_SELECTION.json").read_text(encoding="utf-8"))
    paths = {
        "runtime_strategy_py": BASE / "runtime" / "strategy.py",
        "frozen_builder_source": BASE / "runtime" / "frozen_builder.py",
        "risk_runner_py": BASE / "backtest" / "compute_risk_metrics.py",
        "performance_summary_csv": BASE / "results" / "PERFORMANCE_SUMMARY.csv",
        "risk_summary_json": BASE / "results" / "RISK_SUMMARY.json",
        "risk_metrics_csv": BASE / "results" / "RISK_METRICS_2020Q1_STARTS_TO_20261019.csv",
        "equity_curves_parquet": BASE / "results" / "EQUITY_CURVES_2020Q1_STARTS_TO_20261019.parquet",
        "equivalence_json": BASE / "runtime" / "EQUIVALENCE.json",
    }
    expected = selection["hashes_sha256"]
    checks = {name: path.is_file() and sha256(path) == expected[name] for name, path in paths.items()}
    if not all(checks.values()):
        raise RuntimeError(
            {
                name: {
                    "expected": expected.get(name),
                    "actual": sha256(paths[name]) if paths[name].is_file() else None,
                }
                for name, passed in checks.items()
                if not passed
            }
        )
    equivalence = json.loads(paths["equivalence_json"].read_text(encoding="utf-8"))
    if (
        equivalence.get("new_builder_sha256") != expected["frozen_builder_source"]
        or equivalence.get("comparison", {}).get("status") != "identical"
        or equivalence.get("strategy_logic_changed") is not False
        or equivalence.get("archive_runtime_dependency_removed") is not True
    ):
        raise RuntimeError("frozen builder equivalence boundary changed")
    if (
        selection.get("strategy_name") != "沪深2"
        or selection.get("live_trading_authorized") is not False
        or selection.get("supermind_entry") is not None
        or selection.get("maintenance", {}).get("active_runtime_self_contained") is not True
    ):
        raise RuntimeError("strategy registration or authorization boundary changed")
    print(
        json.dumps(
            {
                "status": "ok",
                "strategy": selection["strategy_name"],
                "checks": checks,
                "archive_dependency": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
