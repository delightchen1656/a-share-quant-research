"""Daily audited ledger and preregistered diagnostics. No intraday reconstruction."""
from pathlib import Path
from types import SimpleNamespace as NS
from functools import lru_cache
import json, math, sys
import numpy as np
import pandas as pd
import research as r

HERE=r.HERE;BASE=r.BASE;ENTRY=HERE/'supermind_baseline2_D7_daily.py'
FIELDS=['open','high','low','close','preclose','volume','amount','turn','tradestatus','isST','volume20','prev_actual','adjust_ratio']
engine=r.mod(BASE/'start_date_study/study.py','review_engine')
# The shared adapter's signal refresh must follow the actual strategy interval.
text=(BASE/'start_date_study/study.py').read_text(encoding='utf-8')
text=text.replace('if g.alpha_first or (index-1)%20==0:g.alpha_ranks=ranks[str(prev.date())]',
                  'if g.alpha_first or (index-1)%m.INTERVAL==0:g.alpha_ranks=ranks[str(prev.date())]')
exec(compile(text,str(BASE/'start_date_study/study.py'),'exec'),engine.__dict__)

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

class Market:
    def __init__(self):
        self.dates=pd.DatetimeIndex(pd.read_parquet(BASE/'start_date_study/benchmark.parquet').date)
        manifest=json.loads((HERE/'inputs.json').read_text(encoding='utf-8'))
        self.symbols=[x['symbol'] for x in manifest['files']];self.columns={s:i for i,s in enumerate(self.symbols)}
        shape=(len(self.dates),len(self.symbols));self.raw={k:np.full(shape,np.nan) for k in FIELDS};self.present=np.zeros(shape,dtype=bool)
        for n,record in enumerate(manifest['files']):
            path=r.DATA/'raw'/record['symbol'][-2:]/(record['symbol']+'.parquet')
            assert r.sha(path)==record['sha256']
            x=pd.read_parquet(path);x.date=pd.to_datetime(x.date);x=x.set_index('date').sort_index()
            x=x.loc[x.index<=r.Q['end'],FIELDS[:10]].apply(pd.to_numeric,errors='raise')
            x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual
            ix=self.dates.get_indexer(x.index);ok=ix>=0;ix=ix[ok];x=x.iloc[np.flatnonzero(ok)]
            for k in FIELDS:self.raw[k][ix,n]=x[k].to_numpy()
            self.present[ix,n]=True
        meta=pd.read_csv(r.DATA/'metadata/historical_mainboard_universe.csv')
        self.outs={a.symbol:pd.Timestamp(a.outDate) for a in meta.itertuples() if pd.notna(a.outDate)}
        actions=r.mod(BASE/'test2_controlled20/pipeline.py','action_utils')
        actions.HERE=HERE
        self.actions=actions.Actions(pd.Timestamp(r.Q['end']))
    @lru_cache(maxsize=3)
    def __getitem__(self,date):return Day(self,self.dates.get_loc(date))

