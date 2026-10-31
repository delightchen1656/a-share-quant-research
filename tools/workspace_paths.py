"""Canonical paths and explicit resolution of preserved historical path records.

Historical manifests remain immutable. Resolving a location never bypasses their
content hashes and does not grant a research reader access outside its whitelist.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
MARKET = ROOT / 'K线数据'
HUSHEN = MARKET / '沪深'
KECHUANG = MARKET / '科创'
GOLD = MARKET / '黄金'
UPDATES = MARKET / '更新备份与审计'

def resolve_recorded_path(value):
    value = str(value).replace('\\', '/')
    prefix = ROOT.as_posix() + '/'
    relative = value[len(prefix):] if value.lower().startswith(prefix.lower()) else value
    config = json.loads((ROOT/'tools/layout_paths.json').read_text(encoding='utf8'))
    for old, new in sorted(config['legacy_paths'].items(), key=lambda pair: -len(pair[0])):
        if relative == old or relative.startswith(old+'/'):
            return ROOT / (new + relative[len(old):])
    p = Path(value)
    return p if p.is_absolute() else ROOT/p
