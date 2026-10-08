"""Repeat the frozen 100k start-date study with 500k; no model or rule tuning."""
from pathlib import Path
import hashlib

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parent / 'baseline_3_1_start_dates_100k_20261008/run.py'
source = REFERENCE.read_text(encoding='utf-8')
reference_hash = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
assert 'CASH=100000.' in source
source = source.replace('100000', '500000').replace('100k', '500k').replace('10万元', '50万元')
# The inherited executor already enforces the same condition; verify it explicitly.
engine = HERE.parent / 'baseline_3_2/start_date_study.py'
assert 'if qty<=0 or (qty<200 and qty!=sellable): continue' in engine.read_text(encoding='utf-8')
source = source.replace("'capital':500000", "'capital':500000,'minimum_sell_rule_verified':True,'reference_script_sha256':" + repr(reference_hash))
exec(compile(source, str(REFERENCE), 'exec'), globals())
