"""Observe D+1..D+60 lows relative to the signal close; never screen signals."""
import numpy as np

OBSERVATION_VERSION='future60_high_low_v1'
MATCH_DIRECTORY='matches_v6_box_extremes60'

def trough(low,valid,dates,t,reference):
    end=t+60;stop=min(end,len(low)-1);q=np.arange(t+1,stop+1)
    good=valid[q]&np.isfinite(low[q])&(low[q]>0)
    full=end<len(low) and len(q)==60 and good.all()
    result=dict(trough_status60='完整' if full else '未满60日' if end>=len(low) else '观察期缺价',
        trough_complete60=bool(full),trough_observed_days60=int(good.sum()),
        trough_return60=None,trough_price60=None,trough_date60=None,trough_day60=None,max_drop60=None)
    if full:
        worst=q[int(np.argmin(low[q]))]
        change=float(low[worst]/reference-1)
        result.update(trough_return60=change,trough_price60=float(low[worst]),
            trough_date60=dates[worst].strftime('%Y-%m-%d'),trough_day60=int(worst-t),
            max_drop60=max(0.,-change))
    return result
