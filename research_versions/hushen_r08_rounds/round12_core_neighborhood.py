"""Predeclared 15-point neighborhood, not a fine unrestricted weight search."""
import itertools,hashlib
import research as r
import round08_long_momentum as signals
from round09_affordability import Study

WEIGHTS={'mix334':(.3,.3,.4),'mix433':(.4,.3,.3),'mix532':(.5,.3,.2),'mix424':(.4,.2,.4),'mix442':(.4,.4,.2)}
CONFIGS=[dict(id='N%02d'%(i+1),family=family,size='mid',cadence='bimonthly',interval=40,
    count=count,buffer=2*count,exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,count) in enumerate(itertools.product(WEIGHTS,(10,12,14)))]

def rank(frame,cfg):
    assert frame.execute_date.nunique()==1
    q=frame.sort_values('symbol').copy();q=q[q.float_cap_proxy_group==1].copy()
    # Same eligibility as the original signal, including unused-field missingness.
    q=q.dropna(subset=['long_risk','market_adjusted','distribution_proxy','vol60','ret5','turn20'])
    a,b,c=WEIGHTS[cfg['family']]
    q['score']=a*q.distribution_proxy.rank(pct=True)+b*q.long_risk.rank(pct=True)+c*(1-q.vol60.rank(pct=True))
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round12_core_neighborhood';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='15predeclaredconfigs:5coarse weight sets x10/12/14stocks;mid,bimonthly,85%equalweight,affordablelot,60pool,2xbuffer. No post-result grid expansion.',weights=WEIGHTS,
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
