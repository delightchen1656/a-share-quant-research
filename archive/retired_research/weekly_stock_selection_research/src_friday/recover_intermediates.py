"""Preserve Friday intermediates, then rebuild the original Monday files separately."""
from pathlib import Path
import hashlib
import json
import shutil
import datetime

BASE=Path(__file__).resolve().parent.parent
original=BASE/'audits/holdout_restricted/research_v1'
friday=BASE/'audits/holdout_restricted/friday_open_v2'
files=['weekly_schedule.parquet','schedule_skips.json','weekly_factor_panel.parquet','panel_audit.json']
assert not (friday/'directory_incident.json').exists()
registered=json.loads((original/'artifact_registration.json').read_text(encoding='utf-8'))
expected={Path(row['path']).name:row['sha256'] for row in registered['files']}
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
records=[]
for name in files:
    source=original/name
    assert source.exists()
    destination=friday/name
    assert not destination.exists()
    shutil.copy2(source,destination)
    records.append(dict(name=name,original_expected_sha256=expected[name],Friday_intermediate_sha256=digest(destination)))
payload=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    incident='Friday common.py audit path retained Monday directory because a literal string replacement did not match; four reproducible intermediate files were overwritten.',
    raw_inputs_and_fills_untouched=True,no_new_Friday_model_or_outcome_comparison_run=True,
    remediation='Preserve Friday intermediates here; rebuild Monday intermediates with unchanged original code; require all original registered artifact hashes to match.',files=records)
(friday/'directory_incident.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('Friday intermediates preserved; original expected hashes recorded.')
