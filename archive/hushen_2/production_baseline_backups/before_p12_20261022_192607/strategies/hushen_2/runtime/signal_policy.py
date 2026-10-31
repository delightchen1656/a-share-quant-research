"""User-approved ATR025 post-selection filter; frozen model and ranking stay intact."""
from __future__ import annotations
import math
import pandas as pd

POLICY_ID='original_top3_atr_ge025_no_refill_v1'
MINIMUM_ATR=0.025


def configuration():
    return dict(policy=POLICY_ID,minimum_atr=MINIMUM_ATR,comparison='>=',
        applied_after='original_daily_top3',refill=False,preserve_original_rank=True)


def eligible(atr):
    value=float(atr)
    return math.isfinite(value) and MINIMUM_ATR<=value<=.05


def filter_frame(candidates:pd.DataFrame)->pd.DataFrame:
    """Filter the ORIGINAL top3 output, never rebuild rankings on a reduced pool."""
    if not {'date','symbol','atr_pct'}.issubset(candidates.columns):
        raise ValueError('ATR筛选缺少候选日期、代码或ATR')
    if candidates.duplicated(['date','symbol']).any() or candidates.groupby('date').size().gt(3).any():
        raise ValueError('必须先生成原每日前三，再执行ATR筛选；禁止补选第四名')
    return candidates.loc[candidates.atr_pct.map(eligible)].copy()


def filter_payloads(candidates):
    if not isinstance(candidates,list) or len(candidates)>3:
        raise ValueError('ATR筛选只接收原始前三信号')
    return [dict(s) for s in candidates if eligible(s['atr'])]
