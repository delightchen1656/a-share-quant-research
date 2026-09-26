"""Quarterly historical-return clusters; not historical industry classifications."""
import hashlib
import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from threadpoolctl import threadpool_limits
import research as r
import round08_long_momentum as source

PATH=r.HERE/'features_return_clusters.parquet'

def fit_clusters(returns,date,symbols,k):
    past=returns.loc[returns.index<date,sorted(symbols)].tail(120)
    assert len(past)==120 and past.index.max()<date
    valid=(past.notna().sum()>=115)&(past.std()>1e-6)
    past=past.loc[:,valid].clip(-.2,.2)
    x=past.fillna(0.).to_numpy().T
    x=(x-x.mean(axis=1,keepdims=True))/x.std(axis=1,keepdims=True)
    with threadpool_limits(limits=1):
        m=MiniBatchKMeans(n_clusters=k,random_state=20260925,n_init=3,batch_size=256,max_iter=100)
        labels=m.fit_predict(x)
    return pd.Series(labels,index=past.columns),dict(max_input_date=str(past.index.max()),rows=len(past),symbols=past.shape[1],clusters=k)

def main():
    assert not PATH.exists(),'Preserve completed clusters'
    protocol=dict(groups=[8,16],lookback=120,min_observed=115,seed=20260925,
        method='Quarter first eligible execution date; contemporaneous eligible stock pool; strictly earlier returns; per-stock demean/std after clipping +/-20% and filling up to5missing returns0; MiniBatchKMeans3initializations,batch256,max100; quarter memberships fixed, new qualifying stocks wait until next quarter',
        warning='Statistical return groups,not historical industries. No strategy or performance proved.',
        implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
    r.save(r.HERE/'cluster_preparation_protocol.json',protocol)
    f=pd.read_parquet(source.FEATURES);parts=[]
    for i,s in enumerate(sorted(f.symbol.unique())):
        close=pd.read_parquet(r.e.qfq_path(s),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        parts.append(close.pct_change(fill_method=None).rename(s))
        if i%500==0:print('CLUSTER_RETURNS',i,flush=True)
    returns=pd.concat(parts,axis=1).sort_index()
    audits=[];labels=[]
    for quarter,rows in f.groupby(f.execute_date.dt.to_period('Q')):
        date=rows.execute_date.min();symbols=rows.loc[rows.execute_date==date,'symbol'].tolist()
        frame=pd.DataFrame(index=sorted(symbols))
        for k in (8,16):
            values,audit=fit_clusters(returns,date,symbols,k)
            frame['cluster'+str(k)]=values
            audits.append(dict(quarter=str(quarter),fit_date=str(date),**audit))
        frame.index.name='symbol';frame['quarter']=str(quarter);labels.append(frame.reset_index())
        print('CLUSTER_FIT',str(quarter),len(symbols),flush=True)
    f['quarter']=f.execute_date.dt.to_period('Q').astype(str)
    f=f.merge(pd.concat(labels,ignore_index=True),on=['symbol','quarter'],how='left',validate='many_to_one').drop(columns='quarter')
    f.to_parquet(PATH,index=False)
    r.save(r.HERE/'cluster_preparation_audit.json',dict(rows=len(f),audits=audits,missing_memberships=int(f.cluster8.isna().sum())))

if __name__=='__main__':main()
