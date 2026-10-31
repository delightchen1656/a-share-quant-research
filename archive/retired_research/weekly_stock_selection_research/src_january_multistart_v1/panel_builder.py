"""Adapter-independent frozen feature/label/schedule semantics."""
import numpy as np
import pandas as pd
from runtime import base_features_and_pool
from factor_functions import quotes_valid
from common import SPEC

def make_schedule(days,index,cutoff,start='2018-01-01'):
    days=pd.DatetimeIndex(days);index=index.copy();index.index=pd.to_datetime(index.index)
    rows=[]
    for mon in pd.date_range(start,cutoff,freq='W-MON'):
        tue=mon+pd.Timedelta(days=1)
        if mon not in days or tue not in days:continue
        m=int(days.get_loc(mon));t=int(days.get_loc(tue))
        if m==0:continue
        assert t==m+1
        prices=index.reindex([mon,tue])
        market_return=prices['close'].iloc[1]/prices['open'].iloc[0]-1
        rows.append(dict(signal_date=str(days[m-1].date()),monday=str(mon.date()),tuesday=str(tue.date()),
                         signal_pos=m-1,mon_pos=m,tue_pos=t,year=mon.year,market_return=float(market_return)))
    return pd.DataFrame(rows)

def symbol_panel(symbol,frame,days,plan):
    days=pd.DatetimeIndex(days)
    frame=frame.copy()
    if 'date' in frame:frame=frame.set_index('date')
    frame.index=pd.to_datetime(frame.index)
    assert frame.index.is_unique
    frame=frame.reindex(days)
    base,eligible=base_features_and_pool(frame)
    valid,num=quotes_valid(frame)
    lr=np.log1p(num.pctChg/100).where(valid)
    base['momentum120']=np.expm1(lr.rolling(120,min_periods=108).sum())
    sig=plan.signal_pos.to_numpy()
    chosen=np.flatnonzero(eligible.iloc[sig].to_numpy())
    if not len(chosen):return None
    result=plan.iloc[chosen][['signal_date','monday','tuesday','year','market_return']].reset_index(drop=True)
    result['symbol']=symbol
    for col in SPEC['factors']:result[col]=base[col].iloc[sig[chosen]].to_numpy()
    m=plan.mon_pos.to_numpy()[chosen];t=plan.tue_pos.to_numpy()[chosen]
    mv=valid.iloc[m].to_numpy();tv=valid.iloc[t].to_numpy()
    ordinary=mv&tv&(np.abs(num.preclose.iloc[t].to_numpy()-num.close.iloc[m].to_numpy())<=.015)
    result['label_status']=np.where(~mv,'entry_quote_unavailable',np.where(~tv,'exit_quote_unavailable',np.where(~ordinary,'corporate_reference_change','ordinary_quote_horizon')))
    gross=num.close.iloc[t].to_numpy()/num.open.iloc[m].to_numpy()-1
    result['ordinary_gross_quote_return']=np.where(ordinary,gross,np.nan)
    result['ordinary_quote_excess']=result.ordinary_gross_quote_return-result.market_return
    result['label_maturity_date']=result.tuesday
    return result
