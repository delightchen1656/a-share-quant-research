"""Historical statistical return-group rotation with affordable equal lots."""
import itertools,hashlib
import pandas as pd
import research as r
from prepare_clusters import PATH
from round09_affordability import Study

CONFIGS=[dict(id='K%02d'%(i+1),family=str(k)+'_'+style,size=size,cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=count*2,
    exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(k,style,size,cadence,count) in enumerate(itertools.product(
        (8,16),('strong','pullback','cold'),('all','mid'),('monthly','bimonthly'),(8,12)))]

def rank(frame,cfg):
    assert frame.execute_date.nunique()==1,'Never mix dates into cross-sectional ranks'
    k,style=cfg['family'].split('_');group='cluster'+k
    q=frame.sort_values('symbol').copy()
    if cfg['size']=='mid':q=q[q.float_cap_proxy_group==1].copy()
    q=q.dropna(subset=[group,'mom','near_high','ret20','vol60','distribution_proxy','long_risk'])
    counts=q.groupby(group).size();q=q[q[group].isin(counts[counts>=20].index)].copy()
    g=q.groupby(group)[['mom','near_high','ret20','vol60']].mean()
    h=lambda col:g[col].rank(pct=True)
    if style=='strong':g['score']=.6*h('mom')+.4*h('near_high')
    elif style=='pullback':g['score']=.6*h('mom')+.4*(1-h('ret20'))
    elif style=='cold':g['score']=.6*(1-h('ret20'))+.4*(1-h('vol60'))
    else:raise ValueError(cfg)
    g=g.reset_index().sort_values(['score',group],ascending=[False,True]).head(3)
    priority={c:i for i,c in enumerate(g[group])}
    # Per-stock score fixed to carry+long risk momentum+low volatility.
    q['score']=.4*q.distribution_proxy.rank(pct=True)+.3*q.long_risk.rank(pct=True)+.3*(1-q.vol60.rank(pct=True))
    q=q[q[group].isin(priority)].sort_values(['score','symbol'],ascending=[False,True])
    q['ordinal']=q.groupby(group).cumcount();q['group_priority']=q[group].map(priority)
    # Initial ranking interleaves groups. Retention/affordability can change actual weights.
    return q.sort_values(['ordinal','group_priority']).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=PATH;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round10_cluster_rotation';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='48fixed configs:8/16past-return clusters xstrong/pullback/cold xall/mid xmonthly/bimonthly x8/12;85%equalweights with affordablelot option;minimum20currenteligible members/group;top3groups interleaved,60candidatepool,2xretention;no hard groupweight cap',
            group_training=str(r.HERE/'cluster_preparation_protocol.json'),
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
