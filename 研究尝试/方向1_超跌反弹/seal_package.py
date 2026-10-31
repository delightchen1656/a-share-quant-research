"""Rebuild the package integrity inventory after an authorized change."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent

def main():
    files = []
    for path in sorted(HERE.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(HERE)
        if path.name == 'PACKAGE_MANIFEST.json' or 'generated' in rel.parts or '__pycache__' in rel.parts:
            continue
        files.append({'path': rel.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (HERE / 'PACKAGE_MANIFEST.json').write_text(json.dumps({'files': files}, ensure_ascii=False, indent=2), encoding='utf8')
    print('Sealed', len(files), 'files')

if __name__ == '__main__':
    main()
