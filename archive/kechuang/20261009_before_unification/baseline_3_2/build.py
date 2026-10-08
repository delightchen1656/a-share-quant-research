"""Build standalone 3-2 from frozen 3-1 daily model/feature definitions."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    sources = [ROOT / 'supermind_baseline_3_1_high_attack_adaptive_expiry.py',
               ROOT / 'supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py']
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    source = sources[1].read_text(encoding='utf-8')
    result = source[:source.index('def init(context):')]
    result += (HERE / 'runtime.py').read_text(encoding='utf-8')
    result = result.replace('SuperMind daily-frequency execution strategy for STAR events.',
                            'SuperMind baseline 3-2 DAILY audit revision; legacy models retained.')
    compile(result, '<baseline3-2>', 'exec')
    target = ROOT / 'supermind_baseline_3_2_audited_daily.py'
    target.write_text(result, encoding='utf-8')
    manifest = {'source_sha256': hashes, 'output_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'signal_threshold': .63, 'model_status': 'legacy, not retrained',
                'evaluation_status': 'historical development replay, NOT independent OOS'}
    (HERE / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    print(target)


if __name__ == '__main__':
    main()
