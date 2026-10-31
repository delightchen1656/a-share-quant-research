"""Review a narrow set of known retired test fixtures; does not delete."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'project_memory/holdout_restricted/module_independence_20261031'
NAMES = ['hushen2_buy_workflow_qa_hcrzrhup', 'hushen2_buy_workflow_qa_kiukz7gf',
         'hushen2_manual_exit_ui_4m9mr6y1', 'hushen2_tracking_qa_rak3sa3n',
         'hushen2_upgrade_rehearsal_yrbbiw0q', 'quant-recover-3843ec79f3f842568cce1d961b84f363']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (AUDIT / 'cache_deletion_result.json').exists():
        raise SystemExit('Cleanup already completed; do not overwrite the original reviewed plan.')
    temp = Path(os.environ['TEMP']).resolve()
    files = json.loads((AUDIT / 'disabled_bytecode_candidates.json').read_text(encoding='utf-8'))
    directories, fixture_checks = [], []
    for name in NAMES:
        folder = temp / name
        if not folder.exists():
            continue
        assert folder.resolve().parent == temp
        assert not folder.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        children = list(folder.rglob('*'))
        assert all(not p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT for p in children)
        local_files = [p for p in children if p.is_file()]
        if name.startswith('hushen2_buy_workflow_qa_'):
            for p in local_files:
                assert p.suffix == '.sqlite3', f'Unknown fixture content: {p}'
                assert (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) > 86400
                connection = sqlite3.connect(p.as_uri() + '?mode=ro', uri=True)
                try:
                    rows = connection.execute('SELECT kind,payload FROM events').fetchall()
                    assert rows
                    accepted = [json.loads(payload) for kind, payload in rows if kind == 'accept']
                    assert {r['signal_id'] for r in accepted} == {'test-a', 'test-b'}
                    assert all(r['name'].startswith('隔离测试') for r in accepted)
                    assert all(kind in ('accept', 'buy_review', 'buy') for kind, _ in rows)
                    assert all(json.loads(payload).get('order_id') in ('test-a','test-b')
                               for kind, payload in rows if kind != 'accept')
                    fixture_checks.append({'path': str(p), 'events': len(rows), 'test_ids_only': True})
                finally:
                    connection.close()
                files.append({'path': str(p), 'sha256': digest(p), 'bytes': p.stat().st_size,
                              'reason': 'Retired QA-only SQLite fixture; test-a/test-b records, no active QA process'})
        else:
            assert not local_files, f'Expected empty old temporary directory: {folder}'
        directories.extend(str(p) for p in children if p.is_dir())
        directories.append(str(folder))

    # Search exact unique directory names, not generic temp prefixes. Historical
    # evidence may mention a retired fixture without being a runtime dependency.
    command = ['rg', '-l', '--hidden', '-F', '-g', '!quant_env/**', '-g', '!.git/**',
               '-g', '!project_memory/holdout_restricted/**', '-g', '!K线数据/**',
               '-g', '!**/node_modules/**', '-g', '!tools/audit_cache_candidates.py',
               '-g', '!tools/cleanup_confirmed_cache.ps1']
    for name in NAMES:
        command += ['-e', name]
    scan = subprocess.run(command + ['.'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert scan.returncode == 1, f'Reference matches or scan error; review first: {scan.stdout} {scan.stderr}'
    for config in (Path.home() / '.codex/automations').glob('*/automation.toml'):
        text = config.read_text(encoding='utf-8')
        assert not any(name in text for name in NAMES), f'Automation reference: {config}'
    tasks = (AUDIT / 'task_actions.json').read_text(encoding='utf-8-sig')
    assert not any(name in tasks for name in NAMES)

    plan = {'scan_scope': 'Repository exact-name references, Codex automation TOML, Windows task actions; live processes rechecked by deletion tool',
        'not_a_global_reference_proof': True, 'fixture_checks': fixture_checks,
        'files': files, 'empty_directories': directories,
        'file_count': len(files), 'bytes': sum(x['bytes'] for x in files)}
    (AUDIT / 'approved_cache_plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'files': plan['file_count'], 'bytes': plan['bytes'], 'temp_roots': len(NAMES), 'fixture_databases': len(fixture_checks)}))


if __name__ == '__main__':
    main()
