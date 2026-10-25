"""Registered ATR025-only filter; P12 helpers retained solely for research history."""
from __future__ import annotations
import math
import pandas as pd
import numpy as np

POLICY_ID='original_top3_atr_ge025_no_refill_v1'
MINIMUM_ATR=0.025
MINIMUM_SIZE_PROXY=16.901055936487055
MINIMUM_VOL60=0.018471572551217057


def configuration():
    return dict(policy=POLICY_ID,minimum_atr=MINIMUM_ATR,comparison='>=',
        applied_after='original_daily_top3',refill=False,preserve_original_rank=True)


def eligible(atr):
    value=float(atr)
    return math.isfinite(value) and MINIMUM_ATR<=value<=.05


def eligible_p12(atr,size_proxy,vol60):
    return eligible(atr) and math.isfinite(float(size_proxy)) and math.isfinite(float(vol60)) and float(size_proxy)>=MINIMUM_SIZE_PROXY and float(vol60)>=MINIMUM_VOL60


def attach_features(candidates,component_panel):
    """Join after original ranking. Missing features are an error, not a refill."""
    features=component_panel[['date','symbol','f_log_amount','f_turn','vol60']].copy()
    features['size_proxy']=features.f_log_amount-np.log(features.f_turn.clip(lower=1e-6))
    out=candidates.merge(features[['date','symbol','size_proxy','vol60']],on=['date','symbol'],how='left',validate='one_to_one',sort=False)
    if out[['size_proxy','vol60']].isna().any().any():raise ValueError('P12候选缺少规模或60日波动特征')
    return out


def filter_frame(candidates:pd.DataFrame)->pd.DataFrame:
    """Filter the ORIGINAL top3 output, never rebuild rankings on a reduced pool."""
    if not {'date','symbol','atr_pct'}.issubset(candidates.columns):
        raise ValueError('ATR筛选缺少日期、代码或ATR')
    if candidates.duplicated(['date','symbol']).any() or candidates.groupby('date').size().gt(3).any():
        raise ValueError('必须先生成原每日前三，再执行ATR筛选；禁止补选第四名')
    return candidates.loc[candidates.atr_pct.map(eligible)].copy()


def filter_payloads(candidates):
    if not isinstance(candidates,list) or len(candidates)>3:
        raise ValueError('ATR筛选只接收原始前三信号')
    return [dict(s) for s in candidates if eligible(s['atr'])]
