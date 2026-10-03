"""Isolated execution proxy: inherited rules, cent rounding and prepared-panel speedup.
No platform holdings or realized execution prices are injected as strategy inputs.
Minute bars are unavailable; day-open and daily-volume approximations remain.
"""
from execution_engine import *
import execution_engine as original
PREPARED = None
CALENDAR = None
ROUND_FEES = True
SELECTION_TRACE = None
ACTION_MODE = 'legacy'
STRICT_TARGET = False
SELECTOR = None
SELECTOR_CONTEXT = None  # Opt-in only; previous studies retain identical defaults.
DELISTINGS = {}
DELISTING_EVENTS = []
ACTION_LEDGER = {}
RECEIVABLES = []
LOCKED_BONUS = []
UNRESOLVED_ACTIONS = []

def money(value):
    return round(float(value), 2) if ROUND_FEES else value

def commission(value):
    return money(max(MIN_COMMISSION, value * COMMISSION))

def trading_calendar():
    if CALENDAR is None:
        idx = pd.read_parquet(DATA / "indices" / "000905.SH.parquet", columns=["date"])
        dates = pd.DatetimeIndex(pd.to_datetime(idx.date).sort_values().unique())
    else:
        dates = CALENDAR
    return dates[(dates >= START) & (dates <= END)]

def apply_corporate_action(cash, positions, day, previous_close):
    if ACTION_MODE == 'ledger':
        return ledger_action(cash, positions, day, previous_close)
    cash = original.apply_corporate_action(cash, positions, day, previous_close)
    for s, qty in positions.items():
        if s not in day.index or s not in previous_close:
            continue
        pre = float(day.loc[s, "preclose"])
        if np.isfinite(pre) and pre > 0 and 1+1e-8 < previous_close[s]/pre <= 1.02:
            cash += qty * (previous_close[s]-pre)
    return cash

def receivable_value():
    return sum(x['value'] for x in RECEIVABLES)

def ledger_action(cash, positions, day, previous_close):
    global RECEIVABLES, LOCKED_BONUS
    if day.empty:
        return cash
    date = pd.Timestamp(day.date.iloc[0])
    cash += sum(x['value'] for x in RECEIVABLES if x['date'] <= date)
    RECEIVABLES = [x for x in RECEIVABLES if x['date'] > date]
    LOCKED_BONUS = [x for x in LOCKED_BONUS if x['date'] > date]
    for symbol, qty in list(positions.items()):
        if symbol not in day.index or symbol not in previous_close:
            continue
        event = ACTION_LEDGER.get((date, symbol))
        if event is not None:
            value = money(qty * event['cash'])
            if event['pay_date'] <= date:
                cash += value
            elif value:
                RECEIVABLES.append(dict(date=event['pay_date'], value=value))
            added = int(np.floor(qty * event['bonus'] + 1e-8))
            if added:
                positions[symbol] += added
                if event['stock_date'] > date:
                    LOCKED_BONUS.append(dict(symbol=symbol, quantity=added, date=event['stock_date']))
            continue
        pre = float(day.loc[symbol, 'preclose'])
        if not np.isfinite(pre) or pre <= 0:
            continue
        ratio = previous_close[symbol] / pre
        if 1+1e-8 < ratio < 1.05:
            # Small cash-action proxy retained; never infer newly created shares.
            cash += money(qty * (previous_close[symbol] - pre))
        elif ratio >= 1.05 or ratio <= .95:
            # A large unexplained adjustment is not permission to create cash/shares.
            UNRESOLVED_ACTIONS.append(dict(date=str(date.date()),symbol=symbol,ratio=ratio))
    return cash

