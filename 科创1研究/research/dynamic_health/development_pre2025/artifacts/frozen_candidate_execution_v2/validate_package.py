from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    errors = []
    for relative, expected in manifest["files"].items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing: {relative}")
            continue
        actual = sha256(path)
        if actual != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            errors.append(f"mismatch: {relative}")
    for relative, expected in manifest["immutable_artifacts"].items():
        if sha256(root / relative) != expected["sha256"]:
            errors.append(f"immutable artifact mismatch: {relative}")
    tests = json.loads((root / "execution_rule_tests.json").read_text(encoding="utf-8"))
    reproduction = json.loads((root / "preboundary_reproduction.json").read_text(encoding="utf-8"))
    if tests.get("status") != "passed" or not all(tests.get("checks", {}).values()):
        errors.append("execution rule tests not passed")
    if not all(reproduction.get("execution_invariants", {}).values()):
        errors.append("preboundary execution invariants not passed")
    if errors:
        raise SystemExit("; ".join(errors))
    print(json.dumps({"status": "passed", "files_verified": len(manifest["files"])}, sort_keys=True))


if __name__ == "__main__":
    main()
