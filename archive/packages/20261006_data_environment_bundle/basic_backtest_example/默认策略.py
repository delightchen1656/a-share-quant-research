"""默认本地因子策略。

本地回测与SuperMind导出共同使用本文件。history只包含上一交易日及更早的
前复权日线，可用列为open、high、low、close、volume。
"""
import pandas as pd

FACTOR_NAME = "MA20_1PCT_BAND"
FACTOR_LOOKBACK = 20
FACTOR_FIELDS = ["open", "high", "low", "close", "volume"]


def factor_decision(history, current_position):
    if history is None or len(history) < FACTOR_LOOKBACK:
        return current_position
    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    if len(close) < FACTOR_LOOKBACK:
        return current_position
    last = float(close.iloc[-1])
    average = float(close.tail(FACTOR_LOOKBACK).mean())
    if last > average * 1.01:
        return True
    if last < average * 0.99:
        return False
    return current_position
