"""Equal target weights plus budget-aware lot selection; old behavior is control."""
import itertools,hashlib
import numpy as np
import research as r
import round04 as base
import round08_long_momentum as signals

CONFIGS=[dict(id='J%02d'%(i+1),family=family,size=size,cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=count*2,
    exposure=.85,power=0,minimum=1500,affordable=affordable)
    for i,(family,size,cadence,count,affordable) in enumerate(itertools.product(
        ('long_risk','carry_long'),('mid','large'),('monthly','bimonthly'),(8,12),(False,True)))]

def affordable_select(date,ranked,positions,count,buffer,context):
    budget=max(0.,context['equity']*context['exposure']/count)
    retain=[s for s in positions if s in set(ranked.head(buffer).symbol)]
    ordered=retain+[s for s in ranked.symbol if s not in retain]
    selected=[]
    for s in ordered:
        price=context['prices'].get(s,np.nan)
        if not np.isfinite(price) or price<=0:continue
        value=price*context['lot']*(1+context['slippage'])
        fee=max(context['min_commission'],context['commission']*value)
        if value+fee>budget:continue
        selected.append(s)
        if len(selected)==count:break
    return selected

class Study(base.Study):
    def __init__(self,configs,features=None):
        # Candidate pool60 is distinct from the old-holding retention buffer.
        super().__init__([dict(c,buffer=max(60,c['buffer'])) for c in configs],features)
    def run(self,cfg,start,end=None,stress=False):
        r.e.SELECTOR_CONTEXT=affordable_select if cfg['affordable'] else None
        try:return super().run(cfg,start,end,stress)
        finally:r.e.SELECTOR_CONTEXT=None

def install():
    r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round09_affordability';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='32fixedconfigs;equalweights85%;2signalsx2sizesx2cadencesx2countsxlotbudgeton/off;60candidatepool,original2xretentionbuffer;one lot plusfee/slippage<=current open NAV*.85/count; no high/low/close/volume in selector context',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest(),
            execution_sha256=hashlib.sha256((r.HERE/'execution.py').read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
