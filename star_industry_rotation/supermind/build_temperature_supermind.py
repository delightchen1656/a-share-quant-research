from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "evening_accumulation" / "baselines" / "baseline_3" / "platform" / "supermind_strategy3_bear_downside_v1_single.py"
MAPPING = ROOT / "star_industry_rotation" / "industry_map.csv"


def encoded_mapping() -> str:
    frame = pd.read_csv(MAPPING)
    mapping = dict(zip(frame.symbol.astype(str), frame.industry.astype(str)))
    raw = json.dumps(mapping, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


HELPERS = r'''

_INDUSTRY_MAP_B64 = "__MAPPING__"


def _temperature_sigmoid(value, scale):
    value = min(5.0 * scale, max(-5.0 * scale, float(value)))
    return 100.0 / (1.0 + math.exp(-value / scale))


def _industry_snapshot(frames, offset):
    """Point-in-time industry heat using only completed daily bars."""
    result = {}
    for industry, members in g.industry_members.items():
        close_series = []
        breadth = []
        total_amount20 = 0.0
        total_amount60 = 0.0
        leaders = []
        for symbol in members:
            frame = frames.get(symbol)
            if frame is None:
                continue
            x = frame.sort_index()
            end = len(x) - int(offset)
            if end < 130:
                continue
            x = x.iloc[:end]
            close = x["close"].astype(float)
            turnover = x["turnover"].astype(float)
            if len(close) < 130 or float(turnover.iloc[-20:].mean()) < 50000000:
                continue
            try:
                if str(x["is_st"].iloc[-1]).strip().lower() in ("1", "true", "yes"):
                    continue
            except Exception:
                pass
            close_series.append(close.iloc[-253:].rename(symbol))
            breadth.append(float(close.iloc[-1] > close.iloc[-60:].mean()))
            total_amount20 += float(turnover.iloc[-20:].mean())
            total_amount60 += float(turnover.iloc[-60:].mean())
            leaders.append(float(close.iloc[-1] / close.iloc[-22] - 1.0))
        if len(close_series) < 4:
            continue
        close = pd.concat(close_series, axis=1).sort_index().tail(253)
        ret = close / close.shift(1) - 1.0
        group_ret = ret.mean(axis=1).fillna(0.0)
        nav = (1.0 + group_ret).cumprod()
        if len(nav) < 120:
            continue
        low = float(nav.iloc[-252:].min())
        high = float(nav.iloc[-252:].max())
        position = 50.0 if high <= low else 100.0 * (float(nav.iloc[-1]) - low) / (high - low)
        mom63 = float(nav.iloc[-1] / nav.iloc[-64] - 1.0)
        trend = _temperature_sigmoid(mom63, 0.12)
        breadth_score = 100.0 * float(np.mean(breadth))
        volume_ratio = total_amount20 / total_amount60 if total_amount60 > 0 else 1.0
        volume_score = _temperature_sigmoid(volume_ratio - 1.0, 0.30)
        recent = ret.iloc[-20:]
        common = recent.mean(axis=1)
        dispersion = float(recent.sub(common, axis=0).pow(2).mean(axis=1).pow(0.5).mean())
        common_vol = float(common.std())
        linkage = 1.0 - dispersion / (dispersion + common_vol) if dispersion + common_vol > 0 else 0.0
        linkage_score = 100.0 * min(1.0, max(0.0, linkage))
        leader_score = _temperature_sigmoid(max(leaders), 0.15)
        heat = (0.20 * position + 0.25 * trend + 0.20 * breadth_score +
                0.12 * volume_score + 0.10 * linkage_score + 0.13 * leader_score)
        result[industry] = {"heat": min(100.0, max(0.0, heat)), "breadth": breadth_score}
    return result


def _industry_temperature(frames):
    current = _industry_snapshot(frames, 0)
    previous = _industry_snapshot(frames, 10)
    out = {}
    for industry in current:
        if industry not in previous:
            continue
        out[industry] = {
            "heat": float(current[industry]["heat"]),
            "breadth": float(current[industry]["breadth"]),
            "delta": float(current[industry]["heat"] - previous[industry]["heat"]),
        }
    return out


def _temperature_allowed(symbol, temperatures, bear_probability):
    industry = g.industry_map.get(symbol)
    state = temperatures.get(industry)
    if state is None:
        return False
    heat = float(state["heat"]); delta = float(state["delta"]); breadth = float(state["breadth"])
    if _TEMPERATURE_STRATEGY == 4:
        return not ((heat >= 85.0 and delta < 0.0) or
                    (float(bear_probability) >= 0.70 and delta < -5.0))
    return bool(delta > 0.0 or (heat >= 65.0 and delta > -4.0 and breadth >= 55.0))
'''


def build(strategy: int) -> Path:
    source = SOURCE.read_text(encoding="utf-8")
    mapping = encoded_mapping()
    helper = HELPERS.replace("__MAPPING__", mapping)
    marker = "\ndef init(context):\n"
    if source.count(marker) != 1:
        raise RuntimeError("init marker mismatch")
    source = source.replace(marker, f"\n_TEMPERATURE_STRATEGY = {strategy}\n" + helper + marker, 1)
    init_line = "    g.bear_probability = 0.0\n"
    init_add = (
        "    g.industry_map = _load_extra_model(_INDUSTRY_MAP_B64)\n"
        "    g.industry_members = {}\n"
        "    for _symbol, _industry in g.industry_map.items():\n"
        "        if _symbol in g.model[\"universe\"]:\n"
        "            g.industry_members.setdefault(_industry, []).append(_symbol)\n"
    )
    source = source.replace(init_line, init_add + init_line, 1)
    source = source.replace('history(batch, fields, 121, "1d", True, "pre", True, False)',
                            'history(batch, fields, 263, "1d", True, "pre", True, False)', 1)
    sort_marker = "    scored.sort(key=lambda item: item[2], reverse=True)\n"
    gate = (
        "    temperatures = _industry_temperature(frames)\n"
        "    scored = [item for item in scored if _temperature_allowed(item[0], temperatures, g.bear_probability)]\n"
    )
    source = source.replace(sort_marker, gate + sort_marker, 1)
    old_log = 'log.info("Strategy3 bear-downside V1 initialized; daily frequency; model valid through 2026-09-30; cost=%s" % COST_SCENARIO)'
    new_log = f'log.info("Strategy{strategy} temperature overlay initialized; daily frequency; model valid through 2026-09-30; cost=%s" % COST_SCENARIO)'
    source = source.replace(old_log, new_log, 1)
    source = source.replace('log.info("STRATEGY3 candidates=%s bear_probability=%.6f new_position=%.3f" %',
                            f'log.info("STRATEGY{strategy} candidates=%s bear_probability=%.6f new_position=%.3f" %', 1)
    filename = ("supermind_strategy4_temperature_attack_single.py" if strategy == 4
                else "supermind_strategy5_rising_defense_single.py")
    target = HERE / filename
    target.write_text(source, encoding="utf-8")
    return target


if __name__ == "__main__":
    for number in (4, 5):
        path = build(number)
        print(path, path.stat().st_size)
