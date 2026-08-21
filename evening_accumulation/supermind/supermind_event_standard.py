"""SuperMind minute-frequency simulation strategy for STAR event standard.

The single-file build embeds the model and needs no project attachment.
Set strategy frequency to 1 minute. This is simulation code, not investment advice.
"""
from mindgo_api import *
import base64
import json
import math
import zlib

import numpy as np
import pandas as pd


_EMBEDDED_MODEL_B64 = ""


def _load_model():
    if _EMBEDDED_MODEL_B64:
        raw = zlib.decompress(base64.b64decode(_EMBEDDED_MODEL_B64.encode("ascii")))
        return json.loads(raw.decode("utf-8"))
    raise ValueError("embedded model is empty")


def _tree_probability(model, values):
    raw = float(model["baseline"])
    for tree in model["fast_trees"]:
        feature, threshold, missing, left, right, leaf, value = tree
        i = 0
        while not leaf[i]:
            x = values[feature[i]]
            go_left = missing[i] if np.isnan(x) else x <= threshold[i]
            i = left[i] if go_left else right[i]
        raw += value[i]
    if raw >= 0:
        z = math.exp(-raw)
        return 1.0 / (1.0 + z)
    z = math.exp(raw)
    return z / (1.0 + z)


def _batch_probabilities(model, rows):
    """Score the whole daily universe tree-by-tree instead of stock-by-stock."""
    x = np.asarray(rows, dtype=float)
    raw = np.full(len(x), float(model["baseline"]), dtype=float)
    for feature, threshold, missing, left, right, leaf, value in model["fast_trees"]:
        nodes = np.zeros(len(x), dtype=np.int32)
        active = ~leaf[nodes]
        while np.any(active):
            ri = np.flatnonzero(active); ni = nodes[ri]; fi = feature[ni]
            xv = x[ri, fi]
            go_left = np.where(np.isnan(xv), missing[ni], xv <= threshold[ni])
            nodes[ri] = np.where(go_left, left[ni], right[ni])
            active[ri] = ~leaf[nodes[ri]]
        raw += value[nodes]
    out = np.empty_like(raw); positive = raw >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-raw[positive]))
    z = np.exp(raw[~positive]); out[~positive] = z / (1.0 + z)
    return out


def _last_features(df):
    if df is None or len(df) < 120:
        return None
    x = df.sort_index()
    c = x["close"].to_numpy(dtype=float); v = x["volume"].to_numpy(dtype=float)
    high = x["high"].to_numpy(dtype=float); low = x["low"].to_numpy(dtype=float)
    r = c[1:] / c[:-1] - 1.0
    vchg = v[1:] / v[:-1] - 1.0
    out = {}
    out["ret5"], out["ret20"], out["ret60"] = c[-1] / c[-6] - 1, c[-1] / c[-21] - 1, c[-1] / c[-61] - 1
    out["range20"] = np.max(high[-20:]) / np.min(low[-20:]) - 1
    out["range60"] = np.max(high[-60:]) / np.min(low[-60:]) - 1
    out["dd20"] = c[-1] / np.max(c[-20:]) - 1
    out["vol20"], out["vol60"] = np.std(r[-20:], ddof=1), np.std(r[-60:], ddof=1)
    mean_v20 = np.mean(v[-20:])
    out["volume_ratio"] = np.mean(v[-5:]) / mean_v20
    out["volume_cv"] = np.std(v[-20:], ddof=1) / mean_v20
    out["up_volume_share"] = np.sum(v[-20:][r[-20:] > 0]) / np.sum(v[-20:])
    out["pv_corr"] = np.corrcoef(r[-20:], vchg[-20:])[0, 1]
    low60, high60 = np.min(c[-60:]), np.max(c[-60:])
    out["close_pos60"] = (c[-1] - low60) / (high60 - low60) if high60 != low60 else np.nan
    out["turn20"] = np.mean(x["turnover_rate"].to_numpy(dtype=float)[-20:])
    amount20 = np.mean(x["turnover"].to_numpy(dtype=float)[-20:])
    out["amount20"] = np.log1p(amount20)
    out["breakout_gap"] = c[-1] / np.max(c[-61:-1]) - 1
    out["rise_from_low60"] = c[-1] / low60 - 1
    out["volume_spike"] = v[-1] / mean_v20
    # The same hard anti-chasing filters used by r09.
    if (out["ret5"] > 0.12 or out["ret20"] > 0.20 or out["rise_from_low60"] > 0.30
            or out["volume_spike"] > 5 or high[-1] == low[-1]
            or float(x["quote_rate"].iloc[-1]) >= 19.5 or amount20 < 50000000
            or bool(x["is_st"].iloc[-1])):
        return None
    values = [float(out[name]) for name in g.model["features"]]
    if not np.all(np.isfinite(values)):
        return None
    return values


