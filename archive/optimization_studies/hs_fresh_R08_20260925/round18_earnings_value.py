"""Exploratory earnings/free-float-cap proxy, NOT a true EP-factor replication."""
import hashlib,itertools
import research as r
from prepare_earnings_value import FEATURES
from round09_affordability import Study

CONFIGS=[dict(id='X%02d'%(i+1),family=family,size=size,cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=2*count,
    exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,size,cadence,count) in enumerate(itertools.product(
        ('earnings_proxy','quality_value','value_pullback'),('mid','large'),('monthly','bimonthly'),(8,12)))]

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    q=q[q.float_cap_proxy_group=={'mid':1,'large':2}[cfg['size']]].copy()
    h=lambda col:q[col].rank(pct=True).fillna(.5)
    value=h('earnings_float_proxy');low=1-h('vol60')
    quality=.4*h('fin_roe')+.3*h('fin_cash')+.3*h('fin_margin')
    if cfg['family']=='earnings_proxy':score=value
    elif cfg['family']=='quality_value':score=.5*value+.3*quality+.2*low
    elif cfg['family']=='value_pullback':score=.5*value+.3*(1-h('ret20'))+.2*low
    else:raise ValueError(cfg)
    q['score']=score
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round18_earnings_value';r.Study=Study

if __name__=='__main__':
    assert FEATURES.exists(),'Prepare date-aligned proxy first'
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='24 predeclared: earnings/freefloat-cap PROXY,quality-value,value-pullback xmid/large xmonthly/bimonthly x8/12; 85%equalweight and original transaction constraints',
            source_vintage_verification_required=True,
            valuation_warning='NOT real PE/EP; total-company profit divided by floating-cap estimate, floating share fractions can distort rankings; not a paper replication',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
