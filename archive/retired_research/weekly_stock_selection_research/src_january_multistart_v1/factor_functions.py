import numpy as np
import pandas as pd

def quotes_valid(frame):
    num=frame[['open','high','low','close','volume','amount','preclose','pctChg']].apply(pd.to_numeric,errors='coerce')
    valid=frame.tradestatus.astype(str).eq('1')&np.isfinite(num).all(axis=1)&num.iloc[:,:7].gt(0).all(axis=1)&num.pctChg.gt(-100)
    return valid,num


def new_features(frame,market_lr):
    valid,num=quotes_valid(frame)
    lr=np.log1p(num.pctChg/100).where(valid)
    volume=num.volume.where(valid)
    amount=num.amount.where(valid)
    turn=pd.to_numeric(frame.turn,errors='coerce').where(valid)
    o,h,l,c,pre=[num[x].where(valid) for x in ['open','high','low','close','preclose']]
    span=h-l
    position=((c-l)/span).where(span.gt(0),.5).where(valid)
    range1=(h-l)/pre
    f=pd.DataFrame(index=frame.index)
    f['gap1']=o/pre-1
    f['intraday1']=c/o-1
    f['range1']=range1
    f['close_position1']=position
    f['upper_wick1']=((h-pd.concat([o,c],axis=1).max(axis=1))/span).where(span.gt(0),0.).where(valid)
    f['lower_wick1']=((pd.concat([o,c],axis=1).min(axis=1)-l)/span).where(span.gt(0),0.).where(valid)
    f['mean_close_position5']=position.rolling(5,min_periods=5).mean()
    f['range_expansion1_20']=range1/range1.rolling(20,min_periods=18).mean()
    for n in [3,10,120]:
        f[f'momentum{n}']=np.expm1(lr.rolling(n,min_periods=int(np.ceil(n*.9))).sum())
    f['acceleration5_20']=lr.rolling(5,min_periods=5).sum()-lr.rolling(20,min_periods=18).sum()/4
    f['volume_surprise1_20']=volume/volume.rolling(20,min_periods=18).mean()
    f['amount_surprise1_20']=amount/amount.rolling(20,min_periods=18).mean()
    f['turnover_ratio5_20']=turn.rolling(5,min_periods=5).mean()/turn.rolling(20,min_periods=18).mean()
    f['price_volume_corr20']=lr.rolling(20,min_periods=18).corr(np.log(volume).diff())
    f['downside_deviation20']=np.sqrt(lr.clip(upper=0).pow(2).rolling(20,min_periods=18).mean())
    f['max_up20']=lr.rolling(20,min_periods=18).max()
    f['max_down20']=-lr.rolling(20,min_periods=18).min()
    f['volatility_ratio5_20']=lr.rolling(5,min_periods=5).std()/lr.rolling(20,min_periods=18).std()
    market=market_lr.reindex(frame.index).where(valid)
    variance=market.rolling(60,min_periods=54).var()
    beta=lr.rolling(60,min_periods=54).cov(market)/variance
    f['beta60']=beta
    f['market_corr60']=lr.rolling(60,min_periods=54).corr(market)
    residual_variance=(lr.rolling(60,min_periods=54).var()-beta.pow(2)*variance).clip(lower=0)
    f['idiosyncratic_vol60']=np.sqrt(residual_variance)
    f['residual_momentum5']=lr.rolling(5,min_periods=5).sum()-beta*market.rolling(5,min_periods=5).sum()
    assert list(f.columns)==['gap1', 'intraday1', 'range1', 'close_position1', 'upper_wick1', 'lower_wick1', 'mean_close_position5', 'range_expansion1_20', 'momentum3', 'momentum10', 'momentum120', 'acceleration5_20', 'volume_surprise1_20', 'amount_surprise1_20', 'turnover_ratio5_20', 'price_volume_corr20', 'downside_deviation20', 'max_up20', 'max_down20', 'volatility_ratio5_20', 'beta60', 'market_corr60', 'idiosyncratic_vol60', 'residual_momentum5']
    return f.replace([np.inf,-np.inf],np.nan)
