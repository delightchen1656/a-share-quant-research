"""Pre-2020 disclosed fund holdings universe; not present-day index constituents."""
import hashlib,itertools,json
import pandas as pd
import research as r
from prepare_lower_liquidity import PATH as SOURCE
from round09_affordability import Study

HOLDINGS=r.HERE/'public_sources/dividend_holdings_2019.json'
FEATURES=r.HERE/'features_historical_dividend.parquet'
OriginalRank=r.rank
CONFIGS=[dict(id='V%02d'%(i+1),family=family,size='all',cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=2*count,
    exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,cadence,count) in enumerate(itertools.product(
        ('defensive','barbell','lowvol_reversal','carry_long'),('monthly','bimonthly'),(8,12,20)))]

def build():
    if FEATURES.exists():return
    source=json.loads(HOLDINGS.read_text(encoding='utf-8'))
    assert pd.Timestamp(source['published'])<pd.Timestamp('2020-01-01')
    symbols={x['symbol'] for x in source['rows']}
    assert len(symbols)==98 and all(r.e.is_ordinary_mainboard_a(x) for x in symbols)
    missing=[s for s in symbols if not r.e.raw_path(s).exists() or not r.e.qfq_path(s).exists()]
    assert not missing,missing
    f=pd.read_parquet(SOURCE);f=f[f.symbol.isin(symbols)].copy()
    assert (f.signal_date>=pd.Timestamp(source['published'])).all()
    assert (f.signal_date<f.execute_date).all()
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),symbols=f.symbol.nunique(),
        holdings_sha256=hashlib.sha256(HOLDINGS.read_bytes()).hexdigest(),
        features_source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        published=source['published'],missing_files=missing,
        universe='fixed 98 index-investment positions disclosed August2019; historical eligibility each date, no present-day survival filter; 5million amount floor; fund holdings, NOT exact index constituent membership',
        omitted_from_eligible_features=sorted(symbols-set(f.symbol))))

def rank(frame,cfg):
    if cfg['family']!='carry_long':return OriginalRank(frame,cfg)
    q=frame.sort_values('symbol').dropna(subset=['distribution_proxy','long_risk','vol60']).copy()
    h=lambda col:q[col].rank(pct=True)
    q['score']=.4*h('distribution_proxy')+.3*h('long_risk')+.3*(1-h('vol60'))
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round15_historical_dividend';r.Study=Study

if __name__=='__main__':
    build();install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='24 predeclared:4 signals xmonthly/bimonthly x8/12/20; fixed2019 disclosed98holdings;85%equalweight,60pool,2xbuffer,affordability; no present-day membership or exclusion of later delistings',
            source_sha256=hashlib.sha256(HOLDINGS.read_bytes()).hexdigest(),
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
