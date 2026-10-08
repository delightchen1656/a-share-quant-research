"""Daily regime-transition resizing of held stocks, high exposure floor, no empty pauses."""
import hashlib,itertools
import numpy as np
import pandas as pd
import research as r
import round09_affordability as base
import round08_long_momentum as signals
import execution_daily_overlay as engine
from round03 import calendar_dates

MODES=('fixed85','fixed95','trend60','trend120','dd60','dd120')
CONFIGS=[dict(id='Y%02d'%(i+1),family='carry_long',size='mid',cadence='bimonthly',interval=40,
    count=count,buffer=2*count,exposure=.85,power=0,minimum=1500,affordable=True,risk_mode=mode)
    for i,(mode,count) in enumerate(itertools.product(MODES,(8,12)))]

def exposures(close,mode):
    if mode.startswith('fixed'):return pd.Series(float(mode[-2:])/100,index=close.index)
    if mode.startswith('trend'):
        window=int(mode[5:]);known=close.shift(1)/close.rolling(window,min_periods=window).mean().shift(1)-1
        lower,upper=-.01,.01
    elif mode.startswith('dd'):
        window=int(mode[2:]);known=close.shift(1)/close.rolling(window,min_periods=window).max().shift(1)-1
        lower,upper=-.08,-.03
    else:raise ValueError(mode)
    state=.65;result=[]
    for value in known:
        if pd.notna(value):
            if value<lower:state=.65
            elif value>upper:state=.95
        result.append(state)
    return pd.Series(result,index=close.index)

class Study(base.Study):
    def __init__(self,configs,features=None):
        super().__init__(configs,features)
        close=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
        self.risk={mode:exposures(close,mode) for mode in MODES}
    def run(self,cfg,start,end=None,stress=False):
        e=r.e;end=min(r.END,start+pd.DateOffset(months=24)-pd.Timedelta(days=1)) if end is None else end
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.DELISTING_EVENTS=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.cost]
        dates=calendar_dates(self.cal,start,end,'monthly')
        dates=[d for d in dates if d==start or d.month%2==1]
        ranks={d:self.ranks[(cfg['family'],cfg['size'])][d].copy() for d in dates}
        for q in ranks.values():q['downside']=q.downside.pow(cfg['power'])
        risk=self.risk[cfg['risk_mode']]
        changed=risk.ne(risk.shift(1))&(risk.index>=start)&(risk.index<=end)
        resize={d:float(risk.loc[d]) for d in risk.index[changed] if d not in ranks}
        e.SELECTOR_CONTEXT=base.affordable_select
        try:curve,trades=e.simulate(ranks,.05,cfg['count'],cfg['buffer'],risk.to_dict(),1.5,self.panel,
            min_adjustment=cfg['minimum'],resize_targets=resize)
        finally:e.SELECTOR_CONTEXT=None
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        z=dict(**r.measure(curve,risk_free_annual=.02),**r.exposure(curve),start=str(start.date()),end=str(curve.date.iloc[-1].date()),
            fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),
            unresolved_actions=len(e.UNRESOLVED_ACTIONS),delisting_writeoffs=len(e.DELISTING_EVENTS),
            resize_signal_days=len(resize),resize_orders=int(trades.date.isin(resize).sum()))
        return z,curve,trades

def install():
    r.e=engine;r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round19_daily_risk';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='12 predeclared;carry_long mid,bimonthly8/12;fixed85/95 controls;priorCSI500 trend60/120 +/-1% hysteresis or60/120rolling drawdown -8/-3% hysteresis;65/95%targets;resize existing weights proportionately only on state transitions, no new symbols;normal selection unchanged;fees/minadjustment/limits unchanged',
            engine_sha256=hashlib.sha256((r.HERE/'execution_daily_overlay.py').read_bytes()).hexdigest(),
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
