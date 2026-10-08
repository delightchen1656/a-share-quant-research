import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CURRENT_REQUIRED = [
    ROOT / "README.md",
    ROOT / "strategies/README.md",
    ROOT / "strategies/kechuang/README.md",
    ROOT / "strategies/kechuang/supermind_kechuang_1.py",
    ROOT / "strategies/kechuang/backtest/run.py",
    ROOT / "strategies/kechuang/backtest/engine.py",
    ROOT / "strategies/kechuang/backtest/data/corporate_actions.json",
    ROOT / "strategies/kechuang/backtest/data/snapshot_20260930/manifest.json",
    ROOT / "strategies/kechuang/research/provenance.json",
    ROOT / "strategies/kechuang/research/reference_metrics.json",
    ROOT / "strategies/kechuang/results/latest/verification.json",
    ROOT / "strategies/hushen/README.md",
    ROOT / "strategies/hushen/supermind_hushen_1.py",
    ROOT / "strategies/hushen/backtest/run.py",
    ROOT / "strategies/hushen/backtest/engine.py",
    ROOT / "strategies/hushen/backtest/data/benchmark.parquet",
    ROOT / "strategies/hushen/backtest/data/actions_merged.json",
    ROOT / "strategies/hushen/research/migration.json",
    ROOT / "strategies/hushen/results/latest/migration_validation.json",
    ROOT / "strategies/hushen/results/platform_20261009/fee_patch_validation.json",
    ROOT / "archive/kechuang/20261009_manifest_before.json",
    ROOT / "archive/kechuang/20261009_manifest_after_cache_cleanup.json",
    ROOT / "archive/kechuang/20261009_cache_cleanup.json",
    ROOT / "archive/hushen/INDEX.md",
    ROOT / "research_versions/README.md",
    ROOT / "evening_accumulation/data/metadata/refresh_20261004.json",
    ROOT / "sh_sz_market_research/data_pipeline/data/metadata/refresh_20261004.json",
    ROOT / "data_updates/20261004/audit.json",
]

EXPECTED_HASHES = {
    "strategies/kechuang/supermind_kechuang_1.py":
        "5ac181275a885c574f3e16f527bf07b5976a73ca001bbfb9d63d7f44f95071f9",
    "strategies/hushen/supermind_hushen_1.py":
        "a573941eb69f850536288ba5ce4333d943c2eb4862e7f3a518e46dd55cc653fd",
    "strategies/kechuang/research/training_source/model_artifacts/event_model.joblib":
        "1f87270f6a8506df79f06b38cacfee6c163dfc20f9eb8ae424c2397d816b0fd4",
    "strategies/kechuang/research/training_source/model_artifacts/stop_risk_model.joblib":
        "0cf8fbc48dd6eda524a54ddd14082f44a0b787498983d501160a2fe8f51709d9",
    "strategies/hushen/backtest/data/benchmark.parquet":
        "36674be3b57ca5dd84bc30b4a3f9b4f25af812e36ca7f2a68f24a38c81cc12df",
    "strategies/hushen/backtest/data/actions_merged.json":
        "ef8cff49ed6f2fb86c6a4f06fc304bc0afc0932979921b6068a32c6f59700d8d",
}

CURRENT_RESEARCH_DIRECTIONS = [
    "kechuang_event_risk",
    "kechuang_high_attack",
    "kechuang_industry_temperature",
    "stock_603106",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_manifest(root: Path, rows, full_hash: bool, errors: list[str]) -> None:
    for row in rows:
        path = root / row["path"]
        if not path.is_file():
            errors.append(f"missing manifest file: {path.relative_to(ROOT)}")
        elif full_hash and sha256(path) != row["sha256"].lower():
            errors.append(f"manifest hash mismatch: {path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the two locked baselines and protected research assets.")
    parser.add_argument(
        "--full-archive",
        action="store_true",
        help="rehash every file in the cleaned 2026-10-09 Kechuang archive",
    )
    args = parser.parse_args()
    errors: list[str] = []

    for path in CURRENT_REQUIRED:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")

    for relative, expected in EXPECTED_HASHES.items():
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing hash-locked file: {relative}")
        elif sha256(path) != expected:
            errors.append(f"hash mismatch: {relative}")

    snapshot_root = ROOT / "strategies/kechuang/backtest/data/snapshot_20260930"
    snapshot_manifest = load_json(snapshot_root / "manifest.json")
    if len(snapshot_manifest) != 1240:
        errors.append(f"Kechuang snapshot expected 1240 files, found {len(snapshot_manifest)}")
    snapshot_rows = [{"path": path, "sha256": item["sha256"]} for path, item in snapshot_manifest.items()]
    verify_manifest(snapshot_root, snapshot_rows, True, errors)

    kechuang_validation = load_json(ROOT / "strategies/kechuang/results/latest/verification.json")
    expected_validation = {
        "runs": 14,
        "reference_parity": True,
        "models_retrained": False,
        "platform_unchanged": True,
        "platform_tested": False,
    }
    if kechuang_validation != expected_validation:
        errors.append("Kechuang migration verification no longer matches the frozen result")

    migration = load_json(ROOT / "strategies/hushen/research/migration.json")
    if migration.get("entry_sha256") != EXPECTED_HASHES["strategies/hushen/supermind_hushen_1.py"]:
        errors.append("Hushen migration metadata does not match the current entry")

    for name in CURRENT_RESEARCH_DIRECTIONS:
        directory = ROOT / "research_versions" / name
        if not directory.is_dir():
            errors.append(f"missing research direction: research_versions/{name}")
            continue
        if len(list(directory.glob("*.md"))) != 1:
            errors.append(f"research_versions/{name}: expected exactly one Markdown index")
        if not list(directory.glob("*.py")):
            errors.append(f"research_versions/{name}: no retained source files")

    before_manifest = load_json(ROOT / "archive/kechuang/20261009_manifest_before.json")
    after_manifest = load_json(ROOT / "archive/kechuang/20261009_manifest_after_cache_cleanup.json")
    if len(before_manifest) != 6288:
        errors.append(f"pre-cleanup Kechuang manifest expected 6288 files, found {len(before_manifest)}")
    if len(after_manifest) != 6280:
        errors.append(f"cleaned Kechuang manifest expected 6280 files, found {len(after_manifest)}")
    archive_root = ROOT / "archive/kechuang/20261009_before_unification"
    actual_archive_files = sum(1 for path in archive_root.rglob("*") if path.is_file())
    if actual_archive_files != len(after_manifest):
        errors.append(
            f"cleaned Kechuang archive count mismatch: manifest={len(after_manifest)}, actual={actual_archive_files}"
        )
    verify_manifest(archive_root, after_manifest, args.full_archive, errors)

    cache_files = [
        path
        for path in ROOT.rglob("*.pyc")
        if "quant_env" not in path.parts and ".git" not in path.parts
    ]
    if cache_files:
        errors.append(f"found {len(cache_files)} Python bytecode files outside quant_env")

    if errors:
        raise SystemExit("Repository verification failed:\n- " + "\n- ".join(errors[:50]))

    scope = "entries, current data, models, results, indexes, cache state"
    if args.full_archive:
        scope += ", and all 6280 cleaned Kechuang archive files"
    print(f"Quant repository ready: verified {scope}.")


if __name__ == "__main__":
    main()
