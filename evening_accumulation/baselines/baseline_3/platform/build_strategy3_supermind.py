"""Build the single-file SuperMind Strategy 3 script from the proven V3 execution shell."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "supermind_event_baseline30_live_realistic_v3_single.py"
TARGET = HERE / "supermind_strategy3_bear_downside_v1_single.py"


def literal(name, b64):
    chunks = [b64[i:i + 100] for i in range(0, len(b64), 100)]
    return name + " = (\n" + "\n".join('    "' + x + '"' for x in chunks) + "\n)\n\n"


text = SOURCE.read_text(encoding="utf-8")
stop_b64 = (HERE / "strategy3_stop_risk_model.b64").read_text(encoding="ascii")
bear_b64 = (HERE / "strategy3_bear_models.b64").read_text(encoding="ascii")
insert_at = text.index("def _load_model():")
text = text[:insert_at] + literal("_EMBEDDED_STOP_MODEL_B64", stop_b64) + literal(
    "_EMBEDDED_BEAR_MODELS_B64", bear_b64
) + text[insert_at:]

helpers = r'''
def _load_extra_model(encoded):
    raw = zlib.decompress(base64.b64decode(encoded.encode("ascii")))
    return json.loads(raw.decode("utf-8"))


def _prepare_portable(model):
    model["fast_trees"] = [
        (np.asarray([n["f"] for n in tree], dtype=np.int16),
         np.asarray([n["t"] for n in tree]),
         np.asarray([n["m"] for n in tree], dtype=bool),
         np.asarray([n["l"] for n in tree], dtype=np.int16),
         np.asarray([n["r"] for n in tree], dtype=np.int16),
         np.asarray([n["leaf"] for n in tree], dtype=bool),
         np.asarray([n["v"] for n in tree])) for tree in model["trees"]
    ]
    return model


def _bear_model_for_today(today):
    key = today.strftime("%Y-%m-%d")
    selected = None
    for model in g.bear_bundle["models"]:
        if model["start"] <= key and key <= model["end"]:
            return model
        if model["start"] <= key:
            selected = model
    return selected


def _market_values(frames):
    series = []
    for symbol in frames:
        frame = frames[symbol]
        if frame is None or len(frame) < 61:
            continue
        series.append(frame.sort_index()["close"].astype(float).rename(symbol).iloc[-61:])
    if not series:
        return None, None
    close = pd.concat(series, axis=1).sort_index().tail(61)
    ret = close / close.shift(1) - 1.0
    mret = ret.mean(axis=1).fillna(0.0)
    nav = (1.0 + mret).cumprod()
    out = {}
    out["mret5"] = float(nav.iloc[-1] / nav.iloc[-6] - 1.0)
    out["mret20"] = float(nav.iloc[-1] / nav.iloc[-21] - 1.0)
    out["mret60"] = float(nav.iloc[-1] / nav.iloc[-61] - 1.0)
    out["mvol20"] = float(mret.iloc[-20:].std())
    out["breadth1"] = float((ret.iloc[-5:] > 0).mean(axis=1).mean())
    out["breadth20"] = float((close.iloc[-1] / close.iloc[-21] - 1.0 > 0).mean())
    out["dispersion"] = float(ret.iloc[-5:].std(axis=1).mean())
    out["downside_share"] = float((ret.iloc[-5:] < -0.03).mean(axis=1).mean())
    cross_var = float(ret.var(axis=1).iloc[-20:].mean())
    out["common_risk"] = min(1.0, max(0.0, float(mret.iloc[-20:].var()) / cross_var)) if cross_var > 0 else 0.0
    out["avg_dd20"] = float((close.iloc[-1] / close.iloc[-20:].max() - 1.0).mean())
    values = [float(out[name]) for name in g.bear_bundle["features"]]
    if not np.all(np.isfinite(values)):
        return None, close
    return values, close


def _downside_penalty(symbol, held_symbols, close):
    if close is None or symbol not in close.columns or not held_symbols:
        return 0.0
    ret = close.pct_change().tail(60)
    downside = ret.loc[ret.mean(axis=1) < 0]
    if len(downside) < 15:
        return 0.0
    x = downside[symbol].to_numpy(dtype=float)
    maximum = 0.0
    for held in held_symbols:
        if held not in downside.columns:
            continue
        y = downside[held].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if int(valid.sum()) < 15:
            continue
        corr = float(np.corrcoef(x[valid], y[valid])[0, 1])
        if np.isfinite(corr):
            maximum = max(maximum, corr)
    return max(0.0, maximum)


'''
init_at = text.index("def init(context):")
text = text[:init_at] + helpers + text[init_at:]

old_init_line = "    g.pending = []\n"
new_init = '''    g.stop_model = _prepare_portable(_load_extra_model(_EMBEDDED_STOP_MODEL_B64))
    g.bear_bundle = _load_extra_model(_EMBEDDED_BEAR_MODELS_B64)
    for item in g.bear_bundle["models"]:
        _prepare_portable(item)
    g.bear_probability = 0.0
    g.risk_fraction = 0.10
    g.pending = []
'''
text = text.replace(old_init_line, new_init, 1)
text = text.replace(
    'log.info("STAR event standard initialized; use 1-minute frequency; cost=%s" % COST_SCENARIO)',
    'log.info("Strategy3 bear-downside V1 initialized; daily frequency; model valid through 2026-09-30; cost=%s" % COST_SCENARIO)',
    1,
)

start = text.index("def before_trading(context):")
end = text.index("def _submit(symbol, target_amount, action):", start)
before = r'''def before_trading(context):
    today = get_datetime().date()
    g.order_locks = {}; g.order_intent = {}; g.order_seen_fill = {}; g.previous_close = {}
    g.daily_buy_value = 0.0; g.daily_sell_value = 0.0
    symbols = g.model["universe"]
    fields = ["open", "high", "low", "close", "volume", "turnover", "turnover_rate", "quote_rate", "is_st"]
    feature_rows = []; frames = {}
    for begin in range(0, len(symbols), 300):
        batch = symbols[begin:begin + 300]
        data = history(batch, fields, 121, "1d", True, "pre", True, False)
        for symbol in batch:
            frame = data.get(symbol) if isinstance(data, dict) else None
            if frame is not None and len(frame):
                frames[symbol] = frame
                g.previous_close[symbol] = float(frame.sort_index()["close"].iloc[-1])
            values = _last_features(frame)
            if values is not None:
                feature_rows.append((symbol, values))
    scored = []
    if feature_rows:
        values = [item[1] for item in feature_rows]
        up = _batch_probabilities(g.model, values)
        stop = _batch_probabilities(g.stop_model, values)
        held = list(context.portfolio.positions.keys())
        market_values, close = _market_values(frames)
        for i in range(len(feature_rows)):
            probability = float(up[i]); stop_probability = float(stop[i])
            if probability < g.model["threshold"] or stop_probability > 0.50:
                continue
            symbol = feature_rows[i][0]
            rank_score = probability - 0.22 * stop_probability
            rank_score -= 0.10 * _downside_penalty(symbol, held, close)
            scored.append((symbol, probability, rank_score, stop_probability))
        model = _bear_model_for_today(today)
        if model is not None and market_values is not None:
            g.bear_probability = float(_tree_probability(model, market_values))
        else:
            g.bear_probability = 0.0
    scored.sort(key=lambda item: item[2], reverse=True)
    g.pending = [(item[0], item[1]) for item in scored[:g.model["top_per_day"]]]
    if g.bear_probability >= 0.70: g.risk_fraction = 0.055
    elif g.bear_probability >= 0.55: g.risk_fraction = 0.075
    elif g.bear_probability >= 0.40: g.risk_fraction = 0.09
    else: g.risk_fraction = 0.10
    g.buy_done_date = None
    log.info("STRATEGY3 candidates=%s bear_probability=%.6f new_position=%.3f" %
             (str(g.pending), g.bear_probability, g.risk_fraction))


'''
text = text[:start] + before + text[end:]
text = text.replace("order_target_percent(symbol, 0.10)", "order_target_percent(symbol, g.risk_fraction)", 1)
TARGET.write_text(text, encoding="utf-8")
print(TARGET, TARGET.stat().st_size)
