"""User-fixed trading costs; Hushen1 open-price .2% fills, original cash reuse."""
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
from replay_hushen2_local import ROOT,sha

SOURCE=ROOT/'archive/reports/holdout_restricted/hushen1_cash_cost_vs_hushen2/attempt_20261028_213602'
BENCHMARK=ROOT/'archive/reports/holdout_restricted/hushen_original_q1_to_current_csi300/attempt_20261028_224317/CSI300_PRICE_INDEX.parquet'


def fee_only_engine():
    e=common.adapter(unified=False)
    original=e.Account.__init__
    def initialize(self,start,market,**kwargs):
        original(self,start,market,scenario='unified_cash_cost',**kwargs)
        # Only costs change: restore Hushen1's original credited-sale reuse.
        self.settle_sale_next_session=False
        assert self.m.SLIP_ONE_SIDE==.002 and self.no_transfer_fee and self.fixed_stamp_rate==.001
        assert self.commission_rate==.0003 and self.minimum_commission==5
        assert (self.m.COUNT,self.m.EXPOSURE,self.m.INTERVAL,self.m.BUFFER,self.m.PARTICIPATION)==(5,.98,20,1.5,.005)
    e.Account.__init__=initialize
    return e


def prepare(out):
    h,_=common.health();assert h['market_date']=='2026-10-28'
    original=json.loads((SOURCE/'PROTOCOL.json').read_text(encoding='utf-8'))
    protected={p:sha(Path(p)) for p in original['protected_before']}
    for path in [BENCHMARK,SOURCE/'SUMMARY.json',common.H1/'backtest/cash_cost_policy.json']:
        protected[str(path)]=sha(path)
    protocol=dict(status='frozen_before_results',scope='2020..2026 annual,Q1 full starts to same-year end,2026 to current;2020/2026 Q1 full starts continuously to current',
        end=h['market_date'],market_health=h,
        fixed_costs=dict(slippage_one_side=.002,commission_rate=.0003,minimum_commission=5,sell_stamp_rate=.001,separate_transfer_fee=False),
        hushen1_fill='Rebalance fills use same-day open*(1+.002) buy/open*(1-.002) sell,original price tick rounding,daily traded range and order/exchange limit checks. Unfinished targets continue on original subsequent-session process,with same configured .002 costs.',
        hushen1_unchanged=['Original factors and daily ranking','Target5names98% exposure (not hard5slot cap)','20session rebalance,1.5buffer','Credited sale proceeds reusable same session','Original100share cash-fit loop and volume restrictions','Original T+1/corporate actions/dividend-tax algorithm','No terminal forced liquidation or new37day entry blackout'],
        hushen2_unchanged='Current original-top3 ATR025,no refill,5slots20%,fixedIOC,2%dayvolume,7/30calendar,sales next session,expiryclose,37dayterminalgate',
        benchmark='CSI300 price index sh.000300; excess is account CAGR minus index CAGR for each identical start',
        stats='Means of individual Q1-start paths;365calendar-span CAGR;daily Sharpe252,ddof0,rf0;negative peak drawdown',
        production_changed=False,no_retraining=True,protected_before=protected,input_source=str(SOURCE))
    common.dump(out/'PROTOCOL.json',protocol)
    shutil.copy2(BENCHMARK,out/'CSI300_PRICE_INDEX.parquet')
    assert sha(BENCHMARK)==sha(out/'CSI300_PRICE_INDEX.parquet')


def initialize(out):
    common.initialize(str(SOURCE));out=Path(out)
    common.G['out']=out;common.G['engine']=fee_only_engine()
    index=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet')
    common.G['p2']['index']=pd.Series(pd.to_numeric(index.close).to_numpy(),index=pd.to_datetime(index.date))
    for path in (out/'actions').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));assert r['error_code']=='0'
        common.G['market'].actions.cache[r['key']]=r['records']
    source=inspect.getsource(common.job_group)
    assert source.count("strategy=='hushen1_cash_cost'")==2
    source=source.replace("strategy=='hushen1_cash_cost'","strategy=='hushen1_cost_only_open'")
    exec(compile(source,'<hushen1-original-cash-fixed-costs-only>','exec'),common.__dict__)


def run(job):return common.job_group(job)


def reuse_h2(out,group):
    source=SOURCE/'runs'/group/'hushen2';target=out/'runs'/group/'hushen2';target.mkdir(parents=True,exist_ok=True)
    for name in ['EQUITY_CURVES.parquet','TRADES.parquet','DATA_FLAGS.json']:
        shutil.copy2(source/name,target/name);assert sha(source/name)==sha(target/name)
    m=pd.read_parquet(source/'START_METRICS.parquet')
    index=pd.read_parquet(out/'CSI300_PRICE_INDEX.parquet');s=pd.Series(pd.to_numeric(index.close).to_numpy(),index=pd.to_datetime(index.date))
    m['benchmark_annualized']=[(s.loc[pd.Timestamp(r.end_date)]/s.loc[pd.Timestamp(r.start_date)])**(365/r.calendar_day_span)-1 for r in m.itertuples()]
    m['annualized_excess']=m.annualized_return-m.benchmark_annualized
    m.to_parquet(target/'START_METRICS.parquet',index=False)
    old=json.loads((SOURCE/'SUMMARY.json').read_text(encoding='utf-8'))
    r=next(dict(r) for r in old['rows'] if r['group']==group and r['strategy']=='hushen2')
    r.update(annualized_excess=float(m.annualized_excess.mean()),benchmark_only_recomputed=True,account_paths_reused_from=str(source))
    return r


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--resume',action='store_true');parser.add_argument('--fetch-gaps',action='store_true');parser.add_argument('--workers',type=int,default=3);args=parser.parse_args()
    out=(args.output or ROOT/'archive/reports/holdout_restricted/hushen_cost_open_annual_csi300'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')).resolve();out.mkdir(parents=True,exist_ok=True)
    print('OUTPUT',out,flush=True)
    if not args.resume:prepare(out)
    if args.fetch_gaps:common.fetch(out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'));end=protocol['end']
    groups=[(str(y),y,f'{y}-12-31' if y<2026 else end) for y in range(2020,2027)]+[('2020_to_current',2020,end)]
    existing={}
    if args.resume and (out/'SUMMARY.json').exists():
        existing={(r['group'],r['strategy']):r for r in json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))['rows'] if not r['action_gaps']}
    rows=list(existing.values());jobs=[]
    for g,y,d in groups:
        if (g,'hushen2') not in existing:rows.append(reuse_h2(out,g))
        if (g,'hushen1_cost_only_open') not in existing:jobs.append(('hushen1_cost_only_open',g,y,d))
    print('REUSED',len(rows),'RUN_GROUPS',len(jobs),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(out),)) as pool:
        for f in as_completed([pool.submit(run,j) for j in jobs]):
            row=f.result();rows.append(row);print('COMPLETE',row['group'],'GAPS',row['action_gaps'],flush=True)
    rows.sort(key=lambda r:(r['group'],r['strategy']));gaps=sorted({g for r in rows for g in r['action_gaps']})
    assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    assert common.health()[0]==protocol['market_health']
    common.dump(out/'SUMMARY.json',dict(status='verified' if not gaps else 'incomplete_action_coverage',end=end,rows=rows,action_gaps=gaps,protected_unchanged=True,continuous2026_alias='2026 annual is identical to2026_to_current'))
    print('DONE','GAPS',gaps,flush=True)


if __name__=='__main__':main()