class Account(engine.Account):
    def __init__(self,start,market,scenario='strict_daily_limits',initial=100000,control='original',params=None):
        self.scenario=scenario;self.market=market;self.order_audit=[];self.defer=False
        self.dividend_credits={}
        self.date=pd.Timestamp(start)
        entry=HERE/'uploaded_v5.py' if scenario=='original_daily_reference' else ENTRY
        engine.load_model=lambda k:engine.module(entry,'review_strategy')
        super().__init__('D11',start,{},market,market.outs,capacity_scale=.4 if scenario=='capacity_10pct' else 1.)
        self.cash=float(initial);self.day={};self.initial=float(initial)
        if scenario=='double_commission':self.m.COMMISSION_RATE=.0006;self.m.MIN_COMMISSION=10.
        for k,v in (params or {}).items():setattr(self.m,k,v)
        self.sync()
    def corporate(self):
        for s,p in self.holdings.items():
            action=self.actions.get((s,self.date))
            if action:self.dividend_credits[s]=self.dividend_credits.get(s,0.)+p['qty']*action['cash']
        super().corporate()
    def order(self,s,qty,price=None):
        row=self.day.get(s);b=self.bars.get(s);original_limit=price
        def reject(reason):
            self.order_audit.append(dict(date=str(self.date.date()),symbol=s,qty=qty,limit=original_limit,status=reason));return None
        if self.defer:return reject('one_session_delay')
        if row is None or row.tradestatus!=1 or row.volume<=0:return reject('not_tradable')
        if self.scenario!='original_daily_reference':
            if qty>0:
                if b.open>=b.high_limit-1e-8 or price<b.open-1e-8:return reject('buy_limit_not_marketable_at_open')
                proposed=min(price,b.open*1.001,row.high,b.high_limit)
                if proposed<max(row.low,b.low_limit)-1e-8:return reject('invalid_open_fill')
            else:
                if b.open<=b.low_limit+1e-8 or price>b.open+1e-8:return reject('sell_limit_not_marketable_at_open')
                proposed=max(price,b.open*.999,row.low,b.low_limit)
                if proposed>min(row.high,b.high_limit)+1e-8:return reject('invalid_open_fill')
            price=round(float(proposed),2)
            if qty>0 and price>original_limit+1e-8:return reject('buy_rounding_limit')
            if qty<0 and price<original_limit-1e-8:return reject('sell_rounding_limit')
        value=abs(qty)*price
        extra=round(max(10,value*.0006)-max(5,value*.0003),2) if self.scenario=='double_commission' else 0.
        before=len(self.trades)
        result=super().order(s,qty,price)
        if len(self.trades)>before:
            if extra:
                self.cash-=extra;self.fees+=extra;self.trades[-1]['commission']+=extra;self.sync()
            fill=self.trades[-1]
            if self.scenario!='original_daily_reference':
                assert (fill['price']<=original_limit+1e-8 if qty>0 else fill['price']>=original_limit-1e-8)
            self.order_audit.append(dict(date=str(self.date.date()),symbol=s,qty=qty,limit=original_limit,price=fill['price'],status='filled'))
        else:reject('cash_or_volume_cap')
        return result

def metrics(a,requested=None):
    q=pd.DataFrame(a.curve);t=pd.DataFrame(a.trades);nav=q.equity.to_numpy();ret=nav/np.r_[a.initial,nav[:-1]]-1
    return dict(requested_start=requested,actual_start=str(q.date.iloc[0].date()),end=str(q.date.iloc[-1].date()),initial_cash=a.initial,
        final_equity=float(nav[-1]),total_return=float(nav[-1]/a.initial-1),cagr=float((nav[-1]/a.initial)**(365.25/((q.date.iloc[-1]-q.date.iloc[0]).days+1))-1),
        max_drawdown=float((1-nav/np.maximum.accumulate(np.r_[a.initial,nav])[1:]).max()),sharpe=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)) if ret.std(ddof=1)>0 else None,
        trades=len(t),commission=float(t.commission.sum()) if len(t) else 0.,transfer=float(t.transfer.sum()) if len(t) else 0.,stamp=float(t.stamp.sum()) if len(t) else 0.,
        transaction_fees=a.fees,dividend_tax=a.tax,total_cost=a.fees+a.tax,final_cash=a.cash,average_exposure=float(q.exposure.mean()),
        unresolved_actions=len(a.issues),reference_differences=len(a.reference_diffs),rejected_orders=sum(x['status']!='filled' for x in a.order_audit))

