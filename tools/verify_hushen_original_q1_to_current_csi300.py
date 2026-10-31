"""Recompute original-execution Q1-to-current metrics and CSI300 excess."""
from pathlib import Path
import argparse
import json

import numpy as np
import pandas as pd

from replay_hushen2_local import sha


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output.resolve()
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert summary['status']=='verified' and not summary['action_gaps'] and len(summary['rows'])==14
    assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    ix=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet');index=pd.Series(pd.to_numeric(ix.close).to_numpy(),index=pd.to_datetime(ix.date))
    assert sha(out/'CSI300_PRICE_INDEX.parquet')==protocol['benchmark_sha256']
    expected={2020:58,2021:58,2022:58,2023:59,2024:58,2025:57,2026:56};count=0;maximum_error=0.;flags=[];pairs={};position_counts=[]
    for r in summary['rows']:
        folder=out/'runs'/r['group']/r['strategy'];m=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet')
        assert len(m)==r['starts']==expected[r['year']]
        assert pd.to_datetime(m.start_date).dt.year.eq(r['year']).all() and pd.to_datetime(m.start_date).dt.month.le(3).all()
        assert set(m.end_date)=={summary['end']}
        count+=len(m);pairs[(r['year'],r['strategy'])]=m
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy(float);start=pd.Timestamp(g.start_date.iloc[0]);end=pd.Timestamp(g.date.iloc[-1]);span=(end-start).days
            ret=e/np.r_[100000.,e[:-1]]-1
            values=dict(cumulative_return=e[-1]/100000.-1,annualized_return=(e[-1]/100000.)**(365/span)-1,
                        maximum_drawdown=float((e/np.maximum.accumulate(e)-1).min()),sharpe_zero_rf_252_ddof0=float(np.sqrt(252)*ret.mean()/ret.std(ddof=0)))
            bm=(index.loc[end]/index.loc[start])**(365/span)-1
            values.update(benchmark_annualized=bm,annualized_excess=values['annualized_return']-bm)
            row=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            for k,v in values.items():
                error=abs(row[k]-v);maximum_error=max(maximum_error,error);assert error<1e-10,(r['year'],r['strategy'],ordinal,k)
        if r['strategy']=='hushen1_original':
            assert c.cash.ge(-.01).all()
            # Original Hushen1 targets five names but does not silently remove
            # old positions whose target-zero sell has not completed.
            position_counts.append(dict(year=r['year'],maximum_actual_holdings=int(c.holdings.max()),
                                        account_days_above_five=int(c.holdings.gt(5).sum())))
            assert np.allclose(c.equity,c.cash+c.market_value+c.receivables,atol=1e-6,rtol=0)
            value=(t.qty.abs()*t.price).round(2);date=pd.to_datetime(t.date)
            transfer=(value*np.where(date<pd.Timestamp('2022-04-29'),.00002,.00001)).round(2)
            stamp=np.where(t.qty.lt(0),(value*np.where(date<pd.Timestamp('2023-08-28'),.001,.0005)).round(2),0.)
            assert np.allclose(t.transfer,transfer,atol=.011,rtol=0)
            assert np.allclose(t.stamp,stamp,atol=.011,rtol=0)
            assert np.allclose(t.commission,np.maximum(5,value*.0003).round(2),atol=.011,rtol=0)
        d=json.loads((folder/'DATA_FLAGS.json').read_text(encoding='utf-8'))
        assert not d['missing_action_keys']
        if d['legacy_unexplained_actions'] or d['legacy_action_reference_differences']:
            flags.append(dict(year=r['year'],strategy=r['strategy'],details=d))
    for year in expected:
        a=pairs[(year,'hushen1_original')];b=pairs[(year,'hushen2')]
        assert a.start_date.tolist()==b.start_date.tolist()
        assert np.allclose(a.benchmark_annualized,b.benchmark_annualized,atol=1e-12,rtol=0)
    assert count==808
    result=dict(status='passed',account_paths=count,independent_metric_max_error=maximum_error,action_gaps=0,
                legacy_flags=flags,benchmark='CSI300 PRICE INDEX sh.000300',end=summary['end'],
                source_sha256=sha(Path(__file__)),summary_sha256=sha(out/'SUMMARY.json'),protected_unchanged=True,
                original_hushen1_historical_fee_checks_passed=True,all_cohorts_end_same_day=True,
                original_hushen1_position_policy='Target5names, not hard5slots; uncompleted old-position exits retained',
                original_hushen1_actual_holdings=position_counts)
    (out/'VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('VERIFIED',count,'paths','MAX_ERROR',maximum_error,'LEGACY_FLAGS',len(flags))
    names={'hushen1_original':'沪深1·原口径','hushen2':'沪深2·原口径'}
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0']
    print('| 起点组 | 版本 | 起点数 | 累计收益 | 年化收益 | 年化超额（沪深300） | 最大回撤 | Sharpe |')
    print('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for year in expected:
        rows=[r for r in summary['rows'] if r['year']==year]
        for r in rows:
            fields=[]
            for k in keys:
                v=f"{r[k]*100:.2f}" if k=='annualized_excess' else f"{r[k]:.3f}" if k=='sharpe_zero_rf_252_ddof0' else f"{r[k]:.2%}"
                if r[k]>=max(row[k] for row in rows)-1e-12:v='**'+v+'**'
                fields.append(v)
            print(f"| {year}Q1→至今 | {names[r['strategy']]} | {r['starts']} | "+' | '.join(fields)+' |')


if __name__=='__main__':main()
