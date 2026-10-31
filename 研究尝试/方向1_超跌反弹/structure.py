"""Frozen direction1 signal functions, no fitting or search."""
import numpy as np
import pandas as pd
from decimal import Decimal,ROUND_HALF_UP

def scan(q, r):
    """All feature windows are trailing. Returned candidates have no future fields."""
    valid = (pd.to_numeric(r.tradestatus) == 1) & (r.volume > 0) & (r.open > 0)
    q = q.loc[valid].reset_index(drop=True)
    r = r.loc[valid].reset_index(drop=True)
    c, h, l = q.close, q.high, q.low
    span = (r.high-r.low).replace(0, np.nan)
    f = pd.DataFrame({'date': q.date})
    f['ret20'] = c.shift(1)/c.shift(21)-1
    f['ret5'] = c.shift(1)/c.shift(6)-1
    f['below_ma20'] = c/c.rolling(20).mean()-1
    f['below_ma60'] = c/c.rolling(60).mean()-1
    f['low_recent'] = l.rolling(3).min()/l.rolling(20).min()-1
    f['rebound_from_low'] = c/l.rolling(3).min()-1
    f['body'] = (r.close-r.open)/span
    f['upper'] = (r.high-r.close)/span
    f['lower'] = (r.open.where(r.open < r.close, r.close)-r.low)/span
    f['volume_ratio'] = r.volume/r.volume.shift(1).rolling(20).mean()
    f['last3_volume_ratio'] = r.volume.shift(1).rolling(3).mean()/r.volume.shift(4).rolling(10).mean()
    f['close_over_prev_high'] = c/h.shift(1)-1
    # Simple prespecified visual prototype, not thresholds chosen by future outcome.
    base = ((f.ret20 <= -.15) & (f.ret5 <= -.08) &
            (f.below_ma20 < 0) & (f.below_ma60 < 0) &
            (f.low_recent <= .02) & (f.rebound_from_low <= .12) &
            (r.close > r.open) & (f.body >= .40) & (f.upper <= .30))
    f['candidate'] = base.fillna(False)
    f['q_position'] = np.arange(len(q))
    return f, q, r

def independent(mask):
    """First qualifying signal in each 10-observed-session cooldown, before labels."""
    keep = []
    last = -100
    for i in np.flatnonzero(np.asarray(mask)):
        if i-last >= 10:
            keep.append(i)
            last = i
    return keep

def limit_flags(raw):
    """Conservative inferred historical limits, not exchange official limit-price data.

    Only 2018-2024 mainboard data: regular 10%, historical ST 5%.
    Exemptions/relisting periods cannot be exhaustively identified in this snapshot.
    Below-theoretical-limit bars are also flagged conservatively rather than allowed.
    """
    r=raw.copy()
    good=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)&(r.preclose>0)
    r=r.loc[good].reset_index(drop=True)
    st=pd.to_numeric(r.isST,errors='coerce')
    if st.isna().any():raise ValueError('Unknown historical ST state')
    prices=np.array([float((Decimal(str(p))*(Decimal('.95') if s==1 else Decimal('.90'))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) for p,s in zip(r.preclose,st)])
    down=(r.close.to_numpy()<=prices+.005)
    one_price=down & ((r.high-r.low).to_numpy()<=.005)
    f=pd.DataFrame({'date':r.date.astype(str),'inferred_down_close':down,'one_price_down':one_price})
    # Prior 20 observed trading bars plus D0. A pair must be wholly inside it.
    pair=pd.Series(down & np.r_[False,down[:-1]])
    f['reject_consecutive2']=pair.rolling(20,min_periods=1).max().astype(bool)
    f['down_count21']=pd.Series(down).rolling(21,min_periods=1).sum().astype(int)
    f['one_price_count21']=pd.Series(one_price).rolling(21,min_periods=1).sum().astype(int)
    return f
