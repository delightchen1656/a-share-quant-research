"""沪深2冻结策略定义。

只定义已登记的因子与执行参数；不会连接券商或自动下单。
"""
from __future__ import annotations

import pandas as pd

try:
    from .frozen_builder import build_signals as _build_signals
except ImportError:  # 兼容直接从runtime目录加载
    from frozen_builder import build_signals as _build_signals


STRATEGY_NAME = "沪深2"
CANDIDATE_ID = "C04_NEW"
FACTOR_SPEC = {
    "M_internal": [0.5, 0.5, 0.0],
    "T_internal": [0.5, 0.0, 0.5, 0.0],
    "H_internal": [0.25, 0.25, 0.5, 0.0],
    "outer": [0.6, 0.0, 0.4],
}
EXECUTION = {
    "initial_cash": 100_000.0,
    "slots": 5,
    "maximum_daily_signals": 3,
    "conditional_buy_lifetime_calendar_days": 7,
    "holding_calendar_days": 30,
    "entry_atr": 0.0,
    "take_atr": 4.0,
    "stop_atr": 1.5,
    "t_plus_one": True,
    "same_day_double_touch": "stop_first",
    "daily_volume_capacity_fraction": 0.02,
}

def build_signals(component_panel: pd.DataFrame) -> pd.DataFrame:
    """按冻结C04_NEW权重生成每日最多3只信号。"""
    return _build_signals(component_panel, CANDIDATE_ID, FACTOR_SPEC)
