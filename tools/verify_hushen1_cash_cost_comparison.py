"""Independent saved-curve/fee audit and table renderer for the controlled comparison."""
from pathlib import Path
import argparse
import json
import math

import numpy as np
import pandas as pd

from replay_hushen2_local import ROOT, sha


def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args();out=args.output.resolve()
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert not summary['smoke_only'] and not summary['action_gaps']
    assert all(sha(Path(f))==h for f,h in protocol['protected_before'].items())
    rows=summary['rows'];assert len(rows)==18
    total=0;delta=0.;regression=[];filehashes={}
    expected={2020:58,2021:58,2022:58,2023:59,2024:58,2025:57,2026:56}
    for row in rows:
        folder=out/'runs'/row['group']/row['strategy']
        mp=folder/'START_METRICS.parquet';cp=folder/'EQUITY_CURVES.parquet';tp=folder/'TRADES.parquet'
        for f in [mp,cp,tp]:filehashes[str(f.relative_to(out))]=sha(f)
        m=pd.read_parquet(mp);c=pd.read_parquet(cp);t=pd.read_parquet(tp)
        assert len(m)==row['starts']==expected[row['year']]
        assert m.start_ordinal.is_unique
        assert pd.to_datetime(m.start_date).dt.year.eq(row['year']).all() and pd.to_datetime(m.start_date).dt.month.le(3).all()
        assert c.date.max()<=pd.Timestamp(row['end'])
        total+=len(m)
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy(float);ret=e/np.r_[100000,e[:-1]]-1
            span=(pd.Timestamp(g.date.iloc[-1])-pd.Timestamp(g.start_date.iloc[0])).days
            values=dict(cumulative_return=e[-1]/100000-1,annualized_return=(e[-1]/100000)**(365/span)-1,
                        maximum_drawdown=float((e/np.maximum.accumulate(e)-1).min()),
                        sharpe_zero_rf_252_ddof0=float(np.sqrt(252)*ret.mean()/ret.std(ddof=0)))
            old=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            for key,val in values.items():
                error=abs(val-old[key]);delta=max(delta,error);assert error<1e-10,(row['group'],ordinal,key)
            assert np.isfinite(e).all() and (e>0).all()
        if row['strategy']=='hushen1_cash_cost':
            assert c.cash.ge(-.01).all()
            assert np.allclose(c.equity,c.cash+c.market_value+c.receivables,atol=1e-6,rtol=0)
            assert (t.loc[t.qty.gt(0),'qty']%100).eq(0).all()
            assert t.transfer.eq(0).all()
            value=(t.qty.abs()*t.price).round(2)
            assert np.allclose(t.commission,np.maximum(5,value*.0003).round(2),atol=.011,rtol=0)
            assert np.allclose(t.stamp,np.where(t.qty.lt(0),(value*.001).round(2),0),atol=.011,rtol=0)
        elif row['group'].isdigit():
            if row['year']<=2024:
                ref=ROOT/'archive/reports/holdout_restricted/hushen2_leader_pool/pre2025_20261028_200500'/row['group']/'current/START_METRICS.parquet'
            else:
                ref=ROOT/'archive/reports/holdout_restricted/hushen2_leader_pool/post2024_20261028_202602'/row['group']/'current/START_METRICS.parquet'
            old=pd.read_parquet(ref)
            for k in ['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']:
                assert np.allclose(m[k],old[k],atol=1e-12,rtol=0),('Hushen2 unchanged',row['group'],k)
            regression.append(row['group'])
    assert total==1038
    verification=dict(status='passed',unique_paths=total,independent_metric_max_delta=delta,hushen2_annual_regression=regression,
        action_gaps=summary['action_gaps'],legacy_data_flags=[dict(group=r['group'],strategy=r['strategy'],issues=r['legacy_action_issues'],reference_differences=r['legacy_action_reference_differences']) for r in rows if r['legacy_action_issues'] or r['legacy_action_reference_differences']],
        protected_unchanged=True,source_sha256=sha(Path(__file__)),result_hashes=filehashes,
        cash_cost_policy_sha256=sha(ROOT/'沪深1研究/backtest/cash_cost_policy.json'),
        isolated_adapter_test='verify_hushen1_cash_cost_adapter.py passed including Friday to Monday cash release',
        annual2026_equals_continuous2026=True)
    (out/'VERIFICATION.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('VERIFIED',total,'paths','MAX_DELTA',delta,'LEGACY_FLAGS',verification['legacy_data_flags'])
    mapping={(r['group'],r['strategy']):r for r in rows}
    groups=[str(y) for y in range(2020,2027)]+['2020_to_current','2025_to_current','2026_to_current']
    display=[]
    print('| 起点组 | 版本 | 起点数 | 累计收益 | 年化收益 | 年化超额 | 最大回撤 | Sharpe | 平均买入笔数 |')
    print('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |')
    for group in groups:
        actual='2026' if group=='2026_to_current' else group
        pair=[mapping[(actual,s)] for s in ['hushen1_cash_cost','hushen2']]
        name=group.replace('_to_current','→至今') if '_to_' in group else group+'→年末' if group!='2026' else '2026→至今'
        for r in pair:
            label='沪深1·统一现金成本' if r['strategy']=='hushen1_cash_cost' else '现有沪深2'
            fields=[]
            for k in ['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0']:
                value=f"{r[k]*100:.2f}" if k=='annualized_excess' else f"{r[k]:.3f}" if k=='sharpe_zero_rf_252_ddof0' else f"{r[k]:.2%}"
                if r[k]>=max(a[k] for a in pair)-1e-12:value='**'+value+'**'
                fields.append(value)
            print('| '+name+' | '+label+f" | {r['starts']} | "+' | '.join(fields)+f" | {r['filled']:.1f} |")
            display.append(dict(group=group,source_group=actual,**{k:v for k,v in r.items() if k!='group'}))
    (out/'COMPARISON.json').write_text(json.dumps(dict(end=summary['end'],rows=display,verification='VERIFICATION.json',protocol='PROTOCOL.json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
