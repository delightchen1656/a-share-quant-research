from mindgo_api import *

import base64
import json
import math
import zlib

import numpy as np


# 沪深基准1：状态切换红利反转（SuperMind 收益优化V2）
# 建议设置：日频；回测起点不早于 2018-01-01；基准 000905.SH。
# 股票池压缩文本由构建步骤写入，不依赖 os/open/getattr。
_MAINBOARD_UNIVERSE_B64 = "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"

TARGET_COUNT = 20
BUFFER_COUNT = 40
TARGET_EXPOSURE = 1.00
MIN_LISTING_BARS = 250
MIN_AMOUNT20 = 50000000.0
MIN_VOL20 = 0.004
MAX_VOL20 = 0.08
MAX_SINGLE_MULTIPLE = 1.5


def _load_universe():
    raw = zlib.decompress(base64.b64decode(_MAINBOARD_UNIVERSE_B64.encode("ascii")))
    symbols = json.loads(raw.decode("utf-8"))
    # 国金普通A股账户硬白名单：只允许沪深主板普通人民币股票。
    # 明确排除科创板/存托凭证、创业板、北交所及其他需要另行开通权限的品种。
    return [s for s in symbols if _is_ordinary_mainboard_a(s)]


def _is_ordinary_mainboard_a(symbol):
    if symbol.endswith(".SH"):
        return symbol.startswith(("600", "601", "603", "605"))
    if symbol.endswith(".SZ"):
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def _rank01(values, reverse=False):
    a = np.asarray(values, dtype=float)
    out = np.zeros(len(a), dtype=float)
    valid = np.isfinite(a)
    idx = np.flatnonzero(valid)
    if len(idx) == 0:
        return out
    order = idx[np.argsort(a[idx], kind="mergesort")]
    if len(order) == 1:
        out[order[0]] = 0.5
    else:
        out[order] = np.arange(len(order), dtype=float) / float(len(order) - 1)
    if reverse:
        out[valid] = 1.0 - out[valid]
    return out


def _dividend_quality(qfq_frame, raw_frame):
    """由前复权/原始收盘价的复权因子变化估计分红持续性。

    SuperMind批量history对历史preclose字段可能返回空数据，因此这里只用
    三个既有科创基准已经验证过的close字段。
    """
    if qfq_frame is None or raw_frame is None:
        return np.nan
    q = qfq_frame.sort_index()
    r = raw_frame.sort_index()
    if "close" not in q.columns or "close" not in r.columns:
        return np.nan
    common = q.index.intersection(r.index)
    if len(common) < MIN_LISTING_BARS:
        return np.nan
    qc = q.loc[common, "close"].to_numpy(dtype=float)
    rc = r.loc[common, "close"].to_numpy(dtype=float)
    valid = np.isfinite(qc) & np.isfinite(rc) & (qc > 0) & (rc > 0)
    factor = np.full(len(common), np.nan, dtype=float)
    factor[valid] = qc[valid] / rc[valid]
    change = np.zeros(max(0, len(factor) - 1), dtype=float)
    pair = np.isfinite(factor[1:]) & np.isfinite(factor[:-1]) & (factor[:-1] > 0)
    change[pair] = np.abs(factor[1:][pair] / factor[:-1][pair] - 1.0)
    # 过滤极小数值噪声及大比例送转；跨年度持续发生的小幅复权因子变化
    # 才会获得较高质量分。
    event = (change > 0.0005) & (change < 0.12)
    if not np.any(event):
        return 0.0
    n = len(change)
    recent = change[max(0, n - 250):]
    middle = change[max(0, n - 500):max(0, n - 250)]
    old = change[max(0, n - 750):max(0, n - 500)]
    y0 = float(np.sum(recent[(recent > 0.0005) & (recent < 0.12)]))
    y1 = float(np.sum(middle[(middle > 0.0005) & (middle < 0.12)]))
    y2 = float(np.sum(old[(old > 0.0005) & (old < 0.12)]))
    persistence = float((y0 > 0) + (y1 > 0) + (y2 > 0)) / 3.0
    return 0.70 * persistence + 0.30 * min(y0 / 0.05, 1.0)


