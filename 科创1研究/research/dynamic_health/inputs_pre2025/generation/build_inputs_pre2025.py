"""Build the time-isolated KSTAR research input snapshot through 2024-12-31.

This script performs only mechanical date truncation and metadata sanitisation.  It
does not read strategy results, choose securities from returns, or retrain models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


CUTOFF = pd.Timestamp("2024-12-31")
BOUNDARY_VERSION = "public-pre2025-v2"


def repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    raise RuntimeError("repository root containing AGENTS.md was not found")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parquet_date_stats(path: Path) -> tuple[int, str | None, str | None]:
    dates = pd.to_datetime(pd.read_parquet(path, columns=["date"])["date"], errors="raise")
    if dates.empty:
        return 0, None, None
    return len(dates), dates.min().date().isoformat(), dates.max().date().isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_read_only(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    shutil.copy2(source, target)
    os.chmod(target, stat.S_IREAD)


def cutoff_anchored_qfq(raw: pd.DataFrame) -> pd.DataFrame:
    """Rebuild QFQ using only raw rows visible by the cutoff.

    BaoStock raw ``preclose`` already reflects same-day distributions.  Chaining
    previous actual close / current preclose makes the series continuous across
    those events.  Normalising the final multiplier to one gives a cutoff-date
    (not present-date) forward-adjusted series.
    """
    frame = raw.copy().sort_values("date").reset_index(drop=True)
    factors = pd.Series(1.0, index=frame.index)
    for idx in range(1, len(frame)):
        previous_close = float(frame.loc[idx - 1, "close"])
        current_preclose = float(frame.loc[idx, "preclose"])
        factors.iloc[idx] = factors.iloc[idx - 1] * (
            previous_close / current_preclose if current_preclose > 0 else 1.0
        )
    factors /= factors.iloc[-1]
    for column in ("open", "high", "low", "close", "preclose"):
        frame[column] = frame[column].astype(float) * factors
    frame["adjustflag"] = "2"
    return frame


def build(output: Path, root: Path, overwrite: bool = False) -> None:
    if output.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing snapshot: {output}")
    output.mkdir(parents=True, exist_ok=True)

    market = root / "evening_accumulation" / "data"
    source_universe = market / "metadata" / "universe.csv"
    source_calendar = market / "metadata" / "trade_calendar_20261026.csv"
    training = root / "strategies" / "kechuang" / "research" / "training_source"
    platform = root / "strategies" / "kechuang" / "supermind_kechuang_1.py"

    universe = pd.read_csv(source_universe, dtype=str)
    ipo = pd.to_datetime(universe["ipoDate"], errors="coerce")
    universe = universe.loc[ipo.notna() & ipo.le(CUTOFF)].copy()
    out_date = pd.to_datetime(universe["outDate"], errors="coerce")
    future_out = out_date.gt(CUTOFF)
    universe.loc[future_out, "outDate"] = ""
    effective_out = pd.to_datetime(universe["outDate"], errors="coerce")
    universe["status"] = effective_out.notna().map({True: "0", False: "1"})
    # Current names can encode later ST/delisting events, so omit them entirely.
    universe = universe[["code", "ipoDate", "outDate", "type", "status", "board", "symbol"]]
    universe["metadata_asof_date"] = CUTOFF.date().isoformat()
    universe = universe.sort_values("symbol").reset_index(drop=True)
    metadata_dir = output / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    universe.to_csv(metadata_dir / "universe.csv", index=False, encoding="utf-8")

    calendar = pd.read_csv(source_calendar, dtype={"is_trading_day": "int64"})
    calendar_dates = pd.to_datetime(calendar["calendar_date"], errors="raise")
    calendar = calendar.loc[calendar_dates.le(CUTOFF)].copy()
    calendar.to_csv(metadata_dir / "trade_calendar.csv", index=False, encoding="utf-8")

    included_symbols: set[str] = set(universe["symbol"])
    market_audit: dict[str, dict[str, object]] = {}
    (output / "raw").mkdir(exist_ok=True)
    (output / "qfq").mkdir(exist_ok=True)
    for source in sorted((market / "raw").glob("*.parquet")):
        symbol = source.stem
        if symbol not in included_symbols:
            continue
        raw = pd.read_parquet(source)
        raw["date"] = pd.to_datetime(raw["date"], errors="raise")
        raw = raw.loc[raw["date"].le(CUTOFF)].sort_values("date").reset_index(drop=True)
        if raw.empty:
            raise AssertionError(f"eligible symbol has no boundary data: raw/{symbol}")
        frames = {"raw": raw, "qfq": cutoff_anchored_qfq(raw)}
        for kind, frame in frames.items():
            target = output / kind / source.name
            frame.to_parquet(target, index=False)
            rows, first_date, last_date = parquet_date_stats(target)
            if last_date is not None and pd.Timestamp(last_date) > CUTOFF:
                raise AssertionError(f"post-cutoff row survived in {target}")
            market_audit[f"{kind}/{source.name}"] = {
                "rows": rows,
                "min_date": first_date,
                "max_date": last_date,
            }

    raw_names = {p.name for p in (output / "raw").glob("*.parquet")}
    qfq_names = {p.name for p in (output / "qfq").glob("*.parquet")}
    expected_names = {f"{symbol}.parquet" for symbol in included_symbols}
    if raw_names != expected_names or qfq_names != expected_names:
        raise AssertionError("raw/qfq file sets do not exactly match the sanitized universe")

    artifacts = training / "model_artifacts"
    copy_read_only(artifacts / "event_model.joblib", output / "frozen_models" / "event_model.joblib")
    copy_read_only(artifacts / "stop_risk_model.joblib", output / "frozen_models" / "stop_risk_model.joblib")
    copy_read_only(artifacts / "provenance.json", output / "frozen_models" / "source_provenance.json")
    copy_read_only(training / "src" / "model.py", output / "rules" / "feature_model.py")

    platform_hash = sha256(platform)
    model_note = {
        "read_only_artifacts": ["event_model.joblib", "stop_risk_model.joblib"],
        "platform_strategy_sha256": platform_hash,
        "platform_strategy_copied": False,
        "feature_rule_source": "rules/feature_model.py",
        "preserved_training_source_hashes": {
            "train_event_model.py": sha256(training / "train_event_model.py"),
            "train_stop_model_and_research.py": sha256(training / "train_stop_model_and_research.py"),
        },
        "training_lineage_assessment": {
            "conclusion": "insufficient_for_cryptographic_proof",
            "event_model": (
                "The preserved training source applies a final fit cutoff of 2024-12-01, and the "
                "artifact hash matches its preserved provenance. The joblib itself has no trained-through "
                "field and there is no immutable build record binding exact input hashes to this artifact; "
                "therefore absence of post-2024 K-lines cannot be proved from the artifact alone."
            ),
            "stop_risk_model": (
                "The joblib and preserved provenance both declare training_end=2024-12-31, but no immutable "
                "build record binds exact input hashes to the artifact; treat this as declared lineage, not "
                "cryptographic proof."
            ),
            "research_constraint": "Use the artifacts read-only; do not retrain or infer stronger lineage claims.",
        },
    }
    write_json(output / "frozen_models" / "MODEL_LINEAGE.json", model_note)

    generator_copy = output / "generation" / "build_inputs_pre2025.py"
    generator_copy.parent.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__).resolve(), generator_copy)

    audit = {
        "boundary_version": BOUNDARY_VERSION,
        "cutoff": CUTOFF.date().isoformat(),
        "selection_method": "IPO-on-or-before-cutoff only; no return/result-based selection",
        "qfq_method": "rebuilt from cutoff-truncated raw preclose/previous-close chain and normalized to 1.0 at each symbol's last visible row",
        "source_market_root": str(market.relative_to(root)).replace("\\", "/"),
        "source_universe_sha256": sha256(source_universe),
        "source_calendar_sha256": sha256(source_calendar),
        "universe_rows": len(universe),
        "future_ipo_rows_removed": int((ipo > CUTOFF).sum()),
        "future_out_dates_blankened": int(future_out.sum()),
        "precutoff_delisted_rows": int((universe["status"] == "0").sum()),
        "raw_files": len(raw_names),
        "qfq_files": len(qfq_names),
        "raw_global_max_date": max(v["max_date"] for k, v in market_audit.items() if k.startswith("raw/")),
        "qfq_global_max_date": max(v["max_date"] for k, v in market_audit.items() if k.startswith("qfq/")),
        "calendar_max_date": str(pd.to_datetime(calendar["calendar_date"]).max().date()),
        "checks": {
            "all_market_dates_at_or_before_cutoff": True,
            "calendar_at_or_before_cutoff": True,
            "raw_qfq_universe_file_sets_equal": True,
            "future_outdate_not_exposed": True,
            "current_code_name_omitted": True,
        },
        "known_limitations": [
            "The current BaoStock universe is sanitized backward; completeness for securities absent from the current provider response cannot be independently proved.",
            "Cutoff-anchored QFQ infers distributions from BaoStock raw preclose discontinuities; it is not a substitute for a complete independently verified corporate-action table.",
            "Frozen-model lineage is documentary rather than cryptographically bound to exact training inputs; see frozen_models/MODEL_LINEAGE.json.",
        ],
    }
    write_json(output / "AUDIT.json", audit)
    (output / "README.md").write_text(
        "# 科创动态健康度隔离研发输入（截止 2024-12-31）\n\n"
        "仅允许隔离研发读取本目录。`raw/` 与 `qfq/` 已逐文件截断；`metadata/` 已移除未来上市股票、"
        "清空截止日之后的 outDate 并重建 status，且不保留可能泄露后来状态的当前证券名称。\n\n"
        "冻结模型只能只读使用，不得在隔离研发中重训。训练血缘不能形成未使用 2025 年后 K 线的密码学证明，"
        "详见 `frozen_models/MODEL_LINEAGE.json`。`AUDIT.json` 记录限制，`MANIFEST.json` 覆盖除其自身外的全部文件。\n",
        encoding="utf-8",
    )

    entries: dict[str, dict[str, object]] = {}
    for path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "MANIFEST.json"):
        rel = path.relative_to(output).as_posix()
        entry: dict[str, object] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if path.suffix == ".parquet" and path.parent.name in {"raw", "qfq"}:
            entry.update(market_audit[rel])
        entries[rel] = entry
    manifest = {
        "manifest_schema": 1,
        "boundary_version": BOUNDARY_VERSION,
        "cutoff": CUTOFF.date().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_scope": "every regular file in this snapshot except MANIFEST.json itself",
        "files": entries,
    }
    write_json(output / "MANIFEST.json", manifest)


def verify(output: Path) -> None:
    manifest_path = output / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = set(manifest["files"])
    actual = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file() and p.name != "MANIFEST.json"}
    if expected != actual:
        raise AssertionError(f"manifest file-set mismatch: missing={expected-actual}, extra={actual-expected}")
    for rel, metadata in manifest["files"].items():
        path = output / rel
        if sha256(path) != metadata["sha256"]:
            raise AssertionError(f"SHA-256 mismatch: {rel}")
        if rel.startswith(("raw/", "qfq/")) and rel.endswith(".parquet"):
            rows, first_date, last_date = parquet_date_stats(path)
            if (rows, first_date, last_date) != (metadata["rows"], metadata["min_date"], metadata["max_date"]):
                raise AssertionError(f"date audit mismatch: {rel}")
            if last_date is not None and pd.Timestamp(last_date) > CUTOFF:
                raise AssertionError(f"post-cutoff market row: {rel}")
    universe = pd.read_csv(output / "metadata" / "universe.csv", dtype=str)
    if pd.to_datetime(universe["ipoDate"], errors="raise").gt(CUTOFF).any():
        raise AssertionError("post-cutoff IPO leaked into universe")
    out_date = pd.to_datetime(universe["outDate"], errors="coerce")
    if out_date.gt(CUTOFF).any():
        raise AssertionError("post-cutoff outDate leaked into universe")
    calendar = pd.read_csv(output / "metadata" / "trade_calendar.csv")
    if pd.to_datetime(calendar["calendar_date"], errors="raise").gt(CUTOFF).any():
        raise AssertionError("post-cutoff calendar row")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help="overwrite files in the exact snapshot directory without deleting it")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = repo_root(Path(__file__).resolve().parent)
    output = args.output or root / "strategies" / "kechuang" / "research" / "dynamic_health" / "inputs_pre2025"
    output = output.resolve()
    if not args.verify_only:
        build(output, root, overwrite=args.overwrite)
    verify(output)
    print(json.dumps({"status": "ok", "output": str(output), "manifest_sha256": sha256(output / "MANIFEST.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
