"""沪深2冻结信号构建器。

函数由登记前研究中的 ``run_batch_004.py`` 与
``run_batch_009_pre2025_cagr_excess.py`` 最小化抽取；只保留当前C04_NEW
因子合成、横截面排名、五日平滑和每日前三名选择，不读取归档或行情文件。
"""
from __future__ import annotations

import pandas as pd


TOP_K = 3


def _rank(raw: pd.Series, panel: pd.DataFrame) -> pd.Series:
    return panel.assign(_raw=raw).groupby("date", sort=False)["_raw"].rank(
        pct=True, method="average"
    ) - 0.5


def component_m(panel: pd.DataFrame, weights: tuple[float, float, float]) -> pd.Series:
    raw = weights[0] * panel.utility + weights[1] * panel.pen025 + weights[2] * panel.pen100
    return _rank(raw, panel)


def component_t(panel: pd.DataFrame, weights: tuple[float, float, float, float]) -> pd.Series:
    raw = (
        weights[0] * panel.t_mom120_pos
        + weights[1] * panel.t_high60_pos
        + weights[2] * panel.t_mom20_pos
        + weights[3] * panel.t_vol60_neg
    )
    return _rank(raw, panel)


def component_h(panel: pd.DataFrame, weights: tuple[float, float, float, float]) -> pd.Series:
    raw = (
        weights[0] * panel.h_size_neg
        + weights[1] * panel.h_vol60_neg
        + weights[2] * panel.h_overnight_pos
        + weights[3] * panel.h_intraday_neg
    )
    work = panel[["date", "symbol"]].copy()
    work["_raw"] = raw
    work = work.sort_values(["symbol", "date"])
    work["_smooth"] = work.groupby("symbol", sort=False)._raw.transform(
        lambda values: values.rolling(5, min_periods=3).mean()
    )
    work = work.sort_index()
    return work.groupby("date", sort=False)["_smooth"].rank(pct=True, method="average") - 0.5


def build_signals(panel: pd.DataFrame, candidate_id: str, spec: dict) -> pd.DataFrame:
    m = component_m(panel, tuple(spec["M_internal"]))
    t = component_t(panel, tuple(spec["T_internal"]))
    h = component_h(panel, tuple(spec["H_internal"]))
    outer = tuple(spec["outer"])
    out = panel[["date", "symbol", "close", "atr_pct"]].copy()
    out["score"] = outer[0] * m + outer[1] * t + outer[2] * h
    out = out.dropna(subset=["score"])
    out = out.sort_values(
        ["date", "score", "symbol"], ascending=[True, False, True], kind="stable"
    )
    out = out.groupby("date", sort=False).head(TOP_K).copy()
    out["factor"] = candidate_id
    return out.sort_values(
        ["date", "score", "symbol"], ascending=[True, False, True], kind="stable"
    )