def _features(qfq_frame, raw_frame):
    if qfq_frame is None or len(qfq_frame) < MIN_LISTING_BARS:
        return None
    x = qfq_frame.sort_index()
    c = x["close"].to_numpy(dtype=float)
    amount = x["turnover"].to_numpy(dtype=float)
    if len(c) < 121 or not np.all(np.isfinite(c[-121:])):
        return None
    # 风险标识缺失时也拒绝入池，避免数据异常导致越权买入。
    if "is_st" not in x.columns:
        return None
    risk_flag = str(x["is_st"].iloc[-1]).strip().lower()
    if risk_flag in ("1", "true", "yes"):
        return None
    r = c[1:] / c[:-1] - 1.0
    vol20 = float(np.std(r[-20:], ddof=1))
    amount20 = float(np.nanmean(amount[-20:]))
    if (not np.isfinite(vol20) or vol20 < MIN_VOL20 or vol20 > MAX_VOL20
            or not np.isfinite(amount20) or amount20 < MIN_AMOUNT20):
        return None
    neg = np.minimum(r[-20:], 0.0)
    downside = float(np.sqrt(np.mean(neg * neg)))
    high120 = float(np.max(c[-120:]))
    ma60 = float(np.mean(c[-60:]))
    dividend = _dividend_quality(x, raw_frame)
    if not np.isfinite(dividend):
        # 原始价暂缺时不把整只股票剔除；分红项取中性最低值，其他已验证
        # 技术和流动性因子仍可参与排序，避免平台返回空原始价导致零候选。
        dividend = 0.0
    return {
        "amount20": amount20,
        "near_high": float(c[-1] / high120),
        "below_high": float(1.0 - c[-1] / high120),
        "below_ma60": float(max(0.0, 1.0 - c[-1] / ma60)),
        "dividend": float(dividend),
        "downside": max(downside, 0.002),
    }


def _is_first_session_of_month(today):
    key = today.year * 100 + today.month
    if g.last_month_key == key:
        return False
    g.last_month_key = key
    return True


def _build_targets(context):
    symbols = g.universe
    rows = []
    qfq_ok = 0
    raw_ok = 0
    fields = ["close", "turnover", "is_st"]
    raw_fields = ["close"]
    for begin in range(0, len(symbols), 160):
        batch = symbols[begin:begin + 160]
        qfq = history(batch, fields, 751, "1d", True, "pre", True, False)
        raw = history(batch, raw_fields, 751, "1d", True, None, True, False)
        for symbol in batch:
            qf = qfq.get(symbol) if isinstance(qfq, dict) else None
            rf = raw.get(symbol) if isinstance(raw, dict) else None
            if qf is not None and len(qf):
                qfq_ok += 1
            if rf is not None and len(rf):
                raw_ok += 1
            ft = _features(qf, rf)
            if ft is not None:
                rows.append((symbol, ft))
    if not rows:
        log.warn("BASELINE1 no eligible stocks; keep current holdings")
        return None

    bench_data = history(["000905.SH"], ["close"], 121, "1d", True, "pre", True, False)
    bench = bench_data.get("000905.SH") if isinstance(bench_data, dict) else None
    if bench is None or len(bench) < 121:
        log.warn("BASELINE1 benchmark history unavailable")
        return None
    bc = bench.sort_index()["close"].to_numpy(dtype=float)
    strong = bool(bc[-1] > np.mean(bc[-120:]))

    low_amount = _rank01([x[1]["amount20"] for x in rows], reverse=True)
    near_high = _rank01([x[1]["near_high"] for x in rows])
    below_high = _rank01([x[1]["below_high"] for x in rows])
    below_ma = _rank01([x[1]["below_ma60"] for x in rows])
    dividend = _rank01([x[1]["dividend"] for x in rows])
    if strong:
        score = 0.25 * low_amount + 0.20 * near_high + 0.55 * dividend
    else:
        # 只使用2020-2023开发期与2024验证期选出的正式弱市结构。
        score = 0.50 * below_high + 0.25 * below_ma + 0.25 * dividend

    order = np.argsort(-score, kind="mergesort")
    buffer_symbols = [rows[i][0] for i in order[:BUFFER_COUNT]]
    held = list(context.portfolio.positions.keys())
    retained = [s for s in held if s in buffer_symbols]
    selected = retained[:TARGET_COUNT]
    for i in order:
        symbol = rows[i][0]
        if symbol not in selected:
            selected.append(symbol)
        if len(selected) >= TARGET_COUNT:
            break

    downside_map = {}
    for symbol, ft in rows:
        downside_map[symbol] = ft["downside"]
    inv = np.asarray([1.0 / downside_map[s] for s in selected], dtype=float)
    weights = inv / np.sum(inv)
    cap = MAX_SINGLE_MULTIPLE / float(TARGET_COUNT)
    # 迭代封顶后重新分配，保证组合权重之和为95%。
    for _ in range(10):
        above = weights > cap
        if not np.any(above):
            break
        fixed = float(np.sum(np.minimum(weights[above], cap)))
        weights[above] = cap
        free = ~above
        if np.any(free):
            weights[free] = weights[free] / np.sum(weights[free]) * (1.0 - fixed)
    targets = {}
    for i in range(len(selected)):
        targets[selected[i]] = float(weights[i] * TARGET_EXPOSURE)
    log.info("BASELINE1 regime=%s qfq=%d raw=%d eligible=%d selected=%s" %
             ("STRONG" if strong else "WEAK", qfq_ok, raw_ok, len(rows), str(selected)))
    return targets


