"""Generate standalone SuperMind strategy from established platform adapter."""
import ast
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=HERE/'supermind_mainboard_baseline_2_pending1.py'

RANK='''def _rank_candidates(frame, strong):
    x = frame.sort_values("symbol").copy()
    if strong:
        x["score"] = (.25 * _rank01(x.amount20, True)
                      + .20 * _rank01(x.near_high)
                      + .55 * _rank01(x.dividend))
    else:
        # Same cross-sectional tercile definition as local research.
        pct = x.float_cap_proxy.rank(pct=True)
        group = np.minimum(np.floor(pct * 3), 2)
        x = x[group == 1].copy()
        x["score"] = (.55 * x.dividend.rank(pct=True)
                      + .30 * (1 - x.downside.rank(pct=True))
                      + .15 * (1 - x.turn20.rank(pct=True)))
    return x.dropna(subset=["score"]).sort_values(
        ["score", "symbol"], ascending=[False, True])


def _group_features(raw):
    if raw is None or len(raw) < 20:
        return None
    required = ["close", "volume", "turnover_rate"]
    if any(c not in raw.columns for c in required):
        return None
    x = raw.sort_index()
    turn = pd.to_numeric(x["turnover_rate"], errors="coerce")
    volume = float(x["volume"].iloc[-1])
    close = float(x["close"].iloc[-1])
    last = float(turn.iloc[-1])
    turn20 = float(turn.tail(20).mean())
    if not np.all(np.isfinite([volume, close, last, turn20])) or min(volume, close, last) <= 0:
        return None
    # A uniform unit scale does not change cap terciles or turnover ranks.
    return {"float_cap_proxy": volume / (last / 100.) * close, "turn20": turn20}


'''

HANDLE='''def handle_bar(context, bar_dict):
    today = get_datetime().date()
    if not g.rebalance_pending or g.targets is None or g.submitted_date == today:
        return
    positions = context.portfolio.positions
    equity = float(context.portfolio.stock_account.total_value)
    # Preserve local old-positions-first sequence. Use direction-specific locks.
    ordered = list(positions.keys()) + [s for s in g.targets if s not in positions]
    for symbol in ordered:
        tradable, locked_up, locked_down = _trade_state(symbol, bar_dict)
        if not tradable:
            continue
        price = float(bar_dict[symbol].open)
        current = float(positions[symbol].amount) if symbol in positions else 0.
        target = float(g.targets.get(symbol, 0.))
        target_qty = int(equity * target / price / 100.) * 100
        delta = target_qty - current
        if current > 0 and target_qty > 0 and abs(delta) * price < 3000:
            continue
        if abs(delta) < 100 or (delta > 0 and locked_up) or (delta < 0 and locked_down):
            continue
        order_target_percent(symbol, target)
    g.submitted_date = today
    g.rebalance_pending = False
    log.info("HS_BASELINE2 rebalance submitted targets=%d" % len(g.targets))


'''

def main():
 src=(HERE/'small_account_100k/supermind_baseline2_100k.py').read_text(encoding='utf-8')
 src=src.replace('TARGET_COUNT = 10','TARGET_COUNT = 8').replace('BUFFER_COUNT = 30','BUFFER_COUNT = 24')
 src=src.replace('# 沪深基准2 deep_reversal_20_0.8：状态切换红利反转（SuperMind 收益优化V2）','# 沪深基准2：顺势防守8（本地基准2待定1的移植版）')
 src=src.replace('沪深基准2 deep_reversal_20_0.8 状态切换红利反转 收益优化V2','沪深基准2 顺势防守8')
 src=src.replace('保证组合权重之和为95%','目标总仓位为80%')
 src=src.replace('    symbols = g.universe','    symbols = sorted(g.universe)')
 src=src.replace('        for symbol in batch:\n', '        group_raw = history(batch, ["close", "volume", "turnover_rate"], 20, "1d", False, None, True, False)\n        for symbol in batch:\n',1)
 src=src.replace('            if ft is not None:\n                rows.append((symbol, ft))','            if ft is not None:\n                extra = _group_features(group_raw.get(symbol) if isinstance(group_raw, dict) else None)\n                if extra is None:\n                    extra = {"float_cap_proxy": np.nan, "turn20": np.nan}\n                ft.update(extra)\n                rows.append((symbol, ft))')
 start=src.index('    low_amount = _rank01',src.index('def _build_targets'))
 end=src.index('    buffer_symbols =',start)
 src=src[:start]+'''    frame = pd.DataFrame([dict(ft, symbol=s) for s, ft in rows])
    if not strong and frame.float_cap_proxy.notna().mean() < .95:
        log.warn("HS_BASELINE2 turnover/cap data missing; skip rebalance, do not change rule")
        return None
    ranked = _rank_candidates(frame, strong)
    if len(ranked) < TARGET_COUNT:
        log.warn("HS_BASELINE2 fewer than 8 eligible stocks; skip rebalance")
        return None
    rows = [(r["symbol"], r) for r in ranked.to_dict("records")]
    order = list(range(len(rows)))
'''+src[end:]
 src=src.replace('def _build_targets(context):',RANK+'def _build_targets(context):')
 start=src.index('def handle_bar(');end=src.index('def after_trading(',start)
 src=src[:start]+HANDLE+src[end:]
 src=src.replace('BASELINE2 monthly','HS_BASELINE2 quarterly')
 ast.parse(src);OUT.write_text(src,encoding='utf-8')
 print(OUT)

if __name__=='__main__':main()
