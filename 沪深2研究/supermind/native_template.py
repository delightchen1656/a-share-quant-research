# -*- coding: utf-8 -*-
"""SuperMind native execution adapter. Build into a single standalone file.

Use STOCK, MINUTE, 100000 initial cash, empty independent account.
Native fills/corporate actions differ from the frozen local daily-bar ledger.
No broker connection; no fitting; no embedded historical rankings.
"""
from mindgo_api import *
import math

BACKTEST_START='2020-01-02' # preferred start only; actual first callback is authoritative
BACKTEST_END='2024-12-31'
FEATURE_START='2018-01-01'
SLOTS=5
SLIP=.002
DAILY_CAPACITY=.02
FIELDS=['open','high','low','close','prev_close','volume','turnover','turnover_rate','is_paused','is_st']
BATCH_SIZE=150


def date_key(value):return pd.Timestamp(value).strftime('%Y-%m-%d')


def mainboard(s):
    return (s.endswith('.SH') and s[:3] in ('600','601','603','605')) or (s.endswith('.SZ') and s[:3] in ('000','001','002','003'))


def native_positions(context):
    return {s:p for s,p in context.portfolio.positions.items() if int(p.amount)>0}


def available_cash(context):
    # Preserve next-session reuse of sale proceeds despite native T+0 cash credit.
    return max(0.,float(context.portfolio.stock_account.available_cash)-g.sell_cash_today)


def account_equity(context):
    a=context.portfolio.stock_account
    return float(a.available_cash)+float(a.frozen_cash)+sum(float(p.amount)*float(p.last_price) for p in native_positions(context).values())


def occupied(context):
    return set(native_positions(context))|{p['symbol'] for p in g.pending}|{i['symbol'] for i in g.intents.values() if i['side']=='buy' and not i['terminal']}


def init(context):
    if BACKTEST_START<SIGNAL_START or BACKTEST_END<BACKTEST_START:
        raise ValueError('Use an interval starting in2020 or later, end>=start')
    g.models=load_models();g.members={};g.pending=[];g.terms={};g.intents={};g.submitting=None
    g.executions=set();g.sell_cash_today=0.;g.started=False;g.last_signal=None;g.native_days=0
    g.calendar=[date_key(d) for d in get_trade_days(start_date='20180101',end_date=(pd.Timestamp(BACKTEST_END)+pd.Timedelta(days=90)).strftime('%Y%m%d'))]
    g.first=next(d for d in g.calendar if d>=BACKTEST_START)
    g.last=max(d for d in g.calendar if d<=BACKTEST_END)
    g.last_signal_cutoff=date_key(pd.Timestamp(BACKTEST_END)-pd.Timedelta(days=37))
    set_benchmark('000001.SH')
    set_commission(PerShare(type='stock',cost=.0003,min_trade_cost=5.))
    set_slippage(PriceSlippage(0.0)) # price tolerance below; actual fill remains native
    set_volume_limit(daily=DAILY_CAPACITY,minute=1.0)
    enable_open_bar()
    if native_positions(context):raise RuntimeError('Independent empty-start account required')
    log.info('HUSHEN2_NATIVE: MINUTE only,100000 CNY; platform fills, not exact local daily ledger')
    log.info('DIFFERENCES: minute sampling/double-touch order, native IOC emulation, native tax/dividends, data vendor/qfq, expiry14:59')


def before_trading(context):
    day=date_key(get_datetime());g.today=day;g.sell_cash_today=0.;g.bar_callbacks_today=0
    if not g.started:
        if day<SIGNAL_START or day>g.last:
            raise RuntimeError('Actual first session %s is outside supported interval %s..%s'%(day,SIGNAL_START,g.last))
        if native_positions(context):raise RuntimeError('First callback requires an empty account')
        if abs(account_equity(context)-100000)>0.01:raise RuntimeError('Set initial cash=100000')
        g.actual_start=day
        log.info('ACTUAL_START %s configured_hint=%s END=%s; no earlier orders replayed'%(day,BACKTEST_START,BACKTEST_END))
        g.started=True
    if day>g.last:raise RuntimeError('Platform end date exceeds BACKTEST_END')
    foreign=set(native_positions(context))-set(g.terms)
    if foreign:raise RuntimeError('Unmanaged holdings: '+str(sorted(foreign)))
    g.pending=[p for p in g.pending if day<=p['expiry']]
    for s,p in native_positions(context).items():
        term=g.terms[s];quantity=int(p.amount)
        if quantity!=term['quantity']:
            ratio=quantity/float(term['quantity'])
            term['take']/=ratio;term['stop']/=ratio;term['quantity']=quantity
            log.info('NATIVE_SHARE_ACTION %s ratio=%s; native release/tax rules apply'%(s,ratio))
    for i in g.intents.values():i['terminal']=True # stock day orders expire overnight
    subscribe(sorted(occupied(context)|{'000001.SH'}))


