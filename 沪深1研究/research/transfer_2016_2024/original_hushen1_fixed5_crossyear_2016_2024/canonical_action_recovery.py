from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "run_once.py"
PROTOCOL = HERE / "CANONICAL_ACTION_RECOVERY_PROTOCOL_BEFORE_RUN.md"
AUDIT = HERE / "ACTION_CANONICAL_DEDUP_AUDIT_BEFORE_RECOVERY.json"
VALIDATION = HERE / "CANONICAL_ACTION_LOADER_VALIDATION.json"
LOCK = HERE / "FROZEN_BEFORE_CANONICAL_ACTION_RECOVERY.json"
STARTED = HERE / "RUN_STARTED_CANONICAL_ACTION_RECOVERY.json"
FAILED = HERE / "RUN_FAILED_CANONICAL_ACTION_RECOVERY.json"
COMPLETE = HERE / "RUN_COMPLETE_CANONICAL_ACTION_RECOVERY.json"


def load_base():
    spec = importlib.util.spec_from_file_location("frozen_hushen1_run_once", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen base module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


def canonical_load_actions(symbol_to_col: dict[str, int]):
    """Frozen loader with one strict rule: skip only a fully identical event duplicate."""
    path = base.INPUT / "actions_pre2025_repaired_20261024.json"
    expected = next(
        x["sha256"]
        for x in json.loads(base.EXTENSION_PATH.read_text(encoding="utf-8"))["approved_extensions"]
        if Path(x["path"]).name == path.name
    )
    if base.sha256(path) != expected:
        raise RuntimeError("repaired action snapshot hash mismatch")
    source = json.loads(path.read_text(encoding="utf-8"))
    decision = json.loads(AUDIT.read_text(encoding="utf-8"))
    if decision["action_snapshot_sha256"] != expected:
        raise RuntimeError("canonical action audit is not bound to the approved snapshot")
    result = {}
    canonical_records: dict[tuple[int, pd.Timestamp], dict[str, Any]] = {}
    canonical_sources: dict[tuple[int, pd.Timestamp], str] = {}
    duplicate_rows = []
    missing_pay = 0
    missing_release = 0
    skipped_after_cutoff = 0
    for source_key in sorted(source):
        symbol = source_key.split("/", 1)[0]
        if symbol not in symbol_to_col:
            continue
        for source_index, record in enumerate(source[source_key]):
            operate_raw = str(record.get("dividOperateDate", "")).strip()
            if not operate_raw:
                continue
            operate = pd.Timestamp(operate_raw).normalize()
            if operate > base.CUTOFF:
                skipped_after_cutoff += 1
                continue
            event_key = (symbol_to_col[symbol], operate)
            if event_key in canonical_records:
                if record != canonical_records[event_key]:
                    raise RuntimeError(f"nonidentical duplicate repaired action {symbol}/{operate.date()}")
                duplicate_rows.append(
                    {
                        "symbol": symbol,
                        "operate_date": str(operate.date()),
                        "kept_source_key": canonical_sources[event_key],
                        "skipped_source_key": source_key,
                        "skipped_source_index": source_index,
                    }
                )
                continue
            pay_raw = str(record.get("dividPayDate", "")).strip()
            release_raw = str(record.get("dividStockMarketDate", "")).strip()
            pay_fallback = not pay_raw
            release_fallback = not release_raw
            pay = pd.Timestamp(pay_raw).normalize() if pay_raw else operate
            release = pd.Timestamp(release_raw).normalize() if release_raw else operate
            if pay > base.CUTOFF or release > base.CUTOFF:
                raise RuntimeError(f"post-boundary action settlement metadata {symbol}/{operate.date()}")
            missing_pay += int(pay_fallback)
            missing_release += int(release_fallback)
            result[event_key] = base.Action(
                cash=base._num(record.get("dividCashPsBeforeTax", "")),
                stock=base._num(record.get("dividStocksPs", ""))
                + base._num(record.get("dividReserveToStockPs", "")),
                taxable_stock=base._num(record.get("dividStocksPs", "")),
                pay=pay,
                release=release,
                pay_fallback=pay_fallback,
                release_fallback=release_fallback,
            )
            canonical_records[event_key] = record
            canonical_sources[event_key] = source_key
    expected_duplicate = [
        {
            "symbol": "600660.SH",
            "operate_date": "2017-05-15",
            "kept_source_key": "600660.SH/2017",
            "skipped_source_key": "600660.SH/2023",
            "skipped_source_index": 0,
        }
    ]
    if duplicate_rows != expected_duplicate:
        raise RuntimeError(f"canonical duplicate set changed: {duplicate_rows}")
    return result, {
        "events": len(result),
        "missing_pay_date_fallbacks": missing_pay,
        "missing_stock_market_date_fallbacks": missing_release,
        "post_cutoff_events_skipped": skipped_after_cutoff,
        "exact_duplicate_rows_skipped": len(duplicate_rows),
        "canonical_duplicate_rows": duplicate_rows,
        "canonical_policy": "skip full-record exact duplicates; raise on any field difference; never sum duplicates",
    }


def validate_loader() -> None:
    if (HERE / "MAIN_PATH_COMPLETE.json").exists():
        raise RuntimeError("performance output already exists")
    _manifest, records = base.manifest_records()
    symbols = [record["symbol"] for record in records]
    _actions, action_audit = canonical_load_actions({symbol: i for i, symbol in enumerate(symbols)})
    result = {
        "status": "passed_before_performance",
        "action_audit": action_audit,
        "strategy_formula_or_parameter_changed": False,
        "performance_computed": False,
    }
    base.atomic_json(VALIDATION, result)
    print("CANONICAL_ACTION_LOADER_VALIDATION_COMPLETE", flush=True)


def write_lock() -> None:
    base.verify_evaluation_freeze()
    if not VALIDATION.exists():
        raise RuntimeError("canonical loader validation missing")
    if (HERE / "MAIN_PATH_COMPLETE.json").exists():
        raise RuntimeError("performance output already exists")
    old_failure = json.loads((HERE / "RUN_FAILED.json").read_text(encoding="utf-8"))
    if old_failure.get("error") != "duplicate repaired action 600660.SH/2017-05-15":
        raise RuntimeError("unexpected first-attempt failure evidence")
    if LOCK.exists() or STARTED.exists():
        raise RuntimeError("canonical recovery lock/start already exists")
    locked_paths = [
        BASE_PATH,
        HERE / "FROZEN_BEFORE_EVALUATION.json",
        HERE / "RUN_STARTED.json",
        HERE / "RUN_FAILED.json",
        PROTOCOL,
        AUDIT,
        VALIDATION,
        Path(__file__).resolve(),
        base.INPUT / "actions_pre2025_repaired_20261024.json",
    ]
    base.atomic_json(
        LOCK,
        {
            "status": "frozen_before_any_performance_calculation_canonical_action_recovery",
            "locked_files": {str(path.resolve()): base.sha256(path) for path in locked_paths},
            "original_evaluation_freeze_verified": True,
            "first_attempt_failed_before_account_simulation": True,
            "formula_or_parameter_changed": False,
            "performance_computed": False,
        },
    )
    print("CANONICAL_ACTION_RECOVERY_FREEZE_COMPLETE", flush=True)


def verify_recovery_lock() -> dict[str, Any]:
    base.verify_evaluation_freeze()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for raw_path, expected in lock["locked_files"].items():
        path = Path(raw_path)
        if base.sha256(path) != expected:
            raise RuntimeError(f"canonical-recovery locked file changed: {path.name}")
    return lock


def execute() -> None:
    lock = verify_recovery_lock()
    if STARTED.exists() or COMPLETE.exists():
        raise RuntimeError("canonical action recovery already started; do not rerun")
    if (HERE / "MAIN_PATH_COMPLETE.json").exists():
        raise RuntimeError("unexpected performance output before recovery")
    base.atomic_json(
        STARTED,
        {
            "status": "started",
            "recovery_lock_sha256": base.sha256(LOCK),
            "original_freeze_sha256": base.sha256(HERE / "FROZEN_BEFORE_EVALUATION.json"),
            "first_attempt_performance_computed": False,
            "unique_real_performance_evaluation": True,
        },
    )
    base.load_actions = canonical_load_actions
    market = base.ExecutionMarket(base.load_config())
    base.atomic_json(
        HERE / "CANONICAL_ACTION_LOAD_RUNTIME_AUDIT.json",
        {"status": "passed", **market.action_audit},
    )
    main, periods, yearly, loo, stability = base.run_main(market)
    q1_metrics, q1_summary = base.run_q1_batches(market)
    fees = base.run_fee_stress(market, main)
    gate, integrity = base.write_final_reports(
        periods, yearly, loo, stability, q1_metrics, q1_summary, fees, main, market
    )
    summary = {
        "strategy": "original Hushen1 D11 fixed five",
        "initial_cash_cny": base.load_config()["initial_cash_cny"],
        "period_metrics": periods.to_dict("records"),
        "yearly_excess_floor": stability["yearly_excess_floor"],
        "yearly_excess_sample_std": stability["yearly_excess_sample_std"],
        "loo_excess_floor": stability["loo_excess_floor"],
        "q1_scenarios": len(q1_metrics),
        "transfer_gate": gate,
        "integrity": integrity,
        "formula_or_parameter_search": False,
        "canonical_action_recovery": True,
    }
    base.atomic_json(HERE / "SUMMARY.json", summary)
    completion = {
        "status": "complete",
        "unique_real_performance_evaluation": True,
        "recovery_lock_sha256": base.sha256(LOCK),
        "integrity_passed": integrity["passed"],
        "transfer_gate_passed": gate["passed"],
    }
    base.atomic_json(COMPLETE, completion)
    base.atomic_json(HERE / "RUN_COMPLETE.json", completion)
    base.output_manifest()
    print("CANONICAL_ACTION_RECOVERY_EVALUATION_COMPLETE", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate", action="store_true")
    group.add_argument("--write-lock", action="store_true")
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.validate:
        validate_loader()
    elif args.write_lock:
        write_lock()
    else:
        try:
            execute()
        except Exception as exc:
            base.atomic_json(
                FAILED,
                {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
            )
            raise


if __name__ == "__main__":
    main()
