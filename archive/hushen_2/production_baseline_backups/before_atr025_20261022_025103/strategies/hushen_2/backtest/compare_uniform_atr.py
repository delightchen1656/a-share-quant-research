"""Independent risk and frozen-input checks for the two uniform ATR account variants."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import numpy as np
import pandas as pd
from compute_risk_metrics import recompute_metrics
from run_june2020_starts import ROOT,BASE
from market import digest

REFERENCE=BASE/'results/holdout_restricted/baseline_fixed_ioc_all_start_groups/attempt_20261020_041659/FULL_COMPARISON.json'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',nargs=8,type=Path);parser.add_argument('--protected-before',required=True,type=Path);args=parser.parse_args()
    ref=json.loads(REFERENCE.read_text(encoding='utf-8'))
    expected={r['start_count']:r for r in ref['groups'] if r['variant']=='only_fixed_quantity_and_ioc'}
    old={};rows=[];checks=[]
    for group in ['q1_2020','june2020','q1_2025','q1_2026']:
        for directory in sorted((BASE/f'results/holdout_restricted/baseline_fixed_ioc_{group}').glob('attempt_*'),reverse=True):
            path=directory/'SUMMARY.json'
            if not path.exists():continue
            s=json.loads(path.read_text(encoding='utf-8'))
            if s['status']!='complete':continue
            target=expected[s['runs']]
            if abs(s['annualized_return_mean']-target['annualized_return_mean'])>1e-12:continue
            key=tuple(s['start_range']);old[key]=directory
            row=dict(group=group,variant='mixed',**s)
            rows.append(row)
            break
        else:raise RuntimeError('Missing exact fixed-IOC reference '+group)
    seen=set()
    for directory in args.directories:
        s=json.loads((directory/'SUMMARY.json').read_text(encoding='utf-8'))
        p=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
        assert p['mode']=='baseline_fixed_ioc_uniform_execution_atr'
        policy=p['atr'];assert policy in ('relative','price')
        assert s['status']=='complete' and not s['corporate_action_gaps']
        assert s['terminal_open_positions_max']==s['terminal_pending_orders_max']==0
        key=tuple(s['start_range']);baseline=old[key]
        assert (key,policy) not in seen;seen.add((key,policy))
        assert (directory/'SIMULATE_SOURCE.txt').read_bytes()==(baseline/'SIMULATE_SOURCE.txt').read_bytes()
        for path,h in p['source_hashes'].items():assert digest(ROOT/path)==h
        atr_receipt=next(ROOT/path for path in p['source_hashes'] if path.endswith('/VERIFICATION.json') or path.endswith('\\VERIFICATION.json'))
        atr_check=json.loads(atr_receipt.read_text(encoding='utf-8'))
        for path,h in {**atr_check['input_hashes'],**atr_check['original_cache_hashes']}.items():assert digest(ROOT/path)==h
        for receipt in p['action_sources'].get('fixed_ioc_missing_key_receipts',[]):assert digest(ROOT/receipt['path'])==receipt['sha256']
        original=pd.read_parquet(baseline/'FROZEN_SIGNALS.parquet')
        signals=pd.read_parquet(directory/'FROZEN_SIGNALS.parquet')
        assert original.drop(columns='atr_pct').equals(signals.drop(columns='atr_pct'))
        unchanged=original.date.lt(pd.Timestamp('2025-01-01')) if policy=='relative' else original.date.ge(pd.Timestamp('2025-01-01'))
        np.testing.assert_array_equal(original.loc[unchanged,'atr_pct'],signals.loc[unchanged,'atr_pct'])
        curves=pd.read_parquet(directory/'EQUITY_CURVES.parquet');calculated=recompute_metrics(curves)
        assert len(calculated)==s['runs']
        for field,col in [('cumulative_return_mean','cumulative_return'),('annualized_return_mean','annualized_return'),
                          ('maximum_drawdown_mean','maximum_drawdown'),('sharpe_mean','sharpe_zero_rf_252_ddof0')]:
            np.testing.assert_allclose(s[field],calculated[col].mean(),rtol=0,atol=1e-12)
        if policy=='price' and key[0]>='2025-01-01':
            original_curves=pd.read_parquet(baseline/'EQUITY_CURVES.parquet')
            assert curves.equals(original_curves),'Post2024 uniform price must reproduce mixed exactly'
        if policy=='relative' and key[0]<'2025-01-01':
            original_curves=pd.read_parquet(baseline/'EQUITY_CURVES.parquet')
            assert curves.loc[curves.date.lt('2025-01-01')].equals(original_curves.loc[original_curves.date.lt('2025-01-01')])
        trades=pd.read_parquet(directory/'TRADES.parquet')
        for reason in ['take','stop','expiry']:assert trades.reason.eq(reason).sum()/s['runs']==s[reason+'_count_mean']
        label=next(r['group'] for r in rows if tuple(r['start_range'])==key)
        rows.append(dict(group=label,variant=policy,**s))
        checks.append(dict(directory=str(directory.resolve()),baseline=str(baseline),variant=policy,
            simulator_source_identical=True,non_atr_signal_columns_identical=True,risk_recomputed=True,
            hashes={path.name:digest(path) for path in [directory/'SUMMARY.json',directory/'PROTOCOL.json',
                directory/'EQUITY_CURVES.parquet',directory/'FROZEN_SIGNALS.parquet']}))
    assert len(seen)==8
    order={'q1_2020':0,'june2020':1,'q1_2025':2,'q1_2026':3};variant_order={'mixed':0,'relative':1,'price':2}
    rows.sort(key=lambda x:(order[x['group']],variant_order[x['variant']]))
    out=BASE/'results/holdout_restricted/uniform_atr_comparison'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    protected=json.loads(args.protected_before.read_text(encoding='utf-8'))
    for item in protected:assert digest(Path(item['Path'])).lower()==item['Hash'].lower(),('Protected file changed',item['Path'])
    report=dict(status='verified',end='2026-10-19',units='Equal-weight per-start means',
        strategy='Only execution ATR changed; original fixed-quantity IOC and expiry-session close retained',
        historical_posterior_not_blind=True,software_and_account_changed=False,protected_files_hashes_verified=protected,rows=rows,checks=checks,
        reference=str(REFERENCE),reference_sha256=digest(REFERENCE),verifier_sha256=digest(Path(__file__)))
    (out/'COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True)
    for row in rows:
        print(json.dumps({k:row[k] for k in ['group','variant','runs','cumulative_return_mean','annualized_return_mean',
            'maximum_drawdown_mean','sharpe_mean']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
