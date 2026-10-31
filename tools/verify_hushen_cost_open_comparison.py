"""Verify user-fixed fees, opening-price fills and unchanged cash/strategy rules."""
from pathlib import Path
from types import SimpleNamespace as NS
import argparse
import json

import numpy as np
import pandas as pd

from compare_hushen_cost_open_annual_csi300 import fee_only_engine,SOURCE
from replay_hushen2_local import sha


def isolated_open_cash_check():
    class Market:outs={}
    a=fee_only_engine().Account(pd.Timestamp('2026-10-22'),Market(),initial=11000)
    row=NS(open=10.,high=11.,low=9.,close=10.,preclose=10.,volume=1_000_000.,tradestatus=1.,prev_actual=10.,adjust_ratio=1.)
    a.day={s:row for s in ['600000.SH','600001.SH']}
    a.bars={s:NS(open=10.,high_limit=11.,low_limit=9.,is_paused=False,is_st=False,volume=1_000_000.) for s in a.day}
    a.sync()
    assert a.order('600000.SH',1000,a.m._limit_price(a.bars['600000.SH'],True)) is not None
    assert a.trades[-1]['price']==10.02 and a.trades[-1]['commission']==5 and a.trades[-1]['transfer']==0
    a.date=pd.Timestamp('2026-10-23')
    assert a.order('600000.SH',-1000,a.m._limit_price(a.bars['600000.SH'],False)) is not None
    assert a.trades[-1]['price']==9.98 and a.trades[-1]['stamp']==9.98
    assert abs(a.cash-10940.02)<1e-8 and not a.receivables
    assert a.order('600001.SH',100,10.02) is not None,'Hushen1 original same-session sale reuse must remain available'
    assert not a.settle_sale_next_session
    return 'passed:open10 buy10.02/sell9.98,fees,zero transfer,same-session sale reuse preserved'


def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args();out=args.output.resolve()
    unit=isolated_open_cash_check();s=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));p=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert s['status']=='verified' and not s['action_gaps'] and len(s['rows'])==16
    assert all(sha(Path(f))==h for f,h in p['protected_before'].items())
    ix=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet');index=pd.Series(pd.to_numeric(ix.close).to_numpy(),index=pd.to_datetime(ix.date))
    count=0;max_error=0.;flags=[];holdings=[];pairs={};reuse_count=0
    n={2020:58,2021:58,2022:58,2023:59,2024:58,2025:57,2026:56}
    for r in s['rows']:
        f=out/'runs'/r['group']/r['strategy'];m=pd.read_parquet(f/'START_METRICS.parquet');c=pd.read_parquet(f/'EQUITY_CURVES.parquet');t=pd.read_parquet(f/'TRADES.parquet')
        assert len(m)==r['starts']==n[r['year']];count+=len(m);pairs[(r['group'],r['strategy'])]=m
        assert pd.to_datetime(m.start_date).dt.year.eq(r['year']).all() and pd.to_datetime(m.start_date).dt.month.le(3).all()
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy(float);start=pd.Timestamp(g.start_date.iloc[0]);end=pd.Timestamp(g.date.iloc[-1]);span=(end-start).days
            ret=e/np.r_[100000.,e[:-1]]-1;bm=(index.loc[end]/index.loc[start])**(365/span)-1
            values=dict(cumulative_return=e[-1]/100000.-1,annualized_return=(e[-1]/100000.)**(365/span)-1,
                        maximum_drawdown=float((e/np.maximum.accumulate(e)-1).min()),sharpe_zero_rf_252_ddof0=float(np.sqrt(252)*ret.mean()/ret.std(ddof=0)),benchmark_annualized=bm)
            values['annualized_excess']=values['annualized_return']-bm
            old=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            for k,v in values.items():
                err=abs(old[k]-v);max_error=max(max_error,err);assert err<1e-10,(r['group'],r['strategy'],ordinal,k)
        if r['strategy']=='hushen1_cost_only_open':
            assert c.cash.ge(-.01).all() and np.allclose(c.equity,c.cash+c.market_value+c.receivables,atol=1e-6,rtol=0)
            value=(t.qty.abs()*t.price).round(2)
            assert t.transfer.eq(0).all()
            assert np.allclose(t.commission,np.maximum(5,value*.0003).round(2),atol=.011,rtol=0)
            assert np.allclose(t.stamp,np.where(t.qty.lt(0),(value*.001).round(2),0),atol=.011,rtol=0)
            holdings.append(dict(group=r['group'],maximum_actual_holdings=int(c.holdings.max())))
        else:
            old=SOURCE/'runs'/r['group']/'hushen2'
            assert sha(f/'EQUITY_CURVES.parquet')==sha(old/'EQUITY_CURVES.parquet')
            assert sha(f/'TRADES.parquet')==sha(old/'TRADES.parquet');reuse_count+=1
        data=json.loads((f/'DATA_FLAGS.json').read_text(encoding='utf-8'))
        assert not data['missing_action_keys']
        if data['legacy_unexplained_actions'] or data['legacy_action_reference_differences']:flags.append(dict(group=r['group'],details=data))
    assert count==924
    for group in [str(y) for y in range(2020,2027)]+['2020_to_current']:
        a=pairs[(group,'hushen1_cost_only_open')];b=pairs[(group,'hushen2')]
        assert a.start_date.tolist()==b.start_date.tolist() and a.end_date.tolist()==b.end_date.tolist()
        assert np.allclose(a.benchmark_annualized,b.benchmark_annualized,atol=1e-12,rtol=0)
    v=dict(status='passed',account_paths=count,max_independent_metric_error=max_error,action_gaps=0,legacy_data_flags=flags,
           isolated_open_cash_check=unit,hushen2_groups_byte_identical_to_existing=reuse_count,
           hushen1_position_counts=holdings,protected_unchanged=True,summary_sha256=sha(out/'SUMMARY.json'))
    (out/'VERIFICATION.json').write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('VERIFIED',count,'PATHS','MAX_ERROR',max_error,'FLAGS',len(flags))
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0']
    labels={'hushen1_cost_only_open':'沪深1·统一费用/开盘撮合','hushen2':'沪深2·统一费用'}
    display=[]
    print('| 起点组 | 版本 | 起点数 | 累计收益 | 年化收益 | 年化超额（沪深300） | 最大回撤 | Sharpe |')
    print('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for group in [str(y) for y in range(2020,2027)]+['2020_to_current','2026_to_current']:
        actual='2026' if group=='2026_to_current' else group
        rows=[r for r in s['rows'] if r['group']==actual]
        name=group.replace('_to_current','Q1→至今') if '_to_' in group else group+'Q1→年末' if group!='2026' else '2026Q1→至今'
        for r in rows:
            fields=[]
            for k in keys:
                val=f"{r[k]*100:.2f}" if k=='annualized_excess' else f"{r[k]:.3f}" if k=='sharpe_zero_rf_252_ddof0' else f"{r[k]:.2%}"
                if r[k]>=max(a[k] for a in rows)-1e-12:val='**'+val+'**'
                fields.append(val)
            print(f"| {name} | {labels[r['strategy']]} | {r['starts']} | "+' | '.join(fields)+' |')
            display.append(dict(display_group=group,**r))
    (out/'COMPARISON.json').write_text(json.dumps(dict(end=s['end'],benchmark='CSI300 price',rows=display,verification='VERIFICATION.json'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
