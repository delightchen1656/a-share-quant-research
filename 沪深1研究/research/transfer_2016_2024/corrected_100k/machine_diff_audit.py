from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "fixed_formula_monthly_preregistered_v1_20261024"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_differences(old: Any, new: Any, path: str = "$") -> list[dict[str, Any]]:
    if isinstance(old, dict) and isinstance(new, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(old) | set(new)):
            child = f"{path}.{key}"
            if key not in old:
                differences.append({"path": child, "old": "<missing>", "new": new[key]})
            elif key not in new:
                differences.append({"path": child, "old": old[key], "new": "<missing>"})
            else:
                differences.extend(json_differences(old[key], new[key], child))
        return differences
    if isinstance(old, list) and isinstance(new, list):
        differences = []
        for index in range(max(len(old), len(new))):
            child = f"{path}[{index}]"
            if index >= len(old):
                differences.append({"path": child, "old": "<missing>", "new": new[index]})
            elif index >= len(new):
                differences.append({"path": child, "old": old[index], "new": "<missing>"})
            else:
                differences.extend(json_differences(old[index], new[index], child))
        return differences
    return [] if old == new else [{"path": path, "old": old, "new": new}]


def main() -> None:
    old_code = OLD / "run_once.py"
    new_code = HERE / "run_once.py"
    old_config_path = OLD / "frozen_config.json"
    new_config_path = HERE / "frozen_config.json"
    old_protocol_path = OLD / "PROTOCOL_FROZEN.md"
    new_protocol_path = HERE / "PROTOCOL_FROZEN.md"

    old_config = json.loads(old_config_path.read_text(encoding="utf-8"))
    new_config = json.loads(new_config_path.read_text(encoding="utf-8"))
    config_diff = json_differences(old_config, new_config)
    expected_config_diff = [
        {"path": "$.initial_cash_cny", "old": 1000000.0, "new": 100000.0}
    ]

    old_protocol = old_protocol_path.read_text(encoding="utf-8")
    new_protocol = new_protocol_path.read_text(encoding="utf-8")
    expected_protocol = old_protocol.replace(
        "参考组合初始资金 1,000,000 元、20 个仓位，每个目标约 50,000 元，该门槛把单笔目标规模控制在中位日成交额约 0.25% 以内。",
        "参考组合初始资金 100,000 元、20 个仓位，每个目标约 5,000 元；该门槛沿用上一轮预登记的固定门槛，对应单笔目标规模约为中位日成交额的 0.025%，不得因资金纠正而重调。",
    ).replace(
        "参考组合初始现金 1,000,000 元，不计融资、融券与现金利息。",
        "参考组合初始现金 100,000 元，不计融资、融券与现金利息。",
    )

    code_equal = old_code.read_bytes() == new_code.read_bytes()
    config_only_initial_cash = config_diff == expected_config_diff
    protocol_only_expected_correction = new_protocol == expected_protocol
    old_evidence_intact = (
        (OLD / "RUN_COMPLETE.json").exists()
        and (OLD / "OUTPUT_MANIFEST_SHA256.json").exists()
        and (OLD / "FAILURE_CONCLUSION.md").exists()
    )
    passed = all(
        [code_equal, config_only_initial_cash, protocol_only_expected_correction, old_evidence_intact]
    )

    protocol_diff = "".join(
        difflib.unified_diff(
            old_protocol.splitlines(keepends=True),
            new_protocol.splitlines(keepends=True),
            fromfile="old/PROTOCOL_FROZEN.md",
            tofile="corrected_100k/PROTOCOL_FROZEN.md",
        )
    )
    (HERE / "PROTOCOL_DIFF_BEFORE_RUN.patch").write_text(protocol_diff, encoding="utf-8")
    audit = {
        "status": "passed" if passed else "failed",
        "audited_before_corrected_performance": True,
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "old_directory_preserved": str(OLD),
        "new_directory": str(HERE),
        "old_invalid_run_evidence_intact": old_evidence_intact,
        "code": {
            "byte_identical": code_equal,
            "old_sha256": sha256(old_code),
            "new_sha256": sha256(new_code),
        },
        "config": {
            "differences": config_diff,
            "only_strategy_input_difference_is_initial_cash": config_only_initial_cash,
            "old_sha256": sha256(old_config_path),
            "new_sha256": sha256(new_config_path),
        },
        "protocol": {
            "only_initial_cash_and_derived_text_changed": protocol_only_expected_correction,
            "old_sha256": sha256(old_protocol_path),
            "new_sha256": sha256(new_protocol_path),
            "unified_diff_file": "PROTOCOL_DIFF_BEFORE_RUN.patch",
        },
        "immutable_strategy_fields_confirmed_by_config_diff": sorted(
            key for key in new_config if key != "initial_cash_cny"
        ),
        "allowed_change": {
            "path": "$.initial_cash_cny",
            "old": 1000000.0,
            "new": 100000.0,
            "reason": "user-established Hushen research capital convention",
            "performance_tuning": False,
        },
    }
    (HERE / "MACHINE_DIFF_AUDIT_BEFORE_RUN.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
