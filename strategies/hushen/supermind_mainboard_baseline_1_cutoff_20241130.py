# 沪深1：截止2024-11-30前数据的权重重估版。分钟频率，09:31执行，建议本金100000。
# 参数拟合及验证观测截止2024-11-29，未使用之后的行情或标签选参。
# R08框架曾用后续历史选优，因此不是完全独立的历史样本外实验。
# 训练结果是因子排名检验，不是组合年化收益；本版本尚未完成平台回测。
# 运行时可使用每个交易日之前的已知行情进行推断，权重不会在线重新训练。
from mindgo_api import *
import numpy as np
import pandas as pd

TRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'
DISTRIBUTION_WEIGHT = 0.3
MOMENTUM_WEIGHT = 0.2
LOW_VOL_WEIGHT = 0.5
TARGET_COUNT = 12
TARGET_EXPOSURE = 0.95
BUFFER_COUNT = 24
CANDIDATE_COUNT = 60
MIN_ADJUSTMENT = 1500.0
COMMISSION = 0.0003
MIN_FEE = 5.0
ONE_SIDE_SLIPPAGE = 0.002
HISTORY_BARS = 320


def ordinary_mainboard(symbol):
    return ((symbol.endswith('.SH') and symbol.startswith(('600', '601', '603', '605')))
            or (symbol.endswith('.SZ') and symbol.startswith(('000', '001', '002', '003'))))


def past_bars(frame, today):
    if frame is None or len(frame) == 0:
        return None
    x = frame.copy()
    x.index = pd.to_datetime(x.index)
    if x.index.has_duplicates:
        raise ValueError('duplicate historical dates')
    return x.loc[x.index.date < today].sort_index()


def rebalance_due(today, previous_month):
    key = today.year * 100 + today.month
    return previous_month is None or (key != previous_month and today.month % 2 == 1)


def stock_features(q, raw, market):
    """Same mathematical definitions as local rounds 01/04/08; no silent proxies."""
    if q is None or raw is None or len(q) < 250:
        return None
    required = ['close', 'prev_close', 'volume', 'turnover', 'turnover_rate', 'is_st', 'is_paused']
    if any(k not in raw for k in required):
        raise ValueError('missing raw fields; prev_close is mandatory')
    if 'close' not in q:
        raise ValueError('missing adjusted close')
    if q.index[-1] != market.index[-1] or raw.index[-1] != market.index[-1]:
        return None  # Stale/delisted history must not enter today's cross section.
    x = raw.apply(pd.to_numeric, errors='coerce')
    if x.is_st.iloc[-1] != 0 or x.is_paused.iloc[-1] != 0:
        return None
    # Reconstruct using only contemporaneous raw prices and ex-reference closes.
    ratio = x.close / x.prev_close
    c = ratio.where((ratio > 0) & np.isfinite(ratio)).cumprod()
    ret = c.pct_change(fill_method=None)
    vol20 = ret.rolling(20).std().iloc[-1]
    amount20 = x.turnover.rolling(20).mean().iloc[-1]
    if not np.isfinite(vol20) or not .001 <= vol20 <= .08 or not amount20 >= 50e6:
        return None
    # Local float-cap proxy: volume / (turnover percent / 100) * unadjusted close.
    turn = x.turnover_rate
    cap = (x.volume / (turn.where(turn > 0) / 100) * x.close).iloc[-1]
    event = x.close.shift(1) / x.prev_close - 1
    if x.prev_close.tail(250).isna().any() or (x.prev_close.tail(250) <= 0).any():
        raise ValueError('invalid prev_close; cannot compute distribution proxy')
    distribution = event.where(event.between(.0005, .08), 0).clip(upper=.04)
    distribution = distribution.rolling(250, min_periods=250).sum().iloc[-1]
    # Long risk is market-calendar based, ending 20 sessions before the signal day.
    a = np.log(c.reindex(market.index).where(lambda z: z > 0)).diff()
    b = np.log(market.where(market > 0)).diff()
    va = a.rolling(252, min_periods=220).var()
    vb = b.rolling(252, min_periods=220).var()
    beta = a.rolling(252, min_periods=220).cov(b) / vb
    mom = a.rolling(232, min_periods=220).sum().shift(20)
    bm = b.rolling(232, min_periods=220).sum().shift(20)
    risk = va.shift(20).clip(lower=1e-6).pow(.5) * np.sqrt(232)
    residual = (va - beta.pow(2) * vb).shift(20).clip(lower=1e-6).pow(.5) * np.sqrt(232)
    return dict(float_cap_proxy=cap, distribution_proxy=distribution,
                long_risk=(mom / risk).iloc[-1],
                market_adjusted=((mom - beta.shift(20) * bm) / residual).iloc[-1],
                vol60=ret.rolling(60).std().iloc[-1],
                ret5=(c / c.shift(5) - 1).iloc[-1],
                turn20=turn.rolling(20).mean().iloc[-1])


