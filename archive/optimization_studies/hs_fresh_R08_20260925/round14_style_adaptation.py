"""Past style basket signals drive current stocks; execution remains fully separate."""
import itertools,hashlib
import numpy as np
import pandas as pd
import research as r
from prepare_style_history import RANKS,INDICES
from round09_affordability import Study

FEATURES=r.HERE/'features_style_meta.parquet'
FAMILIES=['fixedcarry']+[method+str(window)+'_'+str(top) for method,window,top in itertools.product(('momentum','risk'),(126,252),(1,2))]
CONFIGS=[dict(id='S%02d'%(i+1),family=family,size='all',cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=2*count,
    exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,cadence,count) in enumerate(itertools.product(FAMILIES,('monthly','bimonthly'),(8,12)))]

def lagged_scores(index_returns):
    result={}
    for window in (126,252):
        mean=index_returns.rolling(window,min_periods=126).mean()
        vol=index_returns.rolling(window,min_periods=126).std()
        result['risk'+str(window)]=(mean/vol*np.sqrt(250)).shift(1)
        result['momentum'+str(window)]=np.expm1(np.log1p(index_returns).rolling(window,min_periods=126).sum()).shift(1)
    return pd.DataFrame(result).replace([np.inf,-np.inf],np.nan)

def build():
    if FEATURES.exists():return
    assert RANKS.exists() and INDICES.exists(),'Prepare audited style history first'
    prices=pd.read_parquet(INDICES);scores=[]
    for style,q in prices.groupby('style'):
        z=lagged_scores(q.set_index('date').index_return).reset_index().rename(columns={'date':'execute_date'})
        z['style']=style;scores.append(z)
    ranked=pd.read_parquet(RANKS)
    ranked['ordinal']=ranked.groupby(['execute_date','style']).cumcount()
    f=ranked.merge(pd.concat(scores,ignore_index=True),on=['execute_date','style'],how='left',validate='many_to_one')
    f=f[f.execute_date>=pd.Timestamp('2020-01-02')]
    assert f[['risk126','risk252','momentum126','momentum252']].notna().all().all()
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),scores='Prior-day 126/252session style momentum or mean/std risk score;minimum126observations;not account Sharpe',
        rank_sha256=hashlib.sha256(RANKS.read_bytes()).hexdigest(),index_sha256=hashlib.sha256(INDICES.read_bytes()).hexdigest()))

def rank(frame,cfg):
    assert frame.execute_date.nunique()==1
    if cfg['family']=='fixedcarry':chosen=['carry_mid']
    else:
        score,top=cfg['family'].split('_')
        chosen=frame[['style',score]].drop_duplicates('style').sort_values([score,'style'],ascending=[False,True]).head(int(top))['style'].tolist()
    priority={s:i for i,s in enumerate(chosen)}
    q=frame[frame['style'].isin(chosen)].copy();q['priority']=q['style'].map(priority)
    q=q.sort_values(['ordinal','priority','symbol']).drop_duplicates('symbol')
    return q.head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round14_style_adaptation';r.Study=Study

if __name__=='__main__':
    build();install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='36fixedconfigs:fixedcarry control or prior-day126/252momentum/risk style score,top1/2styles interleaved;monthly/bimonthly,8/12stocks,85%equalweights,affordablelots. Style indices are gross price signals,NOT account NAV. Top2interleaving+retention does not guarantee50/50styleweights.',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
