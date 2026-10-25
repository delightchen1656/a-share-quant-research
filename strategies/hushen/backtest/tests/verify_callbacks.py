"""Exercise actual platform callbacks, including history fetching; no cached-rank shortcut."""
from pathlib import Path
from types import SimpleNamespace as N
import ast,json,time,sys
import numpy as np
import pandas as pd
HOME=Path(__file__).resolve().parents[2]
REFERENCE=Path(__file__).resolve().parent/'reference'
rng=np.random.RandomState(812)
dates=pd.bdate_range('2018-01-01',periods=430)
raw={}
for i in range(180):
    symbol='600%03d.SH'%i
    close=(5+i/25)*np.exp(np.cumsum(rng.normal(0,.015,len(dates))))
    prev=np.r_[close[0],close[:-1]]
    x=pd.DataFrame(dict(open=prev*np.exp(rng.normal(0,.005,len(dates))),close=close,prev_close=prev,volume=3000000.,turnover=close*3000000,turnover_rate=1+i/80,is_paused=0.,is_st=0.),index=dates)
    if i==0:x=x.iloc[70:]
    if i==1:x=x.iloc[:350]
    if i==2:x.loc[dates[335:345],'is_st']=1
    if i==3:x.loc[dates[337:340],'is_paused']=1
    raw[symbol]=x
real = '--real' in sys.argv
if real:
    root=HOME.parents[1]
    dates=pd.DatetimeIndex(pd.read_parquet(HOME/'backtest/data/benchmark.parquet').date)
    dates=dates[dates<=pd.Timestamp('2026-09-30')][-390:]
    raw={}
    for f in sorted((root/'sh_sz_market_research/data_pipeline/data/raw').glob('*/*.parquet')):
        x=pd.read_parquet(f);x.date=pd.to_datetime(x.date);x=x.set_index('date')
        if not dates.isin(x.index).all():continue
        x=x.loc[dates].rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
        x['is_paused']=1-pd.to_numeric(x.tradestatus)
        raw[f.stem]=x[['open','close','prev_close','volume','turnover','turnover_rate','is_paused','is_st']].astype(float)
        if len(raw)==180:break
class Adapter:
    def __init__(self,file):
        self.ns={};exec(((HOME/'supermind_hushen_1.py' if file=='supermind_baseline2_D7f_fast_daily.py' else REFERENCE/file)).read_text(encoding='utf-8').replace('from mindgo_api import *',''),self.ns)
        self.calls=0;self.rows=0;self.universes=0;self.orders=[];self.i=320
        account=N(available_cash=100000.,frozen_cash=0.)
        self.context=N(portfolio=N(positions={},stock_account=account))
        self.ns.update(g=N(),log=N(info=lambda *a:None),get_datetime=lambda:dates[self.i],get_trade_days=lambda **k:dates[:self.i+1],get_all_securities=self.universe,history=self.history,get_open_orders=lambda:[],order=self.order,set_benchmark=lambda *a:None,set_commission=lambda *a:None,PerShare=lambda **k:k,set_slippage=lambda *a:None,PriceSlippage=lambda *a:a,set_volume_limit=lambda **k:None,enable_open_bar=lambda:None)
        self.ns['init'](self.context)
    def universe(self,*args,**kwargs):
        self.universes+=1;d=pd.Timestamp(kwargs['date'])
        return pd.DataFrame(index=[s for s,x in raw.items() if x.index[0]<=d<=x.index[-1]])
    def history(self,symbols,fields,count,*args):
        self.calls+=1
        result={s:raw[s].loc[raw[s].index<dates[self.i]].iloc[-count:][fields].copy() for s in symbols}
        self.rows+=sum(len(x) for x in result.values());return result
    def order(self,s,q,price):
        self.orders.append((str(dates[self.i]),s,q,price))
        # Reject some orders to exercise next-day residual retries.
        if self.i%11==0:return None
        positions=self.context.portfolio.positions;cash=self.context.portfolio.stock_account
        old=positions.get(s,N(amount=0,available_amount=0,last_price=price))
        cash.available_cash-=q*price+max(5,abs(q*price)*.0003)
        amount=old.amount+q
        if amount:positions[s]=N(amount=amount,available_amount=old.available_amount if q>0 else amount,last_price=price)
        elif s in positions:del positions[s]
        return N(order_id=str(len(self.orders)))
    def step(self,i):
        self.i=i
        for v in self.context.portfolio.positions.values():v.available_amount=v.amount
        self.ns['before_trading'](self.context)
        bars={s:N(open=float(x.loc[dates[i],'open']),high_limit=float(x.loc[dates[i],'prev_close']*1.1),low_limit=float(x.loc[dates[i],'prev_close']*.9),is_paused=bool(x.loc[dates[i],'is_paused']),is_st=bool(x.loc[dates[i],'is_st'])) for s,x in raw.items() if dates[i] in x.index}
        self.ns['handle_bar'](self.context,bars);self.ns['after_trading'](self.context)
        return dict(ranks=self.ns['g'].alpha_ranks,targets=self.ns['g'].alpha_targets,positions={s:v.amount for s,v in self.context.portfolio.positions.items()},cash=self.context.portfolio.stock_account.available_cash,orders=self.orders)
a=Adapter('supermind_baseline2_D7c_compatible_daily.py');b=Adapter('supermind_baseline2_D7f_fast_daily.py')
elapsed=[0.,0.]
for i in range(320,390):
    t=time.perf_counter();left=a.step(i);elapsed[0]+=time.perf_counter()-t
    t=time.perf_counter();right=b.step(i);elapsed[1]+=time.perf_counter()-t
    assert left==right,('callback parity',i)
    needed=set(left['positions'])|set(left['targets'])
    for s in needed:
        if s in a.ns['g'].alpha_info and s in b.ns['g'].alpha_info:
            av=a.ns['g'].alpha_info[s];bv=b.ns['g'].alpha_info[s]
            assert np.isclose(av['volume20'],bv['volume20']) and av['previous_st']==bv['previous_st']
funcs=lambda file:{n.name:ast.dump(n,include_attributes=False) for n in ast.parse(((HOME/'supermind_hushen_1.py' if file=='supermind_baseline2_D7f_fast_daily.py' else REFERENCE/file)).read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
af=funcs('supermind_baseline2_D7c_compatible_daily.py');bf=funcs('supermind_baseline2_D7f_fast_daily.py')
assert all(af[k]==bf[k] for k in af if k not in ('_before_trading','on_trade'))
result=dict(days=70,symbols=180,scenario='local real 180-symbol subset; mocked execution' if real else 'deterministic synthetic: listing,delisting,ST,pause,rejected orders',all_daily_ranks_targets_orders_positions_cash_equal=True,all_other_functions_AST_equal=True,old=dict(history_calls=a.calls,returned_rows=a.rows,universe_calls=a.universes,local_seconds=elapsed[0]),fast=dict(history_calls=b.calls,returned_rows=b.rows,universe_calls=b.universes,local_seconds=elapsed[1]),platform_runtime_measured=False)
(HOME/'results/latest'/('callback_real_validation.json' if real else 'callback_validation.json')).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
