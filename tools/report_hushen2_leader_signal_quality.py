"""Retrospective leader subset of frozen signal paths; does not rerank signals."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'archive/reports/holdout_restricted/hushen2_signal_quality'
LEADERS = ROOT / '研究尝试/方向1_超跌反弹/holdout_restricted/leader_classification/mainboard_leader_codes.json'
SOURCES = [
    ROOT / 'archive/reports/holdout_restricted/hushen2_signal_paths/pre2025_20261028_164437/all_event_paths.csv',
    ROOT / 'archive/reports/holdout_restricted/hushen2_signal_paths/post2024_20261028_165504/all_event_paths.csv',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = json.loads((BASE / 'LATEST.json').read_text(encoding='utf-8-sig'))
    codes = set(json.loads(LEADERS.read_text(encoding='utf-8-sig')))
    result = {k: original[k] for k in ('schema_version', 'strategy', 'baseline', 'asof', 'units', 'method')}
    result['scope'] = 'Existing frozen signals intersected with current leader codes; no rerank or refill'
    result['classification_warning'] = '2026-10-27 current leader snapshot applied retrospectively; not historical point-in-time membership or isolated development.'
    result['leader_count'] = len(codes)
    result['provenance'] = [{'path': str(p.relative_to(ROOT)), 'sha256': digest(p)} for p in [LEADERS, *SOURCES, BASE / 'LATEST.json']]
    result['periods'] = []
    for source, reference in zip(SOURCES, original['periods']):
        full = pd.read_csv(source, dtype={'code': str}, low_memory=False)
        selected = full[full['code'].isin(codes)].copy()
        assert selected['signal_id'].is_unique
        rows = []
        for h in range(21):
            high = pd.to_numeric(selected[f'd{h}_high_return'], errors='raise').dropna()
            cumulative = pd.to_numeric(selected[f'd{h}_cumulative_high_return'], errors='raise').dropna()
            close = pd.to_numeric(selected[f'd{h}_close_return'], errors='raise').dropna()
            # First verify the aggregation reproduces the saved all-signal table.
            for suffix, key in [('high_return', 'average_daily_high'), ('cumulative_high_return', 'average_cumulative_high'), ('close_return', 'average_close_return')]:
                assert abs(float(full[f'd{h}_{suffix}'].mean()) - reference['rows'][h][key]) < 1e-10
            rows.append({
                'day': 'D0' if h == 0 else f'D+{h}',
                'average_daily_high': float(high.mean()) if len(high) else None,
                'average_cumulative_high': float(cumulative.mean()) if len(cumulative) else None,
                'average_close_return': float(close.mean()) if len(close) else None,
                'close_win_rate': float((close > 0).mean()) if len(close) else None,
                'valid_n_high': len(high), 'valid_n_cumulative': len(cumulative),
                'valid_n_close': len(close), 'signal_count': len(selected),
            })
        result['periods'].append({'period': reference['period'], 'signal_count': len(selected),
                                 'original_signal_count': len(full),
                                 'valid_close_D0': rows[0]['valid_n_close'],
                                 'valid_close_D20': rows[20]['valid_n_close'],
                                 'signal_ids': selected['signal_id'].tolist(), 'rows': rows})
    target = BASE / 'LEADERS_20261027.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(target)
    for p in result['periods']:
        print(p['period'], p['signal_count'], p['valid_close_D0'], p['valid_close_D20'])
    for a, b in zip(*(p['rows'] for p in result['periods'])):
        keys = ('average_daily_high', 'average_cumulative_high', 'average_close_return', 'close_win_rate')
        print('| ' + a['day'] + ' | ' + ' | '.join(f'{a[k]:.2%} → {b[k]:.2%}' for k in keys) + ' |')
    print('ALL_SIGNAL_AGGREGATION_PARITY: PASS')


if __name__ == '__main__':
    main()