def simulate(ranks: dict[pd.Timestamp, pd.DataFrame], volume_limit: float,
             target_count: int = TARGET_COUNT, buffer_count: int = BUFFER_COUNT,
             target_exposure: float = TARGET_EXPOSURE,
             max_single_multiple: float = MAX_SINGLE_MULTIPLE,
             panel: pd.DataFrame | None = None,
             min_adjustment: float = 0.0,
             risk_only_limits: dict | None = None,
             ) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_symbols = set()
    for x in ranks.values():
        candidate_symbols.update(x.head(buffer_count).symbol)
    if PREPARED is not None:
        by_date = PREPARED
    else:
        if panel is None:
            panel = load_daily_panel(candidate_symbols)
        else:
            panel = panel[panel.symbol.isin(candidate_symbols)].copy()
        by_date = {pd.Timestamp(d): x.set_index("symbol") for d, x in panel.groupby("date")}
    dates = trading_calendar()
    cash = INITIAL_CASH
    positions: dict[str, int] = {}
    previous_close: dict[str, float] = {}
    curve, trades = [], []
    for date in dates:
        date = pd.Timestamp(date)
        day = by_date.get(date, pd.DataFrame())
        cash = apply_corporate_action(cash, positions, day, previous_close)
        # Conservative terminal valuation, not a fictional fill at the last quote.
        # Future delisting dates never exclude a stock from earlier selection.
        for symbol in list(positions):
            if symbol in DELISTINGS and date >= DELISTINGS[symbol]:
                DELISTING_EVENTS.append(dict(date=str(date.date()),symbol=symbol,quantity=positions[symbol],last_mark=previous_close.get(symbol)))
                positions.pop(symbol)
        if date in ranks:
            ranked = ranks[date]
            buffer_symbols = ranked.head(buffer_count).symbol.tolist()
            retained = [s for s in positions if s in buffer_symbols]
            selected = retained[:target_count]
            for symbol in ranked.symbol:
                if STRICT_TARGET and len(selected) >= target_count:
                    break
                if symbol not in selected:
                    selected.append(symbol)
                if len(selected) >= target_count:
                    break
            if SELECTOR is not None:
                selected = SELECTOR(date, ranked, positions, target_count, buffer_count)
                assert len(selected)==len(set(selected)) and len(selected)<=target_count
                assert set(selected).issubset(set(ranked.symbol))
            if SELECTOR_CONTEXT is not None:
                prices = {s:float(day.loc[s,'open']) for s in set(ranked.symbol)|set(positions)
                          if s in day.index and np.isfinite(day.loc[s,'open']) and float(day.loc[s,'open'])>0}
                nav_now = cash + receivable_value() + sum(q*prices.get(s,previous_close.get(s,0.)) for s,q in positions.items())
                exp_now = target_exposure[date] if isinstance(target_exposure,dict) else target_exposure
                context = dict(equity=nav_now,cash=cash,prices=prices,exposure=exp_now,
                               lot=LOT,slippage=SLIPPAGE,commission=COMMISSION,min_commission=MIN_COMMISSION)
                selected = SELECTOR_CONTEXT(date,ranked,positions,target_count,buffer_count,context)
                assert len(selected)==len(set(selected)) and len(selected)<=target_count
                assert set(selected).issubset(set(ranked.symbol))
            ds = ranked.set_index("symbol").downside.to_dict()
            inv = np.array([1/ds[s] for s in selected], dtype=float)
            weights = inv/inv.sum()
            cap = max_single_multiple/target_count
            for _ in range(10):
                above = weights > cap
                if not above.any():
                    break
                fixed = np.minimum(weights[above], cap).sum()
                weights[above] = cap
                free = ~above
                if free.any():
                    weights[free] = weights[free]/weights[free].sum()*(1-fixed)
            exposure_today = target_exposure[date] if isinstance(target_exposure, dict) else target_exposure
            if not 0 <= exposure_today <= 1:
                raise ValueError('Target exposure must be between zero and one')
            targets = dict(zip(selected, weights*exposure_today))
            if SELECTION_TRACE is not None and not (risk_only_limits and date in risk_only_limits):
                SELECTION_TRACE.append(dict(date=str(date.date()), selected=list(selected), targets=targets))
            open_equity = cash + receivable_value() + sum(q*(float(day.loc[s, "open"]) if s in day.index and np.isfinite(day.loc[s, "open"]) else previous_close.get(s,0.)) for s,q in positions.items())
            risk_only = risk_only_limits is not None and date in risk_only_limits
            if risk_only:
                # Research-only sell-only risk check; no stock replacement or recovery buys.
                limit = risk_only_limits[date]
                if not 0 <= limit <= 1:
                    raise ValueError('Risk-only limit must be between zero and one')
                stock_value = open_equity - cash - receivable_value()
                if stock_value <= open_equity * limit or stock_value <= 0:
                    continue_risk = True
                else:
                    continue_risk = False
                targets = {s: (q * float(day.loc[s, 'open']) / stock_value * limit)
                           for s, q in positions.items()
                           if s in day.index and np.isfinite(day.loc[s, 'open'])}
                selected = list(positions)
            # 与平台代码一致：旧持仓先处理，再处理首次买入。
            ordered = list(positions) + [s for s in selected if s not in positions]
            for symbol in ordered:
                if symbol not in day.index:
                    continue
                row = day.loc[symbol]
                if str(row.tradestatus) != "1" or float(row.open) <= 0 or float(row.volume) <= 0:
                    continue
                target_weight = targets.get(symbol, 0.0)
                target_qty = int(open_equity*target_weight/float(row.open)/LOT)*LOT
                current = positions.get(symbol, 0)
                if risk_only:
                    if continue_risk:
                        continue
                    target_qty = min(target_qty, current)
                delta = target_qty-current
                # Suppress small top-ups/trims; never suppress a full exit.
                if current > 0 and target_qty > 0 and abs(delta)*float(row.open) < min_adjustment:
                    continue
                if delta == 0:
                    continue
                limit_qty = int(float(row.volume)*volume_limit/LOT)*LOT
                qty = min(abs(delta), limit_qty)
                if qty < LOT:
                    continue
                side = "BUY" if delta > 0 else "SELL"
                if side == 'BUY':
                    qty = int(qty // LOT) * LOT
                    if qty < LOT:
                        continue
                # 日频09:31的开盘封板判断。
                rate = .05 if str(row.isST) == "1" else .10
                upper = np.floor(float(row.preclose)*(1+rate)*100+.5)/100
                lower = np.floor(float(row.preclose)*(1-rate)*100+.5)/100
                if side == "BUY" and float(row.open) >= upper*.999:
                    continue
                if side == "SELL" and float(row.open) <= lower*1.001:
                    continue
                fill = float(row.open)*(1+SLIPPAGE if side == "BUY" else 1-SLIPPAGE)
                value = money(qty*fill)
                fee = commission(value)
                tax = 0.0 if side == "BUY" else money(value*STAMP_TAX)
                if side == "BUY":
                    while qty >= LOT and value+fee > cash:
                        qty -= LOT
                        value = money(qty*fill)
                        fee = commission(value) if qty else 0
                    if qty < LOT:
                        continue
                    cash -= value+fee
                    positions[symbol] = current+qty
                else:
                    locked = sum(x['quantity'] for x in LOCKED_BONUS if x['symbol'] == symbol)
                    qty = min(qty, max(0, current-locked))
                    if qty <= 0:
                        continue
                    value = money(qty*fill)
                    fee, tax = commission(value), money(value*STAMP_TAX)
                    cash += value-fee-tax
                    remain = current-qty
                    if remain:
                        positions[symbol] = remain
                    else:
                        positions.pop(symbol, None)
                trades.append({"date": date, "time": "09:31:00", "symbol": symbol,
                               "side": side, "fill_price": fill, "quantity": qty,
                               "amount": value, "commission": fee, "stamp_tax": tax})
        close_equity = cash + receivable_value()
        for symbol, qty in positions.items():
            if symbol in day.index and np.isfinite(day.loc[symbol, "close"]):
                close_equity += qty*float(day.loc[symbol, "close"])
                previous_close[symbol] = float(day.loc[symbol, "close"])
            elif symbol in previous_close:
                close_equity += qty*previous_close[symbol]
        curve.append({"date": date, "equity": close_equity, "cash": cash,
                      "stock_value":close_equity-cash-receivable_value(),
                      "holdings": len(positions)})
    return pd.DataFrame(curve), pd.DataFrame(trades)
