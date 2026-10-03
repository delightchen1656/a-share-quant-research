import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    ROOT / "strategies/kechuang/supermind_baseline_3_2_audited_daily.py",
    ROOT / "strategies/kechuang/baseline_3_2/runtime.py",
    ROOT / "strategies/kechuang/supermind_baseline_1_2_stop_filter.py",
    ROOT / "strategies/kechuang/supermind_baseline_2_2_rising_defense.py",
    ROOT / "strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry.py",
    ROOT / "strategies/hushen/supermind_mainboard_baseline_1.py",
    ROOT / "strategies/hushen/supermind_mainboard_baseline_1_cutoff_20241130.py",
    ROOT / "strategies/hushen/cutoff_20241130/README.md",
    ROOT / "strategies/hushen/supermind_test2_D11_fast_daily.py",
    ROOT / "strategies/hushen/supermind_test2_D11_fast_cutoff_20241130.py",
    ROOT / "strategies/hushen/test2_reference/D11_v4_original.py",
    ROOT / "strategies/hushen/test2_reference/README.md",
    ROOT / "strategies/hushen/test2_cutoff_20241130/README.md",
    ROOT / "strategies/kechuang/training_source/train_event_model.py",
    ROOT / "strategies/kechuang/training_source/train_stop_model_and_research.py",
    ROOT / "strategies/kechuang/training_source/research_strategy3.py",
    ROOT / "strategies/kechuang/training_source/industry_temperature/frozen_research_code.py",
    ROOT / "strategies/kechuang/training_source/industry_temperature/temperature_variants.py",
    ROOT / "strategies/kechuang/training_source/model_artifacts/event_model.joblib",
    ROOT / "strategies/kechuang/training_source/model_artifacts/stop_risk_model.joblib",
    ROOT / "strategies/kechuang/history/baseline_1_2.md",
    ROOT / "strategies/kechuang/history/baseline_2_2.md",
    ROOT / "strategies/kechuang/history/baseline_3_1.md",
    ROOT / "strategies/kechuang/history/baseline_3_2_candidate.md",
    ROOT / "strategies/hushen/HISTORY.md",
    ROOT / "research_versions/README.md",
    ROOT / "evening_accumulation/data/metadata/refresh_20261004.json",
    ROOT / "sh_sz_market_research/data_pipeline/data/metadata/refresh_20261004.json",
    ROOT / "data_updates/20261004/audit.json",
    ROOT / "tools/行情库更新说明_20261004.md",
]

missing = [str(path.relative_to(ROOT)) for path in REQUIRED if not path.is_file()]
if missing:
    raise SystemExit("Missing current strategy files: " + ", ".join(missing))

EXPECTED_MODEL_HASHES = {
    ROOT / "strategies/kechuang/training_source/model_artifacts/event_model.joblib":
        "1f87270f6a8506df79f06b38cacfee6c163dfc20f9eb8ae424c2397d816b0fd4",
    ROOT / "strategies/kechuang/training_source/model_artifacts/stop_risk_model.joblib":
        "0cf8fbc48dd6eda524a54ddd14082f44a0b787498983d501160a2fe8f51709d9",
}
bad_hashes = []
for path, expected in EXPECTED_MODEL_HASHES.items():
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        bad_hashes.append(str(path.relative_to(ROOT)))
if bad_hashes:
    raise SystemExit("Changed or damaged model artifacts: " + ", ".join(bad_hashes))

RESEARCH_DIRECTIONS = [
    "kechuang_event_risk",
    "kechuang_high_attack",
    "kechuang_industry_temperature",
    "hushen_r08_rounds",
    "hushen_return_first",
    "hushen_event_prediction",
    "hushen_frontier_low_drawdown",
    "hushen_sector_rotation",
    "hushen_rapid_rally",
    "hushen_legacy_platform",
    "hushen_migration_experiments",
    "hushen_legacy_baseline2",
    "stock_603106",
]
archive_errors = []
for name in RESEARCH_DIRECTIONS:
    directory = ROOT / "research_versions" / name
    markdown = list(directory.glob("*.md"))
    code = list(directory.glob("*.py"))
    if len(markdown) != 1:
        archive_errors.append(f"{name}: expected exactly one Markdown file")
    if not code:
        archive_errors.append(f"{name}: no retained code files")
    if any(path.name == "__pycache__" for path in directory.rglob("__pycache__")):
        archive_errors.append(f"{name}: contains Python cache")
    if any(path.suffix.lower() in {".pyc", ".log", ".tmp"} for path in directory.rglob("*")):
        archive_errors.append(f"{name}: contains a temporary file")
if archive_errors:
    raise SystemExit("Research archive errors: " + "; ".join(archive_errors))

print("Quant core ready: entries, protected data, training sources, histories, research versions and model hashes verified")
