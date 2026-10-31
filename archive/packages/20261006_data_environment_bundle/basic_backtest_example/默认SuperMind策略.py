# -*- coding: utf-8 -*-
"""Generated SuperMind strategy. Select DAILY frequency and CNY 100,000."""
from mindgo_api import *
import math
import numpy as np
import pandas as pd

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


SYMBOL = '600000.SH'
TARGET_EXPOSURE = 0.95
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 5.0
ONE_SIDE_SLIPPAGE = 0.002


def _past(frame, today):
    if frame is None or len(frame) == 0:
        return None
    x = frame.copy()
    x.index = pd.to_datetime(x.index)
    return x.loc[x.index.date < today].sort_index()


def _limit_price(bar, buy):
    if buy:
        value = min(float(bar.high_limit), float(bar.open) * (1 + ONE_SIDE_SLIPPAGE))
        return math.floor(value * 100 + 1e-8) / 100
    value = max(float(bar.low_limit), float(bar.open) * (1 - ONE_SIDE_SLIPPAGE))
    return math.ceil(value * 100 - 1e-8) / 100


def init(context):
    g.want_long = False
    set_benchmark('000300.SH')
    set_commission(PerShare(type='stock', cost=COMMISSION_RATE, min_trade_cost=MIN_COMMISSION))
    set_slippage(PriceSlippage(2 * ONE_SIDE_SLIPPAGE))
    set_volume_limit(daily=0.05, minute=0.01)
    enable_open_bar()
    log.info('BASIC_FACTOR=%s dedicated empty account, DAILY/open, initial capital 100000' % FACTOR_NAME)


def handle_bar(context, bar_dict):
    today = get_datetime().date()
    frames = history([SYMBOL], FACTOR_FIELDS, FACTOR_LOOKBACK + 10,
                     '1d', False, 'pre', True, False)
    hist = _past(frames.get(SYMBOL), today) if isinstance(frames, dict) else None
    g.want_long = bool(factor_decision(hist, g.want_long))
    try:
        bar = bar_dict[SYMBOL]
        if bool(bar.is_paused) or float(bar.volume) <= 0:
            return
        price = float(bar.open)
        upper, lower = float(bar.high_limit), float(bar.low_limit)
    except Exception:
        return
    positions = context.portfolio.positions
    held = int(positions[SYMBOL].amount) if SYMBOL in positions else 0
    if g.want_long and held == 0:
        if price >= upper - 1e-8:
            return
        account = context.portfolio.stock_account
        equity = float(account.total_value)
        limit = _limit_price(bar, True)
        quantity = int(equity * TARGET_EXPOSURE / limit / 100) * 100
        cash = float(account.available_cash)
        while quantity >= 100:
            value = quantity * limit
            if value + max(MIN_COMMISSION, value * COMMISSION_RATE) <= cash:
                break
            quantity -= 100
        if quantity >= 100:
            result = order(SYMBOL, quantity, price=limit)
            log.info('BASIC BUY qty=%d result=%s' % (quantity, str(result)))
    elif not g.want_long and held > 0:
        if price <= lower + 1e-8:
            return
        available = int(positions[SYMBOL].available_amount)
        if available > 0:
            result = order(SYMBOL, -available, price=_limit_price(bar, False))
            log.info('BASIC SELL qty=%d result=%s' % (available, str(result)))


def after_trading(context):
    account = context.portfolio.stock_account
    log.info('BASIC DAILY date=%s nav=%.2f cash=%.2f want_long=%s' %
             (str(get_datetime().date()), float(account.total_value),
              float(account.available_cash), str(g.want_long)))