def init(context):
    g.universe = _load_universe()
    g.targets = None
    g.rebalance_pending = False
    g.last_month_key = None
    g.submitted_date = None
    set_benchmark("000905.SH")
    set_slippage(PriceSlippage(0.004))
    set_commission(PerShare(type="stock", cost=0.0003, min_trade_cost=5.0))
    # 资金容量约束，不是交易所硬限制。日频回测允许最多参与全天成交量5%；
    # 相比旧版0.5%，可显著减少调仓后遗留的小额旧仓。
    set_volume_limit(daily=0.05, minute=0.01)
    log.info("沪深基准1 状态切换红利反转 收益优化V2 initialized; daily frequency")


def before_trading(context):
    today = get_datetime().date()
    g.submitted_date = None
    if _is_first_session_of_month(today):
        targets = _build_targets(context)
        if targets is not None:
            g.targets = targets
            g.rebalance_pending = True


def _trade_state(symbol, bar_dict):
    try:
        bar = bar_dict[symbol]
    except Exception:
        return False, False, False
    price = float(bar.open)
    volume = float(bar.volume)
    if bool(bar.is_paused) or not np.isfinite(price) or price <= 0 or volume <= 0:
        return False, False, False
    upper = float(bar.high_limit)
    lower = float(bar.low_limit)
    locked_up = np.isfinite(upper) and price >= upper * 0.999
    locked_down = np.isfinite(lower) and price <= lower * 1.001
    return True, bool(locked_up), bool(locked_down)


def handle_bar(context, bar_dict):
    today = get_datetime().date()
    if not g.rebalance_pending or g.targets is None or g.submitted_date == today:
        return
    positions = context.portfolio.positions
    # 先提交退出和减仓，再提交新增仓位；平台仍按真实可用资金和撮合结果成交。
    for symbol in list(positions.keys()):
        target = float(g.targets.get(symbol, 0.0))
        tradable, _, locked_down = _trade_state(symbol, bar_dict)
        if tradable and not locked_down:
            order_target_percent(symbol, target)
    for symbol in g.targets:
        if symbol in positions:
            continue
        tradable, locked_up, _ = _trade_state(symbol, bar_dict)
        if tradable and not locked_up:
            order_target_percent(symbol, float(g.targets[symbol]))
    g.submitted_date = today
    g.rebalance_pending = False
    log.info("BASELINE1 monthly rebalance submitted targets=%d" % len(g.targets))


def after_trading(context):
    total = float(context.portfolio.stock_account.total_value)
    cash = float(context.portfolio.stock_account.available_cash)
    log.info("BASELINE1 nav=%.2f cash=%.2f holdings=%d" %
             (total, cash, len(context.portfolio.positions)))
