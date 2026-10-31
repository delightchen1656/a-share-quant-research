import datetime
import json
from settings import BASE,OUT,sha,dump,install_read_boundary
install_read_boundary()
reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
target=BASE/'src_factor_v5/build_features.py'
old=next(x['sha256'] for x in reg['files'] if x['path'].endswith('build_features.py'))
dump(OUT/'engineering_amendment.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    reason='Initial parallel new-feature build raised duplicate-index alignment error before any output panel or model scores. Sequential single-symbol replay has unique indices. Use one worker and independent calendar copy plus uniqueness assertion.',
    feature_definitions_or_model_parameters_changed=False,before_any_new_model_outcomes=True,
    original_builder_sha256=old,amended_builder_sha256=sha(target),
    original_registration_retained=True,raw_inputs_not_modified=True))
print('Engineering-only builder amendment recorded before scores.',flush=True)
