"""Past-only correlation-aware selection, fixed high exposure, no cash timing."""
import itertools,hashlib
import numpy as np
import pandas as pd
import research as r
import round04 as base

CONFIGS=[]
for size,cadence,count in itertools.product(('mid','all'),('monthly','bimonthly'),(8,12)):
    for strength,lookback in ((0,120),(1,120),(2,120),(1,250),(2,250)):
        CONFIGS.append(dict(id='G%02d'%(len(CONFIGS)+1),family='carry_trend',size=size,
            cadence=cadence,interval=20 if cadence=='monthly' else 40,count=count,
            buffer=2*count if strength==0 else 48,exposure=.85,power=0,minimum=1500,
            strength=strength,lookback=lookback))

def past_correlation(returns,date,symbols,lookback):
    past=returns.loc[returns.index<date,symbols].tail(lookback)
    assert len(past)==0 or past.index.max()<date
    corr=past.corr(min_periods=min(60,lookback)).reindex(index=symbols,columns=symbols)
    # Missing pair histories get conservative high correlation, not free diversification.
    a=corr.fillna(1.).clip(-1,1).to_numpy()*.75
    np.fill_diagonal(a,1.)
    return a

def diversified_selection(symbols,corr,held,count,strength):
    score=np.linspace(1.,0.,len(symbols))+.15*np.array([s in held for s in symbols])
    chosen=[]
    for _ in range(min(count,len(symbols))):
        utility=score.copy()
        if chosen:utility-=strength*corr[:,chosen].mean(axis=1)
        utility[chosen]=-np.inf
        chosen.append(int(np.argmax(utility)))
    return [symbols[i] for i in chosen]

class Study(base.Study):
    def __init__(self,configs,features=None):
        super().__init__(configs,features)
        symbols=sorted(set(self.panel.symbol));series=[]
        for s in symbols:
            q=pd.read_parquet(r.e.qfq_path(s),columns=['date','close']).sort_values('date').set_index('date').close
            series.append(q.astype(float).pct_change(fill_method=None).rename(s))
        self.returns=pd.concat(series,axis=1).sort_index();self.corr_cache={}
        print('CORRELATION_INPUTS',len(symbols),flush=True)

    def run(self,cfg,start,end=None,stress=False):
        def selector(date,ranked,positions,count,buffer):
            symbols=ranked.head(buffer).symbol.tolist()
            key=(date,tuple(symbols),cfg['lookback'])
            if key not in self.corr_cache:
                self.corr_cache[key]=past_correlation(self.returns,date,symbols,cfg['lookback'])
            return diversified_selection(symbols,self.corr_cache[key],positions,count,cfg['strength'])
        r.e.SELECTOR=selector if cfg['strength'] else None
        try:return super().run(cfg,start,end,stress)
        finally:r.e.SELECTOR=None

def install():
    r.FEATURES=base.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=base.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round07_diversification';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='40 fixed configs; past120/250session correlation shrunk25%towardidentity; missingpairs highcorr; greedy ordinalscore+0.15heldbonus-strength*mean_selected_corr;48candidates;no-correlation controls retain original2xbuffer;85%exposure equalweights',
            dev='24starts2020/21quarters+0/5/10sessions;24months; same screening/freeze/full gates',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
