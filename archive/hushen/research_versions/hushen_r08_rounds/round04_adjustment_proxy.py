"""Historical price-adjustment proxies, not verified dividend fundamentals."""
import itertools,json
import numpy as np
import pandas as pd
import research as r
from round03 import calendar_dates

FEATURES=r.HERE/'features_historical_adjustment.parquet'
CONFIGS=[dict(id='D%02d'%(i+1),family=family,size=size,cadence=cadence,interval=20 if cadence=='monthly' else 40,
    count=count,buffer=count*2,exposure=.85,power=.5,minimum=1500)
    for i,(family,size,cadence,count) in enumerate(itertools.product(('carry','persistent','carry_trend'),('all','small','mid','large'),('monthly','bimonthly'),(8,12)))]

def adjustment_features(raw):
    close=pd.to_numeric(raw.close,errors='coerce');pre=pd.to_numeric(raw.preclose,errors='coerce')
    ratio=close.shift(1)/pre-1
    event=ratio.where(ratio.between(.0005,.08),0.)
    # Do not claim these are actual dividends: small rights/bonus actions may enter.
    proxy=event.clip(upper=.04).rolling(250,min_periods=250).sum()
    recent=event.rolling(250,min_periods=250).sum()
    persistence=((recent>0).astype(float)+(recent.shift(250)>0).astype(float)+(recent.shift(500)>0).astype(float))/3
    return pd.DataFrame(dict(distribution_proxy=proxy,persistence=persistence))

def build():
    if FEATURES.exists():return
    f=pd.read_parquet(r.HERE/'features_historical_lowvol.parquet');parts=[]
    for i,(symbol,rows) in enumerate(f.groupby('symbol')):
        raw=pd.read_parquet(r.e.raw_path(symbol),columns=['date','close','preclose']).sort_values('date').set_index('date')
        values=adjustment_features(raw).reindex(pd.DatetimeIndex(rows.signal_date));values.index=rows.index;parts.append(values)
        if i%500==0:print('ADJUSTMENT',i,flush=True)
    f=f.join(pd.concat(parts));assert (f.signal_date<f.execute_date).all()
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),definition='Raw previous close/preclose-1;positive0.05..8% events,capped4% each;250observation trailing sum;past3x250 windows eventpresence. Proxy not verified dividend yield;couldinclude small rights/bonus events. Same method covers historically delisted symbols. No trades or ledger cash inferred from this factor.'))

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    if cfg['size']!='all':q=q[q.float_cap_proxy_group=={'small':0,'mid':1,'large':2}[cfg['size']]].copy()
    q=q.dropna(subset=['distribution_proxy','persistence','vol60','turn20'])
    h=lambda col:q[col].rank(pct=True)
    if cfg['family']=='carry':q['score']=.5*h('distribution_proxy')+.3*(1-h('vol60'))+.2*(1-h('turn20'))
    elif cfg['family']=='persistent':q['score']=.5*h('persistence')+.3*h('distribution_proxy')+.2*(1-h('vol60'))
    elif cfg['family']=='carry_trend':q['score']=.5*h('distribution_proxy')+.25*h('near_high')+.25*(1-h('vol60'))
    else:raise ValueError(cfg)
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

OriginalStudy=r.Study
class Study(OriginalStudy):
    def __init__(self,configs,features=None):
        super().__init__(configs,features)
        self.dev=[self.cal[self.cal.get_loc(d)+n] for d in self.dev for n in (0,5,10)]
    def run(self,cfg,start,end=None,stress=False):
        e=r.e;end=min(r.END,start+pd.DateOffset(months=24)-pd.Timedelta(days=1)) if end is None else end
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.DELISTING_EVENTS=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.cost]
        dates=calendar_dates(self.cal,start,end,'monthly')
        if cfg['cadence']=='bimonthly':dates=[d for d in dates if d==start or d.month%2==1]
        ranks={d:self.ranks[(cfg['family'],cfg['size'])][d].copy() for d in dates}
        for q in ranks.values():q['downside']=q.downside.pow(cfg['power'])
        curve,trades=e.simulate(ranks,.05,cfg['count'],cfg['buffer'],cfg['exposure'],1.5,self.panel,min_adjustment=cfg['minimum'])
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        z=dict(**r.measure(curve,risk_free_annual=.02),**r.exposure(curve),start=str(start.date()),end=str(curve.date.iloc[-1].date()),fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS),delisting_writeoffs=len(e.DELISTING_EVENTS))
        return z,curve,trades

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.CONFIGS=CONFIGS;r.ROUND_NAME='round04_adjustment';r.rank=rank;r.Study=Study

if __name__=='__main__':
    build();install();original_save=r.save
    def save(path,obj):
        if path.name=='protocol.json':obj.update(method='Historical raw-price adjustment proxies,NOT verified dividend fundamentals;common monthly or odd-month rebalance,85%fixed,no cash timing',dev='24 starts2020/21quarter+0/5/10sessions,24months;existing screening thresholds and final target gates unchanged',configs=CONFIGS)
        original_save(path,obj)
    r.save=save;r.main()
