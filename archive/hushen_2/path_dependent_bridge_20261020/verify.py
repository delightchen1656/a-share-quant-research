from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[1]


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
        "risk_runner_py": BASE / "backtest" / "compute_risk_metrics.py",
        "performance_summary_csv": BASE / "results" / "PERFORMANCE_SUMMARY.csv",
        "risk_summary_json": BASE / "results" / "RISK_SUMMARY.json",
        "frozen_builder_source": ROOT / "archive" / "hushen_2" / "pre_registration_research_20261020" / "results" / "batch_009_pre2025_cagr_excess" / "run_batch_009_pre2025_cagr_excess.py",
        "execution_engine_source": ROOT / "archive" / "hushen_2" / "pre_registration_research_20261020" / "research" / "run_batch.py",
        "post2024_audit_source": ROOT / "archive" / "hushen_2" / "pre_registration_research_20261020" / "results" / "holdout_restricted" / "seven_versions_four_extra_rows" / "posterior_old_new" / "run_audit.py",
    }
    actual = {name: sha256(path) for name, path in paths.items()}
    expected = selection["hashes_sha256"]
    checks = {name: actual[name] == expected[name] for name in paths}
    if not all(checks.values()):
        raise RuntimeError({name: {"expected": expected[name], "actual": actual[name]} for name in checks if not checks[name]})
    print(json.dumps({"status": "ok", "strategy": selection["strategy_name"], "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