def rank_candidates(frame):
    q = frame.sort_values('symbol').copy().replace([np.inf, -np.inf], np.nan)
    # Group BEFORE dropping missing long-history features, as in local build_features.
    groups = np.minimum(np.floor(q.float_cap_proxy.rank(pct=True) * 3), 2)
    q = q.loc[groups == 1].dropna(subset=[
        'long_risk', 'market_adjusted', 'distribution_proxy', 'vol60', 'ret5', 'turn20'])
    q['score'] = (DISTRIBUTION_WEIGHT * q.distribution_proxy.rank(pct=True)
                  + MOMENTUM_WEIGHT * q.long_risk.rank(pct=True)
                  + LOW_VOL_WEIGHT * (1 - q.vol60.rank(pct=True)))
    return q.sort_values(['score', 'symbol'], ascending=[False, True]).head(CANDIDATE_COUNT)


def select_affordable(ranked, held, prices, equity):
    budget = max(0., equity * TARGET_EXPOSURE / TARGET_COUNT)
    retained = [s for s in held if s in set(ranked[:BUFFER_COUNT])]
    ordered = retained + [s for s in ranked if s not in retained]
    selected = []
    for s in ordered:
        price = prices.get(s, np.nan)
        if not np.isfinite(price) or price <= 0:
            continue
        value = price * 100 * (1 + ONE_SIDE_SLIPPAGE)
        if value + max(MIN_FEE, value * COMMISSION) > budget:
            continue
        selected.append(s)
        if len(selected) == TARGET_COUNT:
            break
    return selected


def build_ranking(today):
    bench_data = history(['000905.SH'], ['close'], HISTORY_BARS, '1d', False, None, True, False)
    bench = past_bars(bench_data.get('000905.SH'), today)
    if bench is None or len(bench) < 273:
        raise ValueError('insufficient benchmark history')
    market = pd.to_numeric(bench.close, errors='coerce')
    signal_date = market.index[-1]
    securities = get_all_securities('stock', signal_date.strftime('%Y%m%d'))
    symbols = sorted(s for s in securities.index if ordinary_mainboard(s))
    if len(symbols) < 500:
        raise ValueError('historical universe unexpectedly small')
    fields = ['close', 'prev_close', 'volume', 'turnover', 'turnover_rate', 'is_st', 'is_paused']
    rows, missing, bad = [], 0, 0
    for begin in range(0, len(symbols), 100):
        batch = symbols[begin:begin + 100]
        rdata = history(batch, fields, HISTORY_BARS, '1d', False, None, True, False)
        if not isinstance(rdata, dict):
            raise ValueError('history must return symbol -> DataFrame')
        for s in batch:
            raw = past_bars(rdata.get(s), today)
            q = raw  # history gate only; stock price chain is reconstructed in stock_features
            if q is None or raw is None:
                missing += 1
                continue
            try:
                ft = stock_features(q, raw, market)
            except ValueError:
                bad += 1
                continue
            if ft is not None:
                rows.append(dict(ft, symbol=s))
    # Do not quietly trade a different universe when the provider drops fields.
    if bad or missing > .05 * len(symbols) or len(rows) < 100:
        raise ValueError('data quality failed: universe=%d missing=%d bad_fields=%d eligible=%d'
                         % (len(symbols), missing, bad, len(rows)))
    ranked = rank_candidates(pd.DataFrame(rows))
    if len(ranked) < TARGET_COUNT:
        raise ValueError('fewer than 12 ranked candidates')
    log.info('R08 signal=%s universe=%d missing=%d eligible=%d top24=%s' % (
        str(signal_date.date()), len(symbols), missing, len(rows),
        str([(r['symbol'], round(r['score'], 6)) for r in ranked.head(24).to_dict('records')])))
    return list(ranked.symbol)


