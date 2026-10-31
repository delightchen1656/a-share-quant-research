"""Standalone inference semantics to be copied into the frozen audit package."""
import numpy as np
import pandas as pd


def base_features_and_pool(frame):
    from factor_functions import quotes_valid
    valid,num=quotes_valid(frame)
    logret=np.log1p(num.pctChg/100).where(valid)
    chain=logret.cumsum()
    amount=num.amount.where(valid)
    volume=num.volume.where(valid)
    turn=pd.to_numeric(frame.turn,errors='coerce').where(valid)
    median_amount=amount.rolling(20,min_periods=18).median()
    eligible=(valid&frame.isST.astype(str).eq('0')&num.close.ge(3)&valid.astype(int).cumsum().ge(120)&
              valid.rolling(20,min_periods=20).mean().ge(.9)&median_amount.ge(2e7))
    factor=pd.DataFrame(index=frame.index)
    for n in [20,60]:
        factor[f'quote_momentum{n}']=np.expm1(logret.rolling(n,min_periods=int(np.ceil(n*.9))).sum())
        factor[f'quote_volatility{n}']=logret.rolling(n,min_periods=int(np.ceil(n*.9))).std()
    factor['quote_reversal5']=-np.expm1(logret.rolling(5,min_periods=5).sum())
    factor['quote_reversal1']=-np.expm1(logret)
    factor['log_median_amount20']=np.log(median_amount)
    factor['volume_ratio5_20']=volume.rolling(5,min_periods=5).mean()/volume.rolling(20,min_periods=18).mean()
    factor['turnover_mean20']=turn.rolling(20,min_periods=18).mean()
    lo=chain.rolling(20,min_periods=18).min()
    hi=chain.rolling(20,min_periods=18).max()
    factor['quote_high_position20']=((chain-lo)/(hi-lo)).where(hi.gt(lo),.5)
    factor['quote_efficiency20']=logret.rolling(20,min_periods=18).sum().abs()/logret.abs().rolling(20,min_periods=18).sum()
    factor['last_quote_change']=np.expm1(logret)
    return factor.replace([np.inf,-np.inf],np.nan),eligible
