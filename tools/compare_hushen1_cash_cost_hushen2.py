"""Controlled Hushen1 cash/cost adapter versus unchanged Hushen2. No fitting."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS
import argparse
import ast
import inspect
import json
import math
import pickle
import sys
import textwrap

import numpy as np
import pandas as pd

from replay_hushen2_local import ROOT, STRATEGY, APP, GAME, CASES, load, sha

H1=ROOT/'沪深1研究'
DATA=ROOT/'K线数据/沪深'
P2=ROOT/'archive/reports/holdout_restricted/hushen2_leader_pool/post2024_20261028_202602/INPUT_PACK.pkl'
G={}
FIELDS=['open','high','low','close','preclose','volume','amount','turn','tradestatus','isST','volume20','prev_actual','adjust_ratio']


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')


def health():
    sys.path.insert(0,str(APP/'tracker'));sys.path.insert(0,str(APP/'runtime'))
    m=load('comparison_market_health',APP/'tracker/market.py')
    h=m.health(APP/'tracker/data')
    assert not h['missing_models']
    return {k:h[k] for k in ('market_date','audit','audit_sha256')},[pd.Timestamp(d) for d in h['sessions']]


def prepare(out):
    h,calendar=health();end=pd.Timestamp(h['market_date'])
    with P2.open('rb') as f:p2=pickle.load(f)
    assert p2['end']==end,'Refresh unchanged baseline execution pack explicitly if committed endpoint changes'
    protected=[H1/'supermind_hushen_1.py',H1/'backtest/engine.py',H1/'backtest/ledger.py',H1/'backtest/actions.py',H1/'research/factors.py',
        H1/'research/protocol.json',H1/'results/latest/rankings_original.json',STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',P2]
    protected+=list((STRATEGY/'model').glob('*.txt'))
    protocol=dict(status='frozen_before_returns',scope='Q1 all starts;2020..2026 annual plus2020/2025/2026 continuous to current',end=str(end.date()),
        changes=['Hushen1 sell proceeds reusable next session only','One-side adverse slippage .002','Commission .0003 min5','Sell stamp .001 full period','No separate transfer fee'],
        unchanged=['Hushen1 four factors and eligibility','5names,98% exposure','20session rebalance and1.5buffer','Original100share cash-fit resizing','Previous20day mean-volume .005 cap and daily .25 cap','T+1','Dividend/share actions and dividend-tax algorithm','Hold unfinished rebalance targets','No artificial terminal liquidation or37dayentry cutoff added to Hushen1'],
        differences_not_unified=['Hushen2 remains5slots20%,fixedquantityIOC,2%dayvolume,7/30calendar,37dayterminalgate,originalexpiryclose','Hushen1 stock-price limit tick rounding retained','Hushen1 dividend tax preserved'],
        metrics='Both re-computed from daily closes:365/calendar span CAGR,ddof0 Sharpe252,rf0,negative peak drawdown; common SSE price benchmark',
        research_only=True,production_changed=False,retraining=False,market_health=h,protected_before={str(p):sha(p) for p in protected})
    dump(out/'PROTOCOL.json',protocol)
    factors=load('comparison_h1_factors',H1/'research/factors.py')
    entry=factors.mod(H1/'supermind_hushen_1.py','comparison_h1_entry')
    dates=pd.DatetimeIndex([d for d in calendar if pd.Timestamp('2018-01-02')<=d<=end])
    # Formal health calendar can stop at the current date; include all frozen historical sessions.
    dates=pd.DatetimeIndex(sorted(set(dates)|{d for d in p2['calendar'] if pd.Timestamp('2018-01-02')<=d<=end}))
    oldcal=pd.DatetimeIndex(pd.read_parquet(H1/'backtest/data/benchmark.parquet').date)
    assert oldcal.isin(dates).all()
    meta=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv',dtype=str).set_index('symbol')
    files=sorted((DATA/'raw').glob('*/*.parquet'));symbols=[p.stem for p in files]
    assert set(symbols)==set(meta.index)
    shape=(len(dates),len(symbols));arrays={}
    folder=out/'inputs';folder.mkdir(exist_ok=True)
    for k in FIELDS:
        arrays[k]=np.lib.format.open_memmap(folder/(k+'.npy'),mode='w+',dtype=np.float64,shape=shape)
        arrays[k][:]=np.nan
    present=np.lib.format.open_memmap(folder/'present.npy',mode='w+',dtype=bool,shape=shape);present[:]=False
    values={k:np.full(shape,np.nan,dtype=np.float32) for k in factors.FEATURES};eligible=np.zeros(shape,dtype=bool);inputs={}
    for j,path in enumerate(files):
        assert entry.mainboard(path.stem)
        inputs[str(path.relative_to(ROOT))]=sha(path)
        x=pd.read_parquet(path);x.date=pd.to_datetime(x.date)
        assert not x.date.duplicated().any()
        x=x.loc[x.date<=end].set_index('date').sort_index()[FIELDS[:10]].apply(pd.to_numeric,errors='raise')
        f,e,_=factors.features(x)
        row=meta.loc[path.stem]
        if pd.notna(row.ipoDate):e &= e.index>=pd.Timestamp(row.ipoDate)
        if pd.notna(row.outDate):e &= e.index<pd.Timestamp(row.outDate)
        for k in factors.FEATURES:values[k][:,j]=f[k].reindex(dates).to_numpy()
        eligible[:,j]=e.reindex(dates,fill_value=False).to_numpy()
        x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual
        ix=dates.get_indexer(x.index);ok=ix>=0;xx=x.iloc[np.flatnonzero(ok)];ix=ix[ok]
        for k in FIELDS:arrays[k][ix,j]=xx[k].to_numpy()
        present[ix,j]=True
        if (j+1)%600==0:print('H1_INPUT_FILES',j+1,len(files),flush=True)
    for a in arrays.values():a.flush()
    present.flush()
    ranked={k:pd.DataFrame(values[k],index=dates,columns=symbols).where(eligible).rank(axis=1,pct=True,method='average').astype(np.float32) for k in factors.FEATURES}
    score=sum(w*ranked[k] for w,k in zip([-.35,-.20,.25,-.20],factors.FEATURES)).rolling(5,min_periods=3).mean().astype(np.float32).where(eligible)
    ranks={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist() for d in dates if d>=pd.Timestamp('2019-12-20')}
    old=json.loads((H1/'results/latest/rankings_original.json').read_text(encoding='utf-8'))
    mismatch=[d for d in old if d in ranks and ranks[d]!=old[d]]
    dump(out/'RANKING_REGRESSION.json',dict(old_dates=len(old),compared_dates=sum(d in ranks for d in old),mismatches=mismatch))
    assert not mismatch,'Original ranking regression differs; inspect input vintage before account runs'
    dump(folder/'dates_symbols.json',dict(dates=[str(d.date()) for d in dates],symbols=symbols,
        outs={s:str(pd.Timestamp(a.outDate).date()) for s,a in meta.iterrows() if pd.notna(a.outDate)}))
    dump(out/'H1_RANKINGS.json',ranks);dump(out/'RAW_INPUT_HASHES.json',inputs)
    # Real provider response caches only; missing held stock-years are queried after a first-pass audit.
    responses={}
    for path in [H1/'backtest/data/actions_merged.json',H1/'results/latest/additional_actions.json']:
        responses.update(json.loads(path.read_text(encoding='utf-8')))
    dump(out/'ACTION_RESPONSES.json',responses)
    protocol.update(raw_hashes_file='RAW_INPUT_HASHES.json',raw_shape=shape,original_ranking_parity=True,ranking_dates=len(ranks))
    dump(out/'PROTOCOL.json',protocol)
    print('PREPARED',shape,'RANKINGS',len(ranks),'END',end,flush=True)


class Day:
    def __init__(self,market,i):self.market=market;self.i=i;self.cache={}
    def get(self,s,default=None):
        if s not in self.market.columns:return default
        if s not in self.cache:
            j=self.market.columns[s]
            self.cache[s]=None if not self.market.present[self.i,j] else NS(**{k:float(v[self.i,j]) for k,v in self.market.raw.items()})
        return self.cache[s] if self.cache[s] is not None else default
    def __contains__(self,s):return self.get(s) is not None
    def __getitem__(self,s):
        value=self.get(s)
        if value is None:raise KeyError(s)
        return value


class ActionBook:
    def __init__(self,out,p2):
        self.cache=json.loads((out/'ACTION_RESPONSES.json').read_text(encoding='utf-8'));self.lookup={};self.gaps=set()
        self.known=p2['known'];self.normalized=p2['actions']
        for path in (out/'actions').glob('*.json'):
            receipt=json.loads(path.read_text(encoding='utf-8'));assert receipt['error_code']=='0'
            self.cache[receipt['key']]=receipt['records']
    def ensure(self,s,date):
        key=s+'/'+str(date.year)
        if key not in self.cache:
            if key in self.known:
                a=self.normalized.get((date,s),[])
                assert len(a)<=1,(s,date,'multiple normalized actions require explicit provider receipt')
                return a[0] if a else None
            self.gaps.add(key);return None
        if key not in self.lookup:
            events={}
            for row in self.cache[key]:
                if not row.get('dividOperateDate'):continue
                d=pd.Timestamp(row['dividOperateDate']);num=lambda k:float(str(row.get(k,'')).strip() or 0)
                events[d]=dict(cash=num('dividCashPsBeforeTax'),stock=num('dividStocksPs')+num('dividReserveToStockPs'),taxable_stock=num('dividStocksPs'),
                    pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d))
            self.lookup[key]=events
        return self.lookup[key].get(date)


class Market:
    def __init__(self,out,p2):
        data=json.loads((out/'inputs/dates_symbols.json').read_text(encoding='utf-8'))
        self.dates=pd.DatetimeIndex(data['dates']);self.symbols=data['symbols'];self.columns={s:i for i,s in enumerate(self.symbols)}
        self.raw={k:np.load(out/'inputs'/(k+'.npy'),mmap_mode='r') for k in FIELDS}
        self.present=np.load(out/'inputs/present.npy',mmap_mode='r');self.outs={s:pd.Timestamp(d) for s,d in data['outs'].items()}
        self.actions=ActionBook(out,p2)
    @lru_cache(maxsize=3)
    def __getitem__(self,date):return Day(self,self.dates.get_loc(date))


def adapter(unified=True):
    e=load('cash_cost_h1_engine',H1/'backtest/engine.py')
    if not unified:return e
    # The repository already exposes this exact optional research scenario.
    # Use it without modifying the production entry/default scenario.
    policy=json.loads((H1/'backtest/cash_cost_policy.json').read_text(encoding='utf-8'))
    assert policy['sale_cash_next_session'] and policy['slippage_one_side']==.002
    assert policy['commission_rate']==.0003 and policy['minimum_commission']==5 and policy['sell_stamp_rate']==.001 and not policy['separate_transfer_fee']
    base_init=e.Account.__init__
    def initialize(self,start,market,**kwargs):
        base_init(self,start,market,scenario='unified_cash_cost',**kwargs)
        assert self.m.COUNT==5 and self.m.EXPOSURE==.98 and self.m.INTERVAL==20 and self.m.BUFFER==1.5 and self.m.PARTICIPATION==.005
        assert self.m.SLIP_ONE_SIDE==.002 and self.settle_sale_next_session
    e.Account.__init__=initialize
    return e


def initialize(out):
    out=Path(out)
    with P2.open('rb') as f:p2=pickle.load(f)
    G.update(out=out,p2=p2,market=Market(out,p2),ranks=json.loads((out/'H1_RANKINGS.json').read_text(encoding='utf-8')),
        engine=adapter(),risk=load('cash_cost_risk',STRATEGY/'backtest/compute_risk_metrics.py'))
    for path in (out/'actions').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));key=r['key'];symbol,year=key.split('/')
        if key in p2['known']:continue
        p2['known'].add(key)
        for row in r['records']:
            if not row.get('dividOperateDate'):continue
            d=pd.Timestamp(row['dividOperateDate']);num=lambda k:float(str(row.get(k,'')).strip() or 0)
            p2['actions'].setdefault((d,symbol),[]).append(dict(cash=num('dividCashPsBeforeTax'),stock=num('dividStocksPs')+num('dividReserveToStockPs'),taxable_stock=num('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d)))


def job_group(job):
    strategy,group,year,endpoint=job;end=pd.Timestamp(endpoint);market=G['market'];p2=G['p2'];out=G['out'];e=G['engine']
    dates=market.dates[(market.dates>=pd.Timestamp(f'{year}-01-01'))&(market.dates<=end)]
    starts=[d for d in dates if d.year==year and d.month<=3]
    records=[];curves=[];trades=[];gaps=set();issues={};references={}
    if strategy=='hushen2':
        core=load('comparison_h2_frozen_core',GAME/'runtime/run_batch.py');ad=load('comparison_h2_fixed',GAME/'runtime/baseline_fixed_ioc.py')
        core=ad.fixed_ioc_engine(core,manual_expiry_open=False,filled_slots=False)
    for i,start in enumerate(starts,1):
        if strategy=='hushen1_cash_cost':
            a=e.Account(start,market)
            for d in dates[dates>=start]:
                n=market.dates.get_loc(d)
                for s in list(a.holdings):
                    action=market.actions.ensure(s,d)
                    if action:a.actions[s,d]=action
                a.step(d,n,market.dates[n-1],G['ranks'])
                a.curve[-1]['holdings']=len(a.holdings)
            c=pd.DataFrame(a.curve);t=pd.DataFrame(a.trades)
            issues.update(a.issues);references.update(a.reference_diffs)
            buys=int(t.qty.gt(0).sum()) if len(t) else 0;sells=int(t.qty.lt(0).sum()) if len(t) else 0
            counts=dict(filled=buys,sells=sells,failed=sum(x['status']!='filled' for x in a.order_audit),take_count=None,stop_count=None,expiry_count=None,terminal_positions=len(a.holdings),deferred_cash=None,receivables_total=sum(v for _,v in a.receivables),total_cost=a.fees+a.tax)
            # Holdings and deferred proceeds remain part of NAV; never force an end liquidation.
            assert abs(c.equity.iloc[-1]-(a.cash+sum(p['qty']*p['last'] for p in a.holdings.values())+sum(v for _,v in a.receivables)))<1e-6
            assert t.transfer.eq(0).all()
            if len(t):assert np.allclose(t.loc[t.qty.lt(0),'stamp'],(t.loc[t.qty.lt(0),'qty'].abs()*t.loc[t.qty.lt(0),'price']*.001).round(2),atol=.011)
        else:
            core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end-pd.Timedelta(days=37);core.YEARS=[year]
            curve=[];missing=set()
            r,t=core.simulate(p2['signals'].loc[p2['signals'].date.between(start,core.LAST_SIGNAL_DATE)],p2['bars'],[d for d in p2['calendar'] if d<=end],
                'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,actions=p2['actions'],known_action_keys=p2['known'],coverage_sink=missing,delist_dates=p2['delists'],slots=5,equity_curve_sink=curve)
            c=pd.DataFrame(curve);attempts=pd.DataFrame(r['fixed_order_attempts']);gaps.update(missing)
            counts=dict(filled=r['filled_orders'],sells=len(t),failed=r['pending_orders_created']-r['filled_orders']-r['pending_orders_at_end'],take_count=int(t.reason.eq('take').sum()),stop_count=int(t.reason.eq('stop').sum()),expiry_count=int(t.reason.eq('expiry').sum()),terminal_positions=r['open_positions_at_end'],deferred_cash=0.,total_cost=float(t.entry_fee.sum()+t.exit_fee_and_tax.sum()))
            assert not r['open_positions_at_end'] and not r['pending_orders_at_end']
            assert abs(c.equity.iloc[-1]-100000-t.pnl.sum())<1e-6
        c['start_ordinal']=i;c['start_date']=start;t['start_ordinal']=i
        m=G['risk'].recompute_metrics(c).iloc[0].to_dict();last=pd.Timestamp(c.date.iloc[-1]);span=(last-start).days
        bm=(p2['index'].loc[last]/p2['index'].loc[start])**(365/span)-1
        m.update(**counts,annualized_excess=m['annualized_return']-bm,benchmark_annualized=float(bm),ending_equity=float(c.equity.iloc[-1]))
        records.append(m);curves.append(c);trades.append(t)
        if i%15==0:print('PATHS',strategy,group,i,len(starts),flush=True)
    if strategy=='hushen1_cash_cost':gaps.update(market.actions.gaps)
    folder=out/'runs'/group/strategy;folder.mkdir(parents=True,exist_ok=True)
    m=pd.DataFrame(records);m.to_parquet(folder/'START_METRICS.parquet',index=False)
    pd.concat(curves,ignore_index=True).to_parquet(folder/'EQUITY_CURVES.parquet',index=False)
    pd.concat(trades,ignore_index=True).to_parquet(folder/'TRADES.parquet',index=False)
    dump(folder/'DATA_FLAGS.json',dict(missing_action_keys=sorted(gaps),legacy_unexplained_actions=issues,legacy_action_reference_differences=references))
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0','ending_equity','filled','sells','failed','terminal_positions','total_cost']
    return dict(strategy=strategy,group=group,year=year,end=str(end.date()),starts=len(starts),**{k:float(m[k].mean()) for k in keys},
        cumulative_return_median=float(m.cumulative_return.median()),positive_fraction=float(m.cumulative_return.gt(0).mean()),beat_fraction=float(m.annualized_excess.gt(0).mean()),
        action_gaps=sorted(gaps),legacy_action_issues=len(issues),legacy_action_reference_differences=len(references))


def fetch(out):
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));gaps=summary['action_gaps']
    import baostock as bs
    assert bs.login().error_code=='0';(out/'actions').mkdir(exist_ok=True)
    try:
        for key in gaps:
            symbol,year=key.split('/');r=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');rows=[]
            while r.error_code=='0' and r.next():rows.append(dict(zip(r.fields,r.get_row_data())))
            assert r.error_code=='0'
            dump(out/'actions'/(key.replace('/','_')+'.json'),dict(key=key,error_code='0',records=rows,fetched_at=datetime.now().isoformat()))
            print('ACTION_RECEIPT',key,len(rows),flush=True)
    finally:bs.logout()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--resume',action='store_true');parser.add_argument('--fetch-gaps',action='store_true');parser.add_argument('--rerun-gaps-only',action='store_true');parser.add_argument('--workers',type=int,default=3);parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    out=(args.output or ROOT/'archive/reports/holdout_restricted/hushen1_cash_cost_vs_hushen2'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')).resolve();out.mkdir(parents=True,exist_ok=True);print('OUTPUT',out,flush=True)
    if not args.resume:prepare(out)
    if args.fetch_gaps:fetch(out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'));end=protocol['end']
    groups=[(str(y),y,f'{y}-12-31' if y<2026 else end) for y in range(2020,2027)]+[('2020_to_current',2020,end),('2025_to_current',2025,end)]
    if args.smoke:groups=groups[:1]
    jobs=[(v,g,y,d) for g,y,d in groups for v in ['hushen1_cash_cost','hushen2']]
    rows=[]
    if args.rerun_gaps_only:
        assert args.resume
        previous=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
        reused={(r['strategy'],r['group']):r for r in previous['rows'] if not r['action_gaps']}
        rows=list(reused.values())
        jobs=[j for j in jobs if (j[0],j[1]) not in reused]
        print('REUSE_COMPLETE_GROUPS',len(rows),'RERUN',len(jobs),flush=True)
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(out),)) as pool:
        for f in as_completed([pool.submit(job_group,j) for j in jobs]):
            row=f.result();rows.append(row);print('COMPLETE',row['strategy'],row['group'],'GAPS',len(row['action_gaps']),'ISSUES',row['legacy_action_issues'],flush=True)
    rows.sort(key=lambda r:(r['group'],r['strategy']));gaps=sorted({g for r in rows for g in r['action_gaps']})
    assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    assert health()[0]==protocol['market_health']
    dump(out/'SUMMARY.json',dict(status='complete_with_legacy_data_flags' if not gaps and any(r['legacy_action_issues'] or r['legacy_action_reference_differences'] for r in rows) else 'verified' if not gaps else 'incomplete_action_coverage',end=end,rows=rows,action_gaps=gaps,protected_unchanged=True,smoke_only=args.smoke,
        continuous_2026_alias='2026 annual cohort is exactly the same set of starts and endpoint as2026_to_current'))
    print('SUMMARY',out/'SUMMARY.json','GAPS',gaps,flush=True)


if __name__=='__main__':main()
