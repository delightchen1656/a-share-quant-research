"""Quality/price combinations over historical mainboard, not dividend-only."""
import hashlib,itertools,json
import research as r
from prepare_complete_financials import FEATURES
from round09_affordability import Study

CONFIGS=[dict(id='W%02d'%(i+1),family=family,size=size,cadence='bimonthly',interval=40,
    count=count,buffer=2*count,exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,size,count) in enumerate(itertools.product(
        ('quality','quality_defensive','quality_long','quality_carry'),('small','mid','all'),(8,12)))]

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    if cfg['size']!='all':q=q[q.float_cap_proxy_group=={'small':0,'mid':1}[cfg['size']]].copy()
    h=lambda c:q[c].rank(pct=True).fillna(.5)
    quality=.4*h('fin_roe')+.3*h('fin_cash')+.3*h('fin_margin')
    low=1-h('vol60')
    if cfg['family']=='quality':score=quality
    elif cfg['family']=='quality_defensive':score=.5*quality+.3*low+.2*(1-h('turn20'))
    elif cfg['family']=='quality_long':score=.5*quality+.3*h('long_risk')+.2*low
    elif cfg['family']=='quality_carry':score=.4*quality+.35*h('distribution_proxy')+.25*low
    else:raise ValueError(cfg)
    q['score']=score
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round17_broad_quality';r.Study=Study

if __name__=='__main__':
    assert FEATURES.exists(),'Build and audit historical financials first'
    audit=json.loads(FEATURES.with_suffix('.json').read_text(encoding='utf-8'))
    assert audit['retired_report_symbols']==audit['retired_universe'],'Resolve retired coverage before exploratory testing'
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='24 predeclared4familiesx3sizesx8/12stocks;bimonthly85%equalweight; historical universe,20million liquidity;missingfinancialneutral;no presentday survival/industry filtering',
            source_vintage_verification_required=True,
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