def normalize_quotes(symbol,frame,asof):
    if frame is None or frame.empty:return None
    x=frame.copy();x.index=pd.DatetimeIndex(x.index).normalize()
    if x.index.duplicated().any():raise RuntimeError('Duplicate quote dates '+symbol)
    x=x.loc[(x.index>=pd.Timestamp(FEATURE_START))&(x.index<=pd.Timestamp(asof))].sort_index()
    if x.empty:return None
    if any(k not in x for k in FIELDS):raise RuntimeError('Required quote fields missing '+symbol)
    x=x[FIELDS].apply(pd.to_numeric,errors='raise')
    x=x.rename(columns={'prev_close':'preclose','turnover':'amount','turnover_rate':'turn','is_st':'isST'})
    x['tradestatus']=1-x['is_paused'];x['date']=x.index;x['symbol']=symbol
    return x.reset_index(drop=True)


def platform_signal_panel(asof):
    # Historical membership at EACH score date; no present-day survivor universe.
    dates=[d for d in g.calendar if SIGNAL_START<=d<=asof]
    for d in dates:
        if d not in g.members:
            table=get_all_securities('stock',date=d.replace('-',''))
            g.members[d]=set(s for s in table.index if mainboard(s))
    symbols=sorted(set().union(*(g.members[d] for d in dates)))
    frames=[];raw_last={};n=0
    # Full causal history keeps the five eligible-observation H smoother intact.
    # Full refresh also avoids splicing incompatible dynamic-qfq vintages.
    for begin in range(0,len(symbols),BATCH_SIZE):
        group=symbols[begin:begin+BATCH_SIZE]
        data=get_price(group,FEATURE_START,asof,'1d',FIELDS,False,'pre',0,False)
        if not isinstance(data,dict):raise RuntimeError('get_price(list) must return dict')
        raw=get_price(group,None,asof,'1d',['close','is_paused'],False,None,1,False)
        if not isinstance(raw,dict):raise RuntimeError('Unadjusted get_price(list) must return dict')
        for s in group:
            b=normalize_quotes(s,data.get(s),asof)
            if b is None:
                if s in g.members[asof]:raise RuntimeError('Listed security has no history '+s)
                continue
            if s in g.members[asof] and date_key(b.date.iloc[-1])!=asof:
                raise RuntimeError('Active security missing latest bar '+s)
            f=model_features(b)
            if len(f):
                f=f.loc[[s in g.members.get(date_key(d),set()) for d in f.date]]
                if len(f):frames.append(f)
            q=raw.get(s)
            if q is not None and len(q) and date_key(q.index[-1])==asof and not bool(q.is_paused.iloc[-1]):
                raw_last[s]=float(q.close.iloc[-1])
            n+=1
        if begin%(BATCH_SIZE*5)==0:log.info('SIGNAL_HISTORY %s symbols=%s/%s'%(asof,n,len(symbols)))
    if not frames:raise RuntimeError('No eligible feature panel')
    panel=pd.concat(frames,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    if panel.date.max()>pd.Timestamp(asof):raise RuntimeError('Future data rejected')
    return panel,raw_last


def after_trading(context):
    day=date_key(get_datetime());g.native_days+=1
    if g.bar_callbacks_today<2:raise RuntimeError('Select MINUTE frequency; daily callbacks cannot implement this adapter')
    # First-day orders use this close, never the previous day's unowned signals.
    if day<=g.last_signal_cutoff and g.last_signal!=day:
        panel,closes=platform_signal_panel(day)
        signals=frozen_signals(panel,g.models);signals=signals.loc[signals.date.eq(pd.Timestamp(day))]
        used=occupied(context);budget=account_equity(context)/SLOTS
        for r in signals.itertuples():
            if r.symbol in used or len(used)>=SLOTS:continue
            if r.symbol not in closes:raise RuntimeError('Missing unadjusted signal close '+r.symbol)
            target=closes[r.symbol];quantity=int(budget//(target*(1+SLIP)*100))*100
            g.pending.append(dict(symbol=r.symbol,signal_date=day,expiry=date_key(pd.Timestamp(day)+pd.Timedelta(days=7)),
                target=target,atr=float(r.atr_pct),score=float(r.score),budget=budget,quantity=quantity))
            used.add(r.symbol)
            log.info('PENDING '+json.dumps(g.pending[-1],sort_keys=True))
        g.last_signal=day
    record(native_equity=account_equity(context),pending_slots=len(g.pending),held_slots=len(native_positions(context)))
    log.info('DAILY %s equity=%.2f pending=%s held=%s'%(day,account_equity(context),len(g.pending),len(native_positions(context))))


def bar_values(bar):
    if bar is None or bool(bar.is_paused):return None
    values=[float(bar.open),float(bar.high),float(bar.low),float(bar.close)]
    if not all(np.isfinite(v) and v>0 for v in values):return None
    return values


def read_bar(bar_dict,symbol):
    try:return bar_dict[symbol]
    except KeyError:return None


def submit_ioc(symbol,quantity,side,term,limit):
    intent=dict(symbol=symbol,requested=abs(quantity),side=side,term=term,filled=0,notional=0.,terminal=False)
    g.submitting=intent
    try:oid=order(symbol,int(quantity),price=float(limit))
    finally:g.submitting=None
    if oid is None:
        intent['terminal']=True;log.info('NATIVE_REJECT %s side=%s qty=%s'%(symbol,side,quantity));return
    oid=str(oid);g.intents[oid]=intent
    # Native API has no five-level IOC; cancel only OUR remaining quantity.
    orders=get_orders(oid) or []
    if not orders:cancel_order(oid) # ambiguous receipt: do not leave a resting order
    for o in orders:
        if int(o.amount)!=abs(quantity):
            cancel_order(oid)
            raise RuntimeError('Native order changed fixed quantity: requested=%s native=%s'%(abs(quantity),o.amount))
        if int(o.filled_amount)<int(o.amount):cancel_order(oid)
    log.info('NATIVE_ATTEMPT %s side=%s requested=%s order=%s'%(symbol,side,abs(quantity),oid))


def handle_bar(context,bar_dict):
    stamp=pd.Timestamp(get_datetime());day=date_key(stamp)
    g.bar_callbacks_today+=1
    # Minute bars are observed only at their timestamps. Never inspect a future day bar.
    for s,p in list(native_positions(context).items()):
        term=g.terms[s]
        if day<=term['entry_date'] or term.get('exit_attempt_day')==day:continue
        values=bar_values(read_bar(bar_dict,s))
        if values is None:continue
        opn,high,low,close=values
        reason='stop' if low<=term['stop'] else 'take' if high>=term['take'] else None
        if reason is None and day>=term['expiry_session'] and (stamp.hour,stamp.minute)>=(14,59):reason='expiry'
        if not reason:continue
        quantity=min(int(p.amount),int(p.available_amount))
        if quantity<=0:continue
        term['exit_attempt_day']=day;term['exit_reason']=reason
        limit=max(float(bar_dict[s].low_limit),math.floor(close*(1-SLIP)*100+1e-8)/100)
        submit_ioc(s,-quantity,'sell',term,limit)
    for p in list(g.pending):
        if day<=p['signal_date'] or day>p['expiry']:continue
        values=bar_values(read_bar(bar_dict,p['symbol']))
        if values is None:continue
        opn,high,low,close=values
        # Current sampled price, not a retroactive fill at an earlier minute low.
        sampled=opn if (stamp.hour,stamp.minute)==(9,30) else close
        if sampled>p['target']:continue
        g.pending.remove(p) # one fixed-share attempt; remainder is cancelled
        quantity=p['quantity']
        limit=min(float(bar_dict[p['symbol']].high_limit),math.ceil(sampled*(1+SLIP)*100-1e-8)/100)
        cost=quantity*limit+max(5.,quantity*limit*.0003)
        if quantity<100 or cost>available_cash(context)+1e-9:
            log.info('FIXED_BUY_REJECT %s quantity=%s reason=cash_or_lot'%(p['symbol'],quantity));continue
        submit_ioc(p['symbol'],quantity,'buy',p,limit)


def find_intent(oid,symbol):
    intent=g.intents.get(str(oid))
    if intent is None and g.submitting is not None and g.submitting['symbol']==symbol:
        intent=g.submitting;g.intents[str(oid)]=intent
    return intent


def on_order(context,odr):
    intent=find_intent(odr.order_id,odr.symbol)
    if intent is None:return
    status=str(odr.status).upper()
    intent['terminal']=any(s in status for s in ('FILLED','CANCELLED','CANCELED','REJECTED')) and 'PARTIALLY' not in status
    log.info('ORDER '+str(odr))


def on_trade(context,trade):
    symbol=trade.order_book_id;intent=find_intent(trade.order_id,symbol)
    if intent is None:return
    key=str(trade.exec_id)
    if key in g.executions:return
    g.executions.add(key)
    quantity=abs(int(trade.last_quantity));price=float(trade.last_price)
    intent['filled']+=quantity;intent['notional']+=quantity*price
    if intent['side']=='buy':
        p=intent['term'];entry=date_key(trade.trading_datetime);deadline=date_key(pd.Timestamp(entry)+pd.Timedelta(days=30))
        average=intent['notional']/intent['filled']
        g.terms[symbol]=dict(entry_date=entry,deadline=deadline,expiry_session=max(d for d in g.calendar if d<=deadline),
            quantity=intent['filled'],take=average*(1+4*p['atr']),stop=average*(1-1.5*p['atr']),atr=p['atr'])
    else:
        g.sell_cash_today+=quantity*price-float(trade.commission)-float(trade.tax)
        g.terms[symbol]['quantity']-=quantity
        if g.terms[symbol]['quantity']==0:del g.terms[symbol]
    log.info('FILL '+str(trade))
