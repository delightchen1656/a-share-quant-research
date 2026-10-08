"""Broader historically eligible liquidity universes, unchanged transaction rules."""
import itertools,hashlib
import numpy as np
import research as r
import round08_long_momentum as long_signal
from round09_affordability import Study
from prepare_lower_liquidity import PATH

OriginalRank=r.rank
CONFIGS=[dict(id='U%02d'%(i+1),family=signal+'@'+str(amount),size=size,cadence='bimonthly',interval=40,
    count=count,buffer=2*count,exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(amount,size,signal,count) in enumerate(itertools.product((5,20,50),('small','mid'),('carry_long','defensive','liquidity'),(8,12)))]

def filter_universe(frame,amount):
    assert frame.execute_date.nunique()==1
    q=frame[frame.amount20>=amount*1e6].copy()
    q['float_cap_proxy_group']=np.minimum(np.floor(q.float_cap_proxy.rank(pct=True)*3),2).fillna(-1).astype(int)
    return q

def rank(frame,cfg):
    signal,amount=cfg['family'].split('@')
    q=filter_universe(frame,float(amount));settings=dict(cfg,family=signal)
    return long_signal.rank(q,settings) if signal=='carry_long' else OriginalRank(q,settings)

def install():
    r.FEATURES=PATH;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round13_liquidity_universe';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='36predeclaredconfigs:5/20/50million amount20 xsmall/mid xcarrylong/defensive/liquidity x8/12;size ranks recomputed AFTER liquidityfilter;85%equalweight,bimonthly,60pool,2xbuffer,lotaffordability;unchanged costs and5%dailyvolume proxy',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