def simulate(market,start,end,scenario='strict_daily_limits',control='original',initial=100000,params=None,save=None):
    ranks=json.loads((HERE/('rankings_'+control+'.json')).read_text(encoding='utf-8'))
    if scenario=='exclude_vendor_anomaly_symbols':ranks={k:[s for s in v if s not in r.BAD] for k,v in ranks.items()}
    sessions=market.dates[(market.dates>=start)&(market.dates<=end)]
    a=Account(sessions[0],market,scenario,initial,control,params)
    for d in sessions:
        i=market.dates.get_loc(d)
        for s in list(a.holdings):
            action=market.actions.ensure(s,d)
            if action:a.actions[s,d]=action
        a.defer=scenario=='one_session_order_delay' and (a.m.g.alpha_first or (i-1)%a.m.INTERVAL==0)
        a.step(d,i,market.dates[i-1],ranks)
        a.curve[-1]['holdings']=len(a.holdings)
    result=metrics(a,str(pd.Timestamp(start).date()));result.update(scenario=scenario,control=control,params=params)
    result['issues']=a.issues;result['reference']=a.reference_diffs
    if save:
        folder=HERE/'runs';folder.mkdir(exist_ok=True)
        pd.DataFrame(a.curve).to_parquet(folder/(save+'_equity.parquet'),index=False)
        pd.DataFrame(a.trades).to_parquet(folder/(save+'_trades.parquet'),index=False)
        r.dump('runs/'+save+'.json',result)
        r.dump('runs/'+save+'_orders.json',a.order_audit)
        contribution={s:float(v) for s,v in a.dividend_credits.items()}
        for trade in a.trades:
            s=trade['symbol'];cost=sum(trade[k] for k in ['commission','transfer','stamp','dividend_tax'])
            contribution[s]=contribution.get(s,0.)-trade['qty']*trade['price']-cost
        for s,p in a.holdings.items():contribution[s]=contribution.get(s,0.)+p['qty']*p['last']
        assert np.isclose(sum(contribution.values()),result['final_equity']-initial,atol=.02), (sum(contribution.values()),result['final_equity']-initial)
        r.dump('runs/'+save+'_contribution.json',dict(sorted(contribution.items(),key=lambda x:-x[1])))
    print('RUN',save,round(result['cagr'],4),round(result['max_drawdown'],4),'issues',len(a.issues),len(a.reference_diffs),flush=True)
    return result,a

def main():
    mode=sys.argv[1];market=Market()
    try:
        if mode=='main':
            results=[]
            for y in range(2020,2027):
                for month in (1,7):
                    start='%d-%02d-01'%(y,month)
                    result,_=simulate(market,start,r.Q['end'],save='start_'+start)
                    results.append(result)
                    r.dump('halfyear_results.json',results)
        elif mode=='diagnostics':
            results=[]
            for name in r.Q['stress_scenarios']:
                initial=500000 if name=='capital_500k' else 1000000 if name=='capital_1m' else 100000
                result,_=simulate(market,'2020-01-01',r.Q['end'],scenario=name,initial=initial,save='stress_'+name)
                results.append(result);r.dump('stress_results.json',results)
            stages=[('development','2019-01-01','2022-12-31'),('selection','2023-01-01','2023-12-31'),('confirmation','2024-01-01','2024-12-31'),('evaluation','2025-01-01',r.Q['end'])]
            rows=[]
            for stage,start,end in stages:
                for control in r.CONTROLS:
                    result,_=simulate(market,start,end,control=control,save=stage+'_'+control)
                    result['stage']=stage;rows.append(result);r.dump('control_results.json',rows)
            neighborhood=[]
            for name,values in [('COUNT',[4,6]),('INTERVAL',[15,25]),('BUFFER',[1.2,1.8])]:
                for value in values:
                    result,_=simulate(market,'2019-01-01','2022-12-31',params={name:value},save='neighbor_'+name+'_'+str(value))
                    neighborhood.append(result);r.dump('neighborhood_results.json',neighborhood)
        elif mode=='equal_horizon':
            rows=[]
            for request in json.loads((HERE/'requests.json').read_text(encoding='utf-8')):
                i=market.dates.get_loc(pd.Timestamp(request['actual']))
                if i+251>=len(market.dates):continue
                result,_=simulate(market,request['actual'],str(market.dates[i+251].date()),save='equal252_'+request['requested'])
                rows.append(result);r.dump('equal_horizon_results.json',rows)
    finally:market.actions.close()

if __name__=='__main__':main()