def init(context):
    g.last_month = None
    g.ranked = None
    g.pending_date = None
    g.holding_order = []
    set_benchmark('000905.SH')
    set_slippage(PriceSlippage(0.004))  # Official definition: half-spread +/-0.2%.
    set_commission(PerShare(type='stock', cost=COMMISSION, min_trade_cost=MIN_FEE))
    set_volume_limit(daily=.05, minute=.01)
    log.info('沪深1 cutoff20241130 weights=0.3/0.2/0.5 MINUTE required; 12 stocks,95% target,first entry then odd-month first session; tax uses platform rules')


def before_trading(context):
    today = get_datetime().date()
    due = rebalance_due(today, g.last_month)
    g.last_month = today.year * 100 + today.month
    g.pending_date = None
    g.ranked = None
    if due:
        try:
            g.ranked = build_ranking(today)
            g.pending_date = today
        except Exception as exc:
            # Keep old holdings; never substitute another factor or stale signal.
            log.warn('R08 SIGNAL_FAILED keep holdings, skip this rebalance: %s' % str(exc))


def trade_state(symbol, bars):
    try:
        bar = bars[symbol]
        price = float(bar.open)
        upper, lower = float(bar.high_limit), float(bar.low_limit)
        if bool(bar.is_paused) or not np.isfinite(price) or price <= 0 or float(bar.volume) <= 0:
            return None
        if not np.isfinite(upper) or not np.isfinite(lower):
            return None
        return price, price >= upper * .999, price <= lower * 1.001
    except Exception:
        return None


def handle_bar(context, bar_dict):
    now = get_datetime()
    if g.pending_date != now.date() or g.ranked is None:
        return
    if (now.hour, now.minute) != (9, 31):
        if now.hour >= 15:
            log.warn('R08 requires MINUTE frequency/09:31 callback; no daily-close substitution')
            g.pending_date = None
        return
    g.pending_date = None  # One attempt only, not daily rebalancing/retry.
    positions = context.portfolio.positions
    held = [s for s in g.holding_order if s in positions and positions[s].amount > 0]
    held += [s for s in positions if positions[s].amount > 0 and s not in held]
    equity = float(context.portfolio.stock_account.total_value)
    prices = {}
    for s in g.ranked:
        try:
            prices[s] = float(bar_dict[s].open)
        except Exception:
            pass
    selected = select_affordable(g.ranked, held, prices, equity)
    if not selected:
        log.warn('R08 no affordable candidates; keep holdings')
        return
    # Same local equal weighting + 1.5/count cap; <8 affordable stocks leaves cash.
    weight = TARGET_EXPOSURE * min(1. / len(selected), 1.5 / TARGET_COUNT)
    ordered = held + [s for s in selected if s not in held]
    sent = 0
    for s in ordered:
        state = trade_state(s, bar_dict)
        if state is None:
            continue
        price, locked_up, locked_down = state
        current = int(positions[s].amount) if s in positions else 0
        target = int(equity * (weight if s in selected else 0) / price / 100) * 100
        delta = target - current
        if current > 0 and target > 0 and abs(delta) * price < MIN_ADJUSTMENT:
            continue
        if abs(delta) < 100 or (delta > 0 and locked_up) or (delta < 0 and locked_down):
            continue
        if delta > 0:
            qty = int(delta // 100) * 100
            cash = float(context.portfolio.stock_account.available_cash)
            while qty >= 100:
                value = round(qty * price * (1 + ONE_SIDE_SLIPPAGE), 2)
                if value + round(max(MIN_FEE, value * COMMISSION), 2) <= cash:
                    break
                qty -= 100
            if qty < 100:
                continue
        else:
            qty = -min(-delta, int(positions[s].available_amount))  # T+1/platform locked shares.
            if qty == 0:
                continue
        result = order(s, qty)
        log.info('R08 ORDER %s qty=%d target=%d result=%s' % (s, qty, target, str(result)))
        sent += 1
    g.holding_order = ordered
    log.info('R08 selected=%s submitted=%d equity=%.2f' % (str(selected), sent, equity))


def after_trading(context):
    account = context.portfolio.stock_account
    positions = context.portfolio.positions
    log.info('R08 DAILY date=%s nav=%.2f cash=%.2f holdings=%d' % (
        str(get_datetime().date()), float(account.total_value), float(account.available_cash),
        sum(1 for s in positions if positions[s].amount > 0)))
