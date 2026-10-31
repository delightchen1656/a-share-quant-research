"""Per-module launch environment. This is coordination, not a security sandbox."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).with_name('environments') / 'modules.json'


def module_environment(name, repo=ROOT):
    profiles = json.loads((repo / 'tools/environments/modules.json').read_text(encoding='utf-8'))
    profile = profiles[name]
    owner = (repo / profile['directory']).resolve()
    owner.relative_to(repo.resolve())
    local = owner / '.local'
    env = os.environ.copy()
    # Do not inherit a different chat's injected Python imports or shared temp path.
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONPYCACHEPREFIX'):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONUTF8='1')
    for key, suffix in {'TEMP': 'tmp', 'TMP': 'tmp', 'MPLCONFIGDIR': 'matplotlib',
                        'XDG_CACHE_HOME': 'cache', 'PIP_CACHE_DIR': 'pip-cache'}.items():
        target = local / suffix
        target.mkdir(parents=True, exist_ok=True)
        env[key] = str(target)
    independent = owner / '.venv/Scripts/python.exe'
    python = independent if independent.is_file() else repo / 'quant_env/Scripts/python.exe'
    return profile, owner, python, env


def validate_script(repo, owner, profile, value):
    script = (repo / value).resolve()
    script.relative_to(repo.resolve())
    allowed = [(repo / p).resolve() for p in profile.get('tool_entries', [])]
    if not script.is_relative_to(owner) and script not in allowed:
        raise ValueError('Script must belong to this module or its explicit tool_entries')
    if not script.is_file() or script.suffix not in ('.py', '.pyw'):
        raise ValueError('Expected an existing Python script')
    return script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module')
    parser.add_argument('--probe', action='store_true', help='Check interpreter and per-module temp/cache paths only')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    profile, owner, python, env = module_environment(args.module)
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    if command == ['--probe'] or args.probe:
        code = ('import json,sys,tempfile,os; print(json.dumps(dict('
                'python=sys.executable,base=sys.base_prefix,temp=tempfile.gettempdir(),'
                'matplotlib=os.environ["MPLCONFIGDIR"],'
                'no_user_site=sys.flags.no_user_site,dont_write_bytecode=sys.dont_write_bytecode)))')
        argv = ['-c', code]
    else:
        if not command:
            parser.error('provide --probe or -- path/to/script.py [arguments]')
        argv = [str(validate_script(ROOT, owner, profile, command[0])), *command[1:]]
    return subprocess.call([str(python), '-X', 'utf8', '-B', '-s', *argv], cwd=ROOT, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
