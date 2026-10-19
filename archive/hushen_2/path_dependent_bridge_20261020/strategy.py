"""沪深2冻结策略定义。

只定义已登记的因子与执行参数；不会连接券商或自动下单。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


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


def _load_builder():
    root = Path(__file__).resolve().parents[3]
    path = (
        root
        / "archive"
        / "hushen_2"
        / "pre_registration_research_20261020"
        / "results"
        / "batch_009_pre2025_cagr_excess"
        / "run_batch_009_pre2025_cagr_excess.py"
    )
    spec = importlib.util.spec_from_file_location("hushen2_frozen_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen builder: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_signals(component_panel: pd.DataFrame) -> pd.DataFrame:
    """按冻结C04_NEW权重生成每日最多3只信号。"""
    return _load_builder().build_signals(component_panel, CANDIDATE_ID, FACTOR_SPEC)
