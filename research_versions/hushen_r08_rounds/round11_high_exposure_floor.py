"""Fixed stock selection with high-floor, lagged market-risk exposure."""
import itertools,hashlib
import numpy as np
import pandas as pd
import research as r
import round09_affordability as base
import round08_long_momentum as signals

MODES=('fixed85','fixed95','trend60','trend65','vol12','vol16')
CONFIGS=[dict(id='R%02d'%(i+1),family='carry_long',size='mid',cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=count*2,
    exposure=.85,power=0,minimum=1500,affordable=True,risk_mode=mode)
    for i,(mode,cadence,count) in enumerate(itertools.product(MODES,('monthly','bimonthly'),(8,12)))]

def risk_exposures(close,mode):
    if mode.startswith('fixed'):return pd.Series(int(mode[-2:])/100,index=close.index)
    if mode.startswith('trend'):
        floor=int(mode[-2:])/100
        known=close.shift(1);ma=close.rolling(120,min_periods=120).mean().shift(1)
        return pd.Series(np.where(known>ma,.95,floor),index=close.index)
    if mode.startswith('vol'):
        vol=close.pct_change(fill_method=None).rolling(60,min_periods=60).std().shift(1)*np.sqrt(250)
        return (int(mode[-2:])/100/vol).clip(.60,.95).fillna(.60)
    raise ValueError(mode)

class Study(base.Study):
    def __init__(self,configs,features=None):
        super().__init__(configs,features)
        close=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
        self.exposures={mode:risk_exposures(close,mode).to_dict() for mode in MODES}
    def run(self,cfg,start,end=None,stress=False):
        return super().run(dict(cfg,exposure=self.exposures[cfg['risk_mode']]),start,end,stress)

def install():
    r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round11_high_floor';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='24fixedconfigs;carry_long mid equalweight constant scoring;fixed85/95 controls;priorclose>prior120MA =>95% else60/65%;or12/16% divided by prior60day CSI500vol clipped60..95%; exposure only updates at normal rebalance; no cashpause;8/12 monthly/bimonthly;lot affordability follows actual targetbudget',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
