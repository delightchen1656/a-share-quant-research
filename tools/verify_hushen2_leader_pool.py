"""Audit final account results and print the leader-pool comparison tables."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research_hushen2_leader_pool import VARIANTS, ROOT, LEADERS, sha

LABELS = dict(current='现有沪深2', leader_no_refill='龙头过滤·不递补', leader_refill='龙头过滤·递补', leader_pool_rank='龙头池内重排名')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    summary = json.loads((out / 'SUMMARY.json').read_text(encoding='utf-8'))
    assert summary['status'] == 'verified' and not summary['action_gaps']
    protocol = json.loads((out / 'PROTOCOL.json').read_text(encoding='utf-8'))
    assert all(sha(Path(p)) == h for p, h in protocol['protected_before'].items())
    leaders = set(json.loads(LEADERS.read_text(encoding='utf-8-sig')))
    checked_paths = 0
    hashes = {}
    for row in summary['rows']:
        folder = out / str(row['year']) / row['variant']
        mp = folder / 'START_METRICS.parquet'
        tp = folder / 'TRADES.parquet'
        hashes[str(mp.relative_to(out))] = sha(mp)
        hashes[str(tp.relative_to(out))] = sha(tp)
        m, t = pd.read_parquet(mp), pd.read_parquet(tp)
        expected = {2020:58, 2021:58, 2022:58, 2023:59, 2024:58}[row['year']]
        assert len(m) == expected and m.start_ordinal.is_unique
        assert pd.to_datetime(m.start_date).dt.month.le(3).all()
        checked_paths += len(m)
        assert (t.entry_date > t.signal_date).all()
        assert (t.entry_date - t.signal_date).dt.days.le(7).all()
        assert (t.exit_date > t.entry_date).all()
        assert t.exit_date.max() <= pd.Timestamp(f"{row['year']}-12-31")
        if row['variant'] != 'current':
            assert t.symbol.str[:6].isin(leaders).all()
        for (_, _), g in t.groupby(['start_ordinal', 'symbol']):
            g = g.sort_values('entry_date')
            if len(g) > 1:
                assert (g.entry_date.iloc[1:].to_numpy() > g.exit_date.iloc[:-1].to_numpy()).all()
        pnl = t.groupby('start_ordinal').pnl.sum().reindex(m.start_ordinal, fill_value=0).to_numpy()
        assert np.allclose(pnl, m.cumulative_return.to_numpy() * 100000, atol=1e-6, rtol=0)
        assert abs(len(t) / len(m) - row['filled']) < 1e-12
        for reason, key in [('take', 'take_count'), ('stop', 'stop_count'), ('expiry', 'expiry_count')]:
            assert abs(t.reason.eq(reason).sum() / len(m) - row[key]) < 1e-12
    receipts = {p.name: sha(p) for p in (out / 'actions').glob('*.json')}
    verification = dict(status='passed', paths=checked_paths, additional_company_action_receipts=len(receipts),
                        action_receipt_hashes=receipts, result_hashes=hashes,
                        summary_sha256=sha(out / 'SUMMARY.json'), script_sha256=sha(Path(__file__)),
                        checks=['baseline per-path metric parity in runner', 'cash PNL identity', 'Q1 population', 'T+1',
                                '7calendar entry window', 'no overlapping same-stock holdings', 'leader execution scope',
                                'trade counts and exits', 'zero company action coverage gaps', 'production hashes unchanged'],
                        retraining='not performed; pending original training definition')
    (out / 'VERIFICATION.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
    print('AUDIT PASSED', checked_paths, 'paths, receipts', len(receipts))
    print('| 年份 | 版本 | 年化收益均值 | 年化超额 | 平均最大回撤 | 平均Sharpe |')
    print('| --- | --- | ---: | ---: | ---: | ---: |')
    for row in summary['rows']:
        print(f"| {row['year']} | {LABELS[row['variant']]} | {row['annualized_return']:.2%} | {row['annualized_excess']*100:.2f} | {row['maximum_drawdown']:.2%} | {row['sharpe_zero_rf_252_ddof0']:.3f} |")
    print('| 年份 | 版本 | 买入成交 | 挂单失败 | 止盈 | 止损 | 到期退出 |')
    print('| --- | --- | ---: | ---: | ---: | ---: | ---: |')
    for row in summary['rows']:
        print(f"| {row['year']} | {LABELS[row['variant']]} | " + ' | '.join(f"{row[k]:.1f}" for k in ['filled', 'failed', 'take_count', 'stop_count', 'expiry_count']) + ' |')
    for v in VARIANTS:
        rows = [r for r in summary['rows'] if r['variant'] == v]
        later = [r for r in rows if r['year'] >= 2022]
        print('OVERVIEW', v, 'fiveyear annual mean', np.mean([r['annualized_return'] for r in rows]),
              'worst annual mean', min(r['annualized_return'] for r in rows),
              '2022-24 annual mean', np.mean([r['annualized_return'] for r in later]),
              '2022-24 sharpe mean', np.mean([r['sharpe_zero_rf_252_ddof0'] for r in later]))


if __name__ == '__main__':
    main()
