"""Original Hushen1/Hushen2 execution, yearly Q1 full starts through common end."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
import argparse
import inspect
import json
import shutil

import numpy as np
import pandas as pd

import compare_hushen1_cash_cost_hushen2 as common
from replay_hushen2_local import ROOT,STRATEGY,APP,sha

SOURCE=ROOT/'archive/reports/holdout_restricted/hushen1_cash_cost_vs_hushen2/attempt_20261028_213602'


def prepare(out):
    h,_=common.health();assert h['market_date']=='2026-10-28'
    original=json.loads((SOURCE/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert original['end']==h['market_date']
    protected={p:sha(Path(p)) for p in original['protected_before']}
    protected[str(SOURCE/'SUMMARY.json')]=sha(SOURCE/'SUMMARY.json')
    protected[str(SOURCE/'H1_RANKINGS.json')]=sha(SOURCE/'H1_RANKINGS.json')
    protocol=dict(status='frozen_before_results',scope='2020..2026 Q1 EVERY trading-session start through20261028; not annual year-end cohorts',
        end=h['market_date'],market_health=h,
        hushen1='Original strict_daily_limits scenario:SLIP .001,5names98%,20session rebalance,1.5buffer,original100share cash resizing,original capacity,original historical stamp+transfer fees,same-session credited-sale reuse',
        hushen2='Unchanged registered ATR025 original-top3/no-refill,5slots20%,fixedIOC,priceTR,7/30calendar,2%volume,.002slip,.001stamp,no separate transfer,sales next-session,expiryclose,37dayterminalgate',
        benchmark='CSI300 PRICE INDEX sh.000300; mean(account CAGR minus benchmark CAGR) over identical starts',
        metrics='Daily closing account NAV;365/calendar-span CAGR;Sharpe252,ddof0,rf0;negative peak drawdown;average per-start metrics',
        no_retraining=True,no_strategy_or_software_change=True,protected_before=protected,
        data_source=str(SOURCE),reuse='Frozen verified market matrices and unchanged rankings; no parameter selection or recalibration')
    common.dump(out/'PROTOCOL.json',protocol)
    import daily_market_update as updater
    indexpath=out/'CSI300_PRICE_INDEX.parquet'
    assert updater.bs.login().error_code=='0'
    try:
        index=updater.query_history('sh.000300','2020-01-01',h['market_date'],'3')
    finally:updater.bs.logout()
    index.to_parquet(indexpath,index=False)
    ix=pd.DatetimeIndex(pd.to_datetime(index.date));close=pd.to_numeric(index.close)
    assert not ix.duplicated().any() and close.gt(0).all() and ix.max()==pd.Timestamp(h['market_date'])
    dates=json.loads((SOURCE/'inputs/dates_symbols.json').read_text(encoding='utf-8'))['dates']
    required=pd.DatetimeIndex([d for d in dates if d>='2020-01-01'])
    assert required.isin(ix).all(),'Benchmark missing a trading-session observation; do not fill'
    protocol.update(benchmark_rows=len(index),benchmark_sha256=sha(indexpath))
    common.dump(out/'PROTOCOL.json',protocol)
    print('BENCHMARK',len(index),'LAST',float(close.iloc[-1]),flush=True)


def initialize(out):
    common.initialize(str(SOURCE))
    out=Path(out);common.G['out']=out
    common.G['engine']=common.adapter(unified=False)
    base_init=common.G['engine'].Account.__init__
    def original_init(self,*args,**kwargs):
        base_init(self,*args,**kwargs)
        assert self.scenario=='strict_daily_limits' and self.m.SLIP_ONE_SIDE==.001
        assert not getattr(self,'settle_sale_next_session',False)
        assert not getattr(self,'no_transfer_fee',False) and not hasattr(self,'fixed_stamp_rate')
        assert (self.m.COUNT,self.m.EXPOSURE,self.m.INTERVAL,self.m.BUFFER,self.m.PARTICIPATION)==(5,.98,20,1.5,.005)
    common.G['engine'].Account.__init__=original_init
    index=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet')
    common.G['p2']['index']=pd.Series(pd.to_numeric(index.close).to_numpy(),index=pd.to_datetime(index.date))
    # New real response receipts only supplement coverage; original sources stay untouched.
    for path in (out/'actions').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));assert r['error_code']=='0'
        common.G['market'].actions.cache[r['key']]=r['records']
        p=common.G['p2'];symbol,year=r['key'].split('/')
        if r['key'] in p['known']:continue
        p['known'].add(r['key'])
        for row in r['records']:
            if not row.get('dividOperateDate'):continue
            d=pd.Timestamp(row['dividOperateDate']);n=lambda k:float(str(row.get(k,'')).strip() or 0)
            p['actions'].setdefault((d,symbol),[]).append(dict(cash=n('dividCashPsBeforeTax'),stock=n('dividStocksPs')+n('dividReserveToStockPs'),taxable_stock=n('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d)))
    source=inspect.getsource(common.job_group)
    assert source.count("strategy=='hushen1_cash_cost'")==2
    source=source.replace("strategy=='hushen1_cash_cost'","strategy=='hushen1_original'")
    line='            assert t.transfer.eq(0).all()\n'
    assert source.count(line)==1;source=source.replace(line,'')
    line="            if len(t):assert np.allclose(t.loc[t.qty.lt(0),'stamp'],(t.loc[t.qty.lt(0),'qty'].abs()*t.loc[t.qty.lt(0),'price']*.001).round(2),atol=.011)\n"
    assert source.count(line)==1;source=source.replace(line,'')
    exec(compile(source,'<original-execution-benchmark-only-report>','exec'),common.__dict__)


def run(job):return common.job_group(job)


def reuse_h2(out,year):
    group=f'{year}_to_current';old='2026' if year==2026 else group
    source=SOURCE/'runs'/old/'hushen2';target=out/'runs'/group/'hushen2';target.mkdir(parents=True,exist_ok=True)
    for name in ['EQUITY_CURVES.parquet','TRADES.parquet','DATA_FLAGS.json']:
        shutil.copy2(source/name,target/name)
        assert sha(source/name)==sha(target/name)
    m=pd.read_parquet(source/'START_METRICS.parquet')
    index=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet');s=pd.Series(pd.to_numeric(index.close).to_numpy(),index=pd.to_datetime(index.date))
    m['benchmark_annualized']=[(s.loc[pd.Timestamp(r.end_date)]/s.loc[pd.Timestamp(r.start_date)])**(365/r.calendar_day_span)-1 for r in m.itertuples()]
    m['annualized_excess']=m.annualized_return-m.benchmark_annualized
    m.to_parquet(target/'START_METRICS.parquet',index=False)
    previous=json.loads((SOURCE/'SUMMARY.json').read_text(encoding='utf-8'))
    r=next(dict(r) for r in previous['rows'] if r['strategy']=='hushen2' and r['group']==old)
    r.update(group=group,annualized_excess=float(m.annualized_excess.mean()),benchmark_changed_only=True,account_path_reused_from=str(source))
    return r


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--resume',action='store_true');parser.add_argument('--fetch-gaps',action='store_true');parser.add_argument('--workers',type=int,default=3);args=parser.parse_args()
    out=(args.output or ROOT/'archive/reports/holdout_restricted/hushen_original_q1_to_current_csi300'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')).resolve();out.mkdir(parents=True,exist_ok=True)
    print('OUTPUT',out,flush=True)
    if not args.resume:prepare(out)
    if args.fetch_gaps:common.fetch(out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    jobs=[(v,f'{y}_to_current',y,protocol['end']) for y in range(2020,2027) for v in ['hushen1_original','hushen2']]
    reused={}
    if args.resume and (out/'SUMMARY.json').exists():
        reused={(r['strategy'],r['group']):r for r in json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))['rows'] if not r['action_gaps']}
    for year in [2020,2025,2026]:
        key=('hushen2',f'{year}_to_current')
        if key not in reused:reused[key]=reuse_h2(out,year)
    rows=list(reused.values());jobs=[j for j in jobs if (j[0],j[1]) not in reused]
    print('ACCOUNT_GROUPS_REUSED',len(rows),'RUN',len(jobs),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(out),)) as pool:
        for f in as_completed([pool.submit(run,j) for j in jobs]):
            row=f.result();rows.append(row);print('COMPLETE',row['strategy'],row['year'],'GAPS',len(row['action_gaps']),flush=True)
    rows.sort(key=lambda r:(r['year'],r['strategy']));gaps=sorted({g for r in rows for g in r['action_gaps']})
    assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    assert common.health()[0]==protocol['market_health']
    common.dump(out/'SUMMARY.json',dict(status='verified' if not gaps else 'incomplete_action_coverage',end=protocol['end'],benchmark='CSI300 price index sh.000300',rows=rows,action_gaps=gaps,protected_unchanged=True))
    print('FINISHED','ACTION_GAPS',gaps,flush=True)


if __name__=='__main__':main()
