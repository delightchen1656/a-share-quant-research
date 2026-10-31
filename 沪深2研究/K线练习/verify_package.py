from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads((HERE / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    checks = {}
    for group in ("runtime", "inputs"):
        for relative, expected in manifest[group].items():
            path = HERE / relative
            checks[relative] = path.is_file() and sha256(path) == expected
    identity = json.loads((HERE / "frozen_inputs/cases/INPUT_IDENTITY.json").read_text(encoding="utf-8"))
    checks["identity_signal_hash"] = identity["signals_sha256"] == manifest["inputs"]["frozen_inputs/cases/INPUT_SIGNALS.parquet"]
    checks["identity_market_hash"] = identity["data_manifest_sha256"] == manifest["inputs"]["frozen_inputs/market/DOWNLOAD_COMPLETE.json"]
    checks["shared_universe"] = (ROOT / "K线数据/沪深/metadata/historical_mainboard_universe.csv").is_file()
    if not all(checks.values()):
        raise SystemExit({name: passed for name, passed in checks.items() if not passed})
    print(json.dumps({"status": "ok", "package": manifest["package"], "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
