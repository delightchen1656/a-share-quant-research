"""One-shot maintenance inventory and preservation; never deletes files."""
from pathlib import Path
import hashlib
import importlib.metadata as md
import json
import os
import platform
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'project_memory/holdout_restricted/module_independence_20261031'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def walk(root):
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in ('.git', 'quant_env', '.venv', '.local')
                   and not (Path(folder) / d).lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT]
        for name in files:
            yield Path(folder) / name


def main():
    if (AUDIT / 'cache_deletion_result.json').exists():
        raise SystemExit('Maintenance already completed; preserve this audit and use a new audit directory for a new run.')
    AUDIT.mkdir(parents=True, exist_ok=True)
    packages = sorted({(d.metadata['Name'], d.version) for d in md.distributions()}, key=lambda x: x[0].lower())
    lock = ROOT / 'tools/environments/requirements.lock.txt'
    lock.write_text('# Installed Windows / Python 3.10 environment; not an offline wheel bundle.\n' +
                    ''.join(f'{name}=={version}\n' for name, version in packages), encoding='utf-8')
    write(ROOT / 'tools/environments/runtime.json', {'python': platform.python_version(),
        'platform': platform.platform(), 'base_prefix': sys.base_prefix,
        'package_count': len(packages), 'lock_sha256': sha(lock),
        'rebuild_verified_on_clean_machine': False})

    reports = ['156315a8-5f6c-49da-a7ac-3c2aeb247a5d', '680ae0e2-2a75-4d42-ae52-fb750444594c', '564fa130-ed1c-4b4a-9e7e-8d00f1fc4c20']
    logs = ['e1fbaead-038e-4447-b53b-a3019f4be8a6', 'db61beb8-f549-408a-a908-f55b03636824', 'f4eef0a2-ad7f-4ae8-b5e5-c1f8ede8db44']
    sources = ['49ab7006-7ea7-4701-afb4-7cda9085ccf4', '80e5c6cf-9b67-4344-9bf0-81aab65ce39b', 'e69a4b9a-10c8-4d0a-9cf6-9b56177d08a1', 'f2175655-7e4c-4b63-9e96-7ec60ef2986b']
    preserved = []
    for ids, destination in [(reports, AUDIT / 'input_reports'),
        (logs, ROOT / '沪深1研究/history/holdout_restricted/external_platform_logs'),
        (sources, ROOT / 'archive/holdout_restricted/external_source_attachments')]:
        for ident in ids:
            source = Path.home() / '.codex/attachments' / ident / '已粘贴的文本.txt'
            target = destination / (ident + '.txt')
            if not source.is_file():
                preserved.append({'source': str(source), 'status': 'missing_not_recreated'})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and sha(target) != sha(source):
                raise RuntimeError(f'Refuse overwrite different evidence: {target}')
            if not target.exists():
                shutil.copy2(source, target)
            assert sha(source) == sha(target)
            preserved.append({'source': str(source), 'copy': str(target.relative_to(ROOT)), 'sha256': sha(target), 'bytes': target.stat().st_size})
    write(AUDIT / 'preserved_external_evidence.json', preserved)

    links = []
    for folder, dirs, _ in os.walk(ROOT, followlinks=False):
        for d in list(dirs):
            p = Path(folder) / d
            if d in ('.git', 'quant_env', '.venv'):
                dirs.remove(d)
                continue
            if p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                dirs.remove(d)
                target = p.resolve()
                entry = {'link': str(p.relative_to(ROOT)), 'target': str(target), 'exists': target.exists()}
                pkg = target / '@oai/artifact-tool/package.json'
                if pkg.is_file():
                    data = json.loads(pkg.read_text(encoding='utf-8'))
                    entry['artifact_tool'] = {'name': data.get('name'), 'version': data.get('version'), 'package_json_sha256': sha(pkg)}
                links.append(entry)
    write(AUDIT / 'directory_links_retained.json', links)

    archived = ROOT / 'project_memory/holdout_restricted/layout_20261031/bytecode'
    candidates = []
    if archived.exists():
        for p in walk(archived):
            if p.name.endswith(('.pyc.disabled', '.pyo.disabled')):
                candidates.append({'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p),
                    'reason': 'Previously inventoried disabled Python bytecode; cannot be imported under this suffix; historical manifest retained.'})
    write(AUDIT / 'disabled_bytecode_candidates.json', candidates)
    print(json.dumps({'packages': len(packages), 'preserved': len(preserved), 'directory_links': len(links),
                      'disabled_bytecode_files': len(candidates), 'disabled_bytecode_bytes': sum(x['bytes'] for x in candidates)}))


if __name__ == '__main__':
    main()
