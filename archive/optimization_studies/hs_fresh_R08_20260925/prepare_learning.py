"""Prepare past-only inputs and separately dated, matured training labels."""
import json
import numpy as np
import pandas as pd
import research as r

PATH=r.HERE/'features_learning_2019.parquet'
LABELED=r.HERE/'learning_labels.parquet'

def labels(close,calendar,horizon,out_date=None):
    mark=close.reindex(calendar).ffill()  # stale marking during suspension, never bfill
    future_date=pd.Series(calendar,index=calendar).shift(-horizon)
    target=mark.shift(-horizon)/mark-1
    if out_date is not None:
        terminal=(pd.Series(calendar,index=calendar)<out_date)&(future_date>=out_date)
        target.loc[terminal]=-1.  # conservative terminal loss, not survivor deletion
    return pd.DataFrame({'target'+str(horizon):target,'label_end'+str(horizon):future_date})

def main():
    if LABELED.exists():raise RuntimeError('Preserve completed labeled dataset')
    r.FEATURE_START='2019-01-01';r.MIN_SIGNAL_VOL=.001;r.FEATURES=PATH
    f=r.build_features()
    calendar=pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').date)).sort_values()
    u=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    exits={z['symbol']:pd.Timestamp(z['outDate']) for z in u.to_dict('records') if pd.notna(z['outDate'])}
    parts=[]
    for i,(symbol,rows) in enumerate(f.groupby('symbol')):
        q=pd.read_parquet(r.e.qfq_path(symbol),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        z=pd.concat([labels(q,calendar,h,exits.get(symbol)) for h in (5,20)],axis=1)
        z=z.reindex(pd.DatetimeIndex(rows.signal_date));z.index=rows.index;parts.append(z)
        if i%500==0:print('LABELS',i,flush=True)
    f=f.join(pd.concat(parts))
    for h in (5,20):assert (f['label_end'+str(h)].dropna()>f.loc[f['label_end'+str(h)].notna(),'signal_date']).all()
    f.to_parquet(LABELED,index=False)
    r.save(LABELED.with_suffix('.json'),dict(rows=len(f),start=str(f.execute_date.min()),end=str(f.execute_date.max()),
        purpose='Training only:future5/20sessionqfqclose returns,each with label_end. Never use a row for training until label_end strictly before model fit date.',
        warning='Labels are gross adjusted-close proxy,not realizable execution returns. Delisted terminal value0 and suspended prices stale-marked;execution remains cash/fees/raw-price ledger. Requires prefix and cutoff tests before training. No model trained yet.'))
    print('PREPARED',len(f),flush=True)

if __name__=='__main__':main()
