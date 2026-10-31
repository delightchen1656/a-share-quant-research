"""Observe the unchanged D1..D60 window relative to the strict D1 opening price."""
import numpy as np
from compute_peak60 import peak
from compute_trough60 import trough

OBSERVATION_VERSION='future60_nextopen_high_low_v1'
MATCH_DIRECTORY='matches_v7_box_nextopen60'

def observe(open_,high,low,close,raw_open,valid,dates,t):
    j=t+1;exists=j<len(dates)
    available=bool(exists and valid[j] and np.isfinite(open_[j]) and open_[j]>0 and np.isfinite(raw_open[j]) and raw_open[j]>0)
    reference=float(open_[j]) if available else None
    result=dict(return_basis='next_session_open',entry_date=dates[j].strftime('%Y-%m-%d') if exists else None,
        entry_open=reference,entry_raw_open=float(raw_open[j]) if available else None,
        entry_status='有效' if available else '次日开盘缺价' if exists else '待次日行情',
        adjusted_reference_price=reference,raw_reference_price=float(raw_open[j]) if available else None,
        **peak(high,valid,dates,t,reference or 1.),**trough(low,valid,dates,t,reference or 1.))
    target=t+40
    result['adjusted_price_change']=float(close[target]/reference-1) if available and target<len(dates) and valid[target] else None
    if not available:
        for key in ['peak_return60','peak40_same_cohort','trough_return60','max_drop60']:result[key]=None
        assert not result['peak_complete60'] and not result['trough_complete60']
    return result
