"""Past-only long horizon risk-adjusted and market-adjusted momentum."""
import itertools,hashlib
import numpy as np
import pandas as pd
import research as r
import round04 as base

FEATURES=r.HERE/'features_long_momentum.parquet'
CONFIGS=[dict(id='H%02d'%(i+1),family=family,size=size,cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=count*2,
    exposure=.85,power=.5,minimum=1500)
    for i,(family,size,cadence,count) in enumerate(itertools.product(
        ('long_risk','market_adjusted','carry_long'),('small','mid','large'),('monthly','bimonthly'),(8,12)))]

def long_features(close,market):
    close=close.reindex(market.index)
    a=np.log(close.where(close>0)).diff();b=np.log(market.where(market>0)).diff()
    va=a.rolling(252,min_periods=220).var();vb=b.rolling(252,min_periods=220).var()
    beta=a.rolling(252,min_periods=220).cov(b)/vb
    mom=a.rolling(232,min_periods=220).sum().shift(20)
    market_mom=b.rolling(232,min_periods=220).sum().shift(20)
    risk=va.shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232)
    residual_risk=(va-beta.pow(2)*vb).shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232)
    return pd.DataFrame(dict(long_risk=mom/risk,
        market_adjusted=(mom-beta.shift(20)*market_mom)/residual_risk))

def build():
    if FEATURES.exists():return
    f=pd.read_parquet(base.FEATURES);parts=[]
    market=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
    for i,(symbol,rows) in enumerate(f.groupby('symbol')):
        close=pd.read_parquet(r.e.qfq_path(symbol),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        z=long_features(close,market).reindex(pd.DatetimeIndex(rows.signal_date));z.index=rows.index;parts.append(z)
        if i%500==0:print('LONG_FEATURES',i,flush=True)
    f=f.join(pd.concat(parts));f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),definition='232log-return sum ending20sessions ago;252session variance/covariance ending20sessions ago,min220; market-adjusted subtracts lagged beta times CSI500 logmomentum; volatility floors1e-6; no future or current industry data',
        implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest()))

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    q=q[q.float_cap_proxy_group=={'small':0,'mid':1,'large':2}[cfg['size']]]
    q=q.dropna(subset=['long_risk','market_adjusted','distribution_proxy','vol60','ret5','turn20'])
    h=lambda col:q[col].rank(pct=True)
    if cfg['family']=='long_risk':q['score']=.6*h('long_risk')+.25*(1-h('vol60'))+.15*(1-h('ret5'))
    elif cfg['family']=='market_adjusted':q['score']=.6*h('market_adjusted')+.25*(1-h('vol60'))+.15*(1-h('turn20'))
    elif cfg['family']=='carry_long':q['score']=.4*h('distribution_proxy')+.3*h('long_risk')+.3*(1-h('vol60'))
    else:raise ValueError(cfg)
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round08_long_momentum';r.Study=base.Study

if __name__=='__main__':
    build();install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='36fixedconfigs:long risk/marketadjusted/carrylong x3historicalsizegroups xmonthly/bimonthly x8/12;85%exposure,power0.5,buffer2x',
            dev='24starts2020/21quarter+0/5/10sessions,24months; original screening and frozen validation',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