def init(context):
    g.model = _load_model()
    g.model["fast_trees"] = [
        (np.asarray([n["f"] for n in tree], dtype=np.int16), np.asarray([n["t"] for n in tree]),
         np.asarray([n["m"] for n in tree], dtype=bool), np.asarray([n["l"] for n in tree], dtype=np.int16),
         np.asarray([n["r"] for n in tree], dtype=np.int16), np.asarray([n["leaf"] for n in tree], dtype=bool),
         np.asarray([n["v"] for n in tree])) for tree in g.model["trees"]
    ]
    g.pending = []
    g.position_state = {}
    g.order_intent = {}
    g.order_locks = {}
    g.buy_done_date = None
    set_benchmark("000688.SH")
    # PriceSlippage is the full spread; 0.002 means about 0.1% on each side.
    set_slippage(PriceSlippage(0.002))
    set_commission(PerShare(type="stock", cost=0.0003, min_trade_cost=5.0))
    set_volume_limit(daily=0.25, minute=0.5)
    log.info("STAR event standard initialized; use 1-minute frequency")


def before_trading(context):
    today = get_datetime().date()
    g.order_locks = {}
    # Frozen 2026-07-31 universe, identical to the local event-standard experiment.
    symbols = g.model["universe"]
    fields = ["open", "high", "low", "close", "volume", "turnover", "turnover_rate", "quote_rate", "is_st"]
    feature_rows = []
    # 300-symbol chunks reduce daily history calls from 7 to 3.
    for begin in range(0, len(symbols), 300):
        batch = symbols[begin:begin + 300]
        data = history(batch, fields, 121, "1d", True, "pre", True, False)
        for symbol in batch:
            values = _last_features(data.get(symbol) if isinstance(data, dict) else None)
            if values is None:
                continue
            feature_rows.append((symbol, values))
    scored = []
    if feature_rows:
        probabilities = _batch_probabilities(g.model, [item[1] for item in feature_rows])
        scored = [(feature_rows[i][0], float(p)) for i, p in enumerate(probabilities)
                  if p >= g.model["threshold"]]
    scored.sort(key=lambda item: item[1], reverse=True)
    g.pending = scored[:g.model["top_per_day"]]
    g.buy_done_date = None
    log.info("STAR candidates: %s" % str(g.pending))


def _submit(symbol, target_amount, action):
    if symbol in g.order_locks:
        return
    order_id = order_target(symbol, int(target_amount))
    if order_id is not None:
        g.order_locks[symbol] = order_id
        g.order_intent[order_id] = {"symbol": symbol, "action": action}


def handle_bar(context, bar_dict):
    now = get_datetime()
    positions = context.portfolio.positions
    # Execute yesterday-close candidates once after today's open.
    if g.buy_done_date != now.date():
        slots = max(0, g.model["max_positions"] - len(positions))
        for symbol, probability in g.pending:
            if slots <= 0:
                break
            if symbol in positions or symbol in g.order_locks:
                continue
            order_id = order_target_percent(symbol, 0.10)
            if order_id is not None:
                g.order_locks[symbol] = order_id
                g.order_intent[order_id] = {"symbol": symbol, "action": "BUY", "probability": probability}
                slots -= 1
        g.buy_done_date = now.date()
    # Minute-level risk management.
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        if symbol not in g.position_state:
            g.position_state[symbol] = {"entry": float(pos.cost_basis), "half": False, "entry_date": None}
        state = g.position_state[symbol]
        # A-share T+1: shares bought today are not sellable today.
        if state.get("entry_date") == now.date() or int(pos.position_days) <= 0:
            continue
        price = float(pos.last_price)
        if price <= state["entry"] * 0.93:
            _submit(symbol, 0, "STOP")
        elif price >= state["entry"] * 1.34:
            _submit(symbol, 0, "TPALL")
        elif price >= state["entry"] * 1.24 and not state["half"]:
            _submit(symbol, max(0, int(pos.amount / 2)), "TPHALF")
        elif int(pos.position_days) >= 30:
            _submit(symbol, 0, "TIME")


def on_order(context, odr):
    intent = g.order_intent.get(odr.order_id)
    if intent is None:
        return
    status = str(odr.status)
    symbol, action = intent["symbol"], intent["action"]
    if "FILLED" in status:
        if action == "BUY":
            pos = context.portfolio.positions.get(symbol)
            if pos is not None:
                g.position_state[symbol] = {"entry": float(pos.cost_basis), "half": False,
                                            "entry_date": get_datetime().date()}
        elif action == "TPHALF" and symbol in g.position_state:
            g.position_state[symbol]["half"] = True
        elif action in ("STOP", "TPALL", "TIME"):
            g.position_state.pop(symbol, None)
        g.order_locks.pop(symbol, None)
        g.order_intent.pop(odr.order_id, None)
        log.info("filled %s %s" % (action, symbol))
    elif "REJECTED" in status or "CANCELLED" in status:
        g.order_locks.pop(symbol, None)
        g.order_intent.pop(odr.order_id, None)
        log.warn("order failed %s %s" % (action, symbol))
