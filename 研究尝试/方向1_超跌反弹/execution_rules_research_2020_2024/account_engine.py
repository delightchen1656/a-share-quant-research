"""Frozen daily account engineering; no input I/O, signal generation or tuning.

All monetary settlements use Decimal ROUND_HALF_UP to fen. Share ownership,
stock availability, receivables and sold/unsold dividend tax are separate.
"""
from dataclasses import dataclass,field
from decimal import Decimal,ROUND_HALF_UP,ROUND_CEILING
from collections import defaultdict
import pandas as pd

CENT=Decimal('.01');ZERO=Decimal('0.00')

def dec(x):return x if isinstance(x,Decimal) else Decimal(str(x))
def money(x):return dec(x).quantize(CENT,rounding=ROUND_HALF_UP)
def ceil_price(x):return dec(x).quantize(CENT,rounding=ROUND_CEILING)
def fee(gross,day,sell=False):
    gross=dec(gross)
    c=money(max(Decimal('5'),gross*Decimal('.0003')))
    t=money(gross*(Decimal('.00001') if day>='2022-04-29' else Decimal('.00002')))
    s=money(gross*(Decimal('.0005') if day>='2023-08-28' else Decimal('.001'))) if sell else ZERO
    return dict(commission=c,transfer=t,stamp=s,total=c+t+s)

def dividend_rate(acquired,asof):
    """Holding interval [acquired, sale/asof); calendar anniversary convention."""
    b=pd.Timestamp(acquired);s=pd.Timestamp(asof)
    if s<b:raise ValueError('Negative holding period')
    if s<=b+pd.DateOffset(months=1):return Decimal('.20')
    if s<=b+pd.DateOffset(years=1):return Decimal('.10')
    return Decimal('0')

def fit_shares(budget,price,day):
    budget=dec(budget);price=dec(price)
    if price<=0:raise ValueError('Nonpositive entry price')
    q=int(budget/price/100)*100
    while q>0 and money(q*price)+fee(q*price,day)['total']>budget:q-=100
    return q

class AuditBlocked(RuntimeError):
    def __init__(self,message,**details):
        super().__init__(message);self.details=details

@dataclass
class Bar:
    open:object
    high:object
    low:object
    close:object
    tradestatus:int=1
    volume:object=1
    lower_limit:object=None
    upper_limit:object=None
    no_price_limit:bool=False
    limit_evidence:str=''

    def active(self):return int(self.tradestatus)==1 and dec(self.volume)>0 and dec(self.open)>0

@dataclass
class Action:
    action_id:str
    code:str
    record_date:str
    ex_date:str
    cash_ps:object=0
    bonus_ps:object=0
    reserve_ps:object=0
    pay_date:str=None
    stock_release_date:str=None
    stock_acquisition_date:str=None
    taxable_stock_income_ps:object=None
    reference_price:object=None
    verified:bool=False
    unresolved_fields:list=field(default_factory=list)
    evidence:str=''

@dataclass
class Lot:
    lot_id:str
    qty:int
    acquired:str
    release:str

@dataclass
class TaxClaim:
    action_id:str
    lot_id:str
    acquired:str
    taxable_income:Decimal

@dataclass
class Position:
    code:str
    name:str
    signal_date:str
    buy_date:str
    due_date:str
    buy_price:Decimal
    buy_qty:int
    buy_gross:Decimal
    buy_fee:Decimal
    last_price:Decimal
    last_factor:float
    lots:list=field(default_factory=list)
    claims:list=field(default_factory=list)
    dividend_gross:Decimal=ZERO
    corporate_events:int=0
    pending_exit:str=None
    first_exit_intent:str=None
    pending_factor_action:bool=False
    trailing_wealth:Decimal=ZERO

    def qty(self):return sum(x.qty for x in self.lots)
    def unlocked(self,day):return all(x.release<=day for x in self.lots)
    def estimated_tax(self,day):return sum((money(x.taxable_income*dividend_rate(x.acquired,day)) for x in self.claims),ZERO)

def run_account(signals,calendar,bars,factors,actions,coverage,start_date,end_date,
                *,scope='all',verified_suspensions=None,policy_verified=False,tp=.20,sl=None,horizon=20,rank='code',trail=False,retain_unknown_quotes=False):
    """Return in-memory audit tables. Caller freezes/hashes and serializes inputs.

    signals: iterable dict(code,name,date,is_leader[,entry_date]); calendar full
    official dates; bars[code][day] Bar, including status=0 rows if available.
    factors[code][day] qfq/raw ratio on valid rows; coverage={(code,year)}.
    verified_suspensions={(code,day)} requires documented external status evidence.
    Only frozen values capital=1m, slots=20, budget=50k, TP=.20, B20 are used.
    """
    if not policy_verified:raise AuditBlocked('Caller must confirm frozen tax/limit/fee policy and evidence')
    if scope not in ('all','leaders'):raise ValueError('Unknown scope')
    dates=list(calendar)
    if dates!=sorted(set(dates)):raise AuditBlocked('Calendar not strictly unique/sorted')
    ordinal={d:i for i,d in enumerate(dates)}
    days=[d for d in dates if start_date<=d<=end_date]
    if not days:raise AuditBlocked('No account dates')
    verified_suspensions=set(verified_suspensions or [])
    action_list=list(actions)
    if len({x.action_id for x in action_list})!=len(action_list):raise AuditBlocked('Duplicate action IDs')
    at_record=defaultdict(list);at_ex=defaultdict(list)
    for a in action_list:
        if a.record_date:at_record[a.record_date].append(a)
        at_ex[a.ex_date].append(a)
    schedule=defaultdict(list);pending_signals=[];signal_keys=set()
    for e0 in signals:
        e=dict(e0)
        if scope=='leaders' and not bool(e.get('is_leader',False)):continue
        key=(e['code'],e['date'])
        if key in signal_keys:raise AuditBlocked('Duplicate signal '+str(key))
        signal_keys.add(key)
        if e['date'] not in ordinal:raise AuditBlocked('Signal missing from official calendar '+str(key))
        j=ordinal[e['date']]+1
        if j>=len(dates) or dates[j]>end_date:
            if start_date<=e['date']<=end_date:pending_signals.append(e)
            continue
        day=dates[j]
        if e.get('entry_date') and e['entry_date']!=day:raise AuditBlocked('Entry is not strict next official session')
        if start_date<=day<=end_date:schedule[day].append(e)
    cash=Decimal('1000000.00');sold_tax=ZERO;unresolved_quotes=[]
    positions={};receivables={};entitlements={};journal=[];nav=[];trades=[];skips=[];delays=[];corporate=[];tax_assessments=[]

    def receive_total():return sum((x['amount'] for x in receivables.values()),ZERO)
    def record(day,phase,kind,code='',cash_delta=ZERO,receivable_delta=ZERO,tax_delta=ZERO,share_delta=0,**extra):
        journal.append(dict(date=day,phase=phase,kind=kind,code=code,cash_delta=money(cash_delta),receivable_delta=money(receivable_delta),
            sold_tax_payable_delta=money(tax_delta),share_delta=int(share_delta),cash_after=cash,receivable_after=receive_total(),sold_tax_payable_after=sold_tax,**extra))

    def get_bar(code,day):
        b=bars.get(code,{}).get(day)
        if b is None:
            if (code,day) in verified_suspensions:return None
            if retain_unknown_quotes:
                unresolved_quotes.append(dict(code=code,date=day,kind='unknown_quote_status_last_mark_no_execution'));return None
            raise AuditBlocked(f'Unknown quote/status gap {code} {day}')
        if not isinstance(b,Bar):raise AuditBlocked('Bars must be explicit Bar records')
        if not b.active():
            if int(b.tradestatus)==0:return None
            raise AuditBlocked(f'Unexplained inactive quote {code} {day}')
        for name in ['open','high','low','close']:
            value=dec(getattr(b,name))
            if value<=0 or abs(value-money(value))>Decimal('.000001'):raise AuditBlocked(f'Invalid raw price {code} {day} {name}')
        if dec(b.high)<max(dec(b.open),dec(b.close)) or dec(b.low)>min(dec(b.open),dec(b.close)):raise AuditBlocked(f'OHLC inconsistency {code} {day}')
        return b

    def lower(b,code,day):
        if not b.limit_evidence:raise AuditBlocked(f'Missing limit evidence {code} {day}')
        if b.no_price_limit:
            if b.lower_limit is not None:raise AuditBlocked('Conflicting no-limit and lower-limit state')
            return ZERO
        if b.lower_limit is None or dec(b.lower_limit)<=0:raise AuditBlocked(f'Unknown lower price limit {code} {day}')
        limit=money(b.lower_limit)
        if min(dec(b.open),dec(b.low),dec(b.close))<limit-Decimal('.005'):raise AuditBlocked(f'Raw quote below evidenced limit {code} {day}')
        return limit

    def target(p):return ceil_price((p.buy_gross*(1+dec(tp))-p.dividend_gross)/p.qty())

    def stop(p):
        if sl is None:return ZERO
        wealth=max(p.buy_gross,p.trailing_wealth) if trail else p.buy_gross
        return money((wealth*(1-dec(sl))-p.dividend_gross)/p.qty())

    def sortkey(e):
        if rank=='liquid':return (-float(e.get('amount20',0)),e['code'])
        if rank=='deep':return (float(e.get('ret20',0)),e['code'])
        return (e['code'],)

    def delay(p,day,reason):
        if p.first_exit_intent is None:p.first_exit_intent=day
        p.pending_exit=p.pending_exit or reason
        delays.append(dict(code=p.code,date=day,reason=reason,first_exit_intent=p.first_exit_intent,due_date=p.due_date,qty=p.qty()))

    def sell(p,day,price,reason,phase):
        nonlocal cash,sold_tax
        if not p.unlocked(day):raise AuditBlocked('Attempt to sell locked shares')
        price=money(price);qty=p.qty();gross=money(price*qty);bill=fee(gross,day,True)
        assessed=p.estimated_tax(day);cash+=gross-bill['total'];sold_tax+=assessed
        for claim in p.claims:
            tax_assessments.append(dict(code=p.code,sale_date=day,action_id=claim.action_id,lot_id=claim.lot_id,acquired=claim.acquired,
                holding_interval=f'[{claim.acquired},{day})',taxable_income=claim.taxable_income,rate=dividend_rate(claim.acquired,day),assessed_tax=money(claim.taxable_income*dividend_rate(claim.acquired,day)),cash_collection_date=None))
        record(day,phase,'sell',p.code,cash_delta=gross-bill['total'],tax_delta=assessed,share_delta=-qty,price=price,gross=gross,**bill,
            reason=reason,dividend_tax_assessed=assessed,signal_date=p.signal_date,buy_date=p.buy_date)
        pnl=gross-bill['total']+p.dividend_gross-assessed-p.buy_gross-p.buy_fee
        trades.append(dict(code=p.code,name=p.name,signal_date=p.signal_date,buy_date=p.buy_date,sell_date=day,buy_qty=p.buy_qty,sell_qty=qty,
            buy_price=p.buy_price,sell_price=price,buy_gross=p.buy_gross,sale_gross=gross,fees=p.buy_fee+bill['total'],dividend_gross=p.dividend_gross,
            dividend_tax=assessed,pnl=pnl,return_pct=float(pnl/(p.buy_gross+p.buy_fee)),reason=reason,phase=phase,buy_offset=ordinal[day]-ordinal[p.buy_date],
            due_date=p.due_date,first_exit_intent=p.first_exit_intent,delayed=bool(p.first_exit_intent),corporate_events=p.corporate_events))
        del positions[p.code]

    for day in days:
        # Ex-rights only applies to the previous registration-date closing owner.
        for a in at_ex.get(day,[]):
            entitled=entitlements.get(a.action_id)
            if entitled is None:
                if a.code in positions and (not a.record_date or a.record_date>=a.ex_date):raise AuditBlocked(f'Unknown held record date {a.action_id}')
                if a.code in positions and a.record_date and positions[a.code].buy_date<=a.record_date:raise AuditBlocked(f'Missing registration-date ownership capture {a.action_id}')
                continue
            if not a.verified or a.unresolved_fields or not a.evidence:raise AuditBlocked(f'Unverified held action {a.action_id}: {a.unresolved_fields}')
            p=positions.get(a.code)
            if p is None:raise AuditBlocked(f'Entitlement owner disappeared before ex-date {a.action_id}')
            if dec(a.cash_ps)<0 or dec(a.bonus_ps)<0 or dec(a.reserve_ps)<0:raise AuditBlocked('Negative action quantities')
            if dec(a.cash_ps)>0 and (not a.pay_date or a.pay_date<a.ex_date):raise AuditBlocked('Unknown/inconsistent dividend payment date')
            stock_ps=dec(a.bonus_ps)+dec(a.reserve_ps)
            if stock_ps and (not a.stock_release_date or not a.stock_acquisition_date):raise AuditBlocked('Missing bonus acquisition/release evidence')
            if a.stock_release_date and a.stock_release_date<a.ex_date:raise AuditBlocked('Stock released before ex-date')
            if stock_ps and not (a.ex_date<=a.stock_acquisition_date<=a.stock_release_date):raise AuditBlocked('Inconsistent stock acquisition/release dates')
            if stock_ps>0 and a.taxable_stock_income_ps is None:raise AuditBlocked('Unknown stock-dividend/reserve-conversion taxable amount')
            taxable_stock=dec(a.taxable_stock_income_ps or 0)
            if taxable_stock<0:raise AuditBlocked('Negative taxable stock income')
            total_q=sum(x['qty'] for x in entitled['lots']);gross=money(total_q*dec(a.cash_ps))
            p.dividend_gross+=gross;p.corporate_events+=1;p.pending_factor_action=True
            if gross:
                receivables[a.action_id]=dict(code=a.code,amount=gross,pay_date=a.pay_date)
                record(day,'preopen','dividend_receivable',a.code,receivable_delta=gross,action_id=a.action_id,entitled_qty=total_q)
            for reglot in entitled['lots']:
                income=money(reglot['qty']*(dec(a.cash_ps)+taxable_stock))
                if income:p.claims.append(TaxClaim(a.action_id,reglot['lot_id'],reglot['acquired'],income))
            extra_exact=dec(total_q)*stock_ps
            if abs(extra_exact-extra_exact.to_integral_value())>Decimal('.00000001'):raise AuditBlocked(f'Fractional stock allocation needs exchange evidence {a.action_id}')
            extra=int(extra_exact)
            if extra:
                p.lots.append(Lot(a.action_id+':stock',extra,a.stock_acquisition_date,a.stock_release_date))
                record(day,'preopen','stock_entitlement',a.code,share_delta=extra,action_id=a.action_id,release=a.stock_release_date,acquired=a.stock_acquisition_date)
            current=get_bar(p.code,day)
            if current is None:
                if a.reference_price is None:raise AuditBlocked(f'Suspended ex-rights requires verified reference price {a.action_id}')
                p.last_price=money(a.reference_price)
            corporate.append(dict(date=day,code=a.code,action_id=a.action_id,entitled_qty=total_q,cash_gross=gross,stock_qty=extra,pay_date=a.pay_date,
                release=a.stock_release_date,stock_acquisition_date=a.stock_acquisition_date,taxable_income_ps=dec(a.cash_ps)+taxable_stock))
        for action_id,item in list(receivables.items()):
            if item['pay_date']<=day:
                amount=item['amount'];cash+=amount;del receivables[action_id]
                record(day,'preopen','dividend_payment',item['code'],cash_delta=amount,receivable_delta=-amount,action_id=action_id)
        today={}
        for code,p in positions.items():
            if (code,int(day[:4])) not in coverage:raise AuditBlocked(f'Missing held code/year corporate evidence {code} {day}',
                code=code,date=day,buy_date=p.buy_date,signal_date=p.signal_date,due_date=p.due_date,qty=p.qty(),pending_exit=p.pending_exit,first_exit_intent=p.first_exit_intent)
            b=get_bar(code,day);today[code]=b
            if b is not None:
                f=factors.get(code,{}).get(day)
                if f is None or not (float(f)>0):raise AuditBlocked(f'Missing share-adjustment factor {code} {day}')
                if abs(float(f)/p.last_factor-1)>.0001 and not p.pending_factor_action:raise AuditBlocked(f'Unexplained held factor change {code} {day}')
                p.last_factor=float(f);p.pending_factor_action=False
        # Only genuine opening exits may finance today's next-open entries.
        intraday_deferred=set()
        for code in list(positions):
            p=positions[code];b=today.get(code)
            if b is None:
                if p.pending_exit or (p.due_date and day>=p.due_date):delay(p,day,'suspended_exit')
                continue
            if day==p.buy_date:continue
            limit=lower(b,code,day)
            if not p.unlocked(day):
                if p.pending_exit or (p.due_date and day>=p.due_date) or dec(b.high)>=target(p) or (sl is not None and dec(b.low)<=stop(p)):delay(p,day,'locked_shares_exit')
                continue
            if p.pending_exit or (p.due_date and day>p.due_date):
                if dec(b.open)>limit:sell(p,day,b.open,'delayed_open','open')
                elif dec(b.high)>limit:intraday_deferred.add(code)
                else:delay(p,day,'sealed_lower_limit_exit')
            elif sl is not None and dec(b.open)<=stop(p):
                if dec(b.open)>limit:sell(p,day,b.open,'stop_loss_open','open')
                elif dec(b.high)>limit:intraday_deferred.add(code)
                else:delay(p,day,'sealed_lower_limit_stop')
            elif dec(b.open)>=target(p):
                if dec(b.open)>limit:sell(p,day,target(p),'take_profit_open','open')
                elif dec(b.high)>limit:intraday_deferred.add(code)
        for e in sorted(schedule.get(day,[]),key=sortkey):
            code=e['code']
            if code in positions:skips.append(dict(date=day,code=code,reason='already_held'));continue
            if len(positions)>=20:skips.append(dict(date=day,code=code,reason='slots_full'));continue
            b=get_bar(code,day)
            if b is None:skips.append(dict(date=day,code=code,reason='confirmed_suspended_entry_no_delayed_buy'));continue
            if b.upper_limit is not None and dec(b.open)>=dec(b.upper_limit):
                skips.append(dict(date=day,code=code,reason='upper_limit_open_conservative_no_fill'));continue
            if (code,int(day[:4])) not in coverage:raise AuditBlocked(f'Missing entry code/year corporate evidence {code} {day}')
            available=cash-sold_tax;budget=min(Decimal('50000.00'),max(ZERO,available));price=money(b.open);qty=fit_shares(budget,price,day)
            if qty<=0:skips.append(dict(date=day,code=code,reason='cannot_afford_100_shares'));continue
            f=factors.get(code,{}).get(day)
            if f is None or not float(f)>0:raise AuditBlocked(f'Missing entry factor {code} {day}')
            gross=money(qty*price);bill=fee(gross,day);cash-=gross+bill['total'];j=ordinal[day]+horizon;due=dates[j] if j<len(dates) else None
            p=Position(code,e.get('name',code),e['date'],day,due,price,qty,gross,bill['total'],price,float(f))
            p.trailing_wealth=gross;p.lots=[Lot(code+':'+day,qty,day,day)];positions[code]=p;today[code]=b
            record(day,'open','buy',code,cash_delta=-gross-bill['total'],share_delta=qty,price=price,gross=gross,**bill,signal_date=e['date'],due_date=due)
        # Opening-at-limit break proxies are intraday exits and cannot fund entries.
        forced_close_candidates=[]
        for code in list(positions):
            p=positions[code];b=today.get(code)
            if day==p.buy_date:continue
            if b is None:
                if p.due_date and day>=p.due_date:delay(p,day,'suspended_exit')
                continue
            if not p.unlocked(day):continue
            limit=lower(b,code,day)
            if code in intraday_deferred:
                reason='delayed_limit_break_proxy' if p.pending_exit or (p.due_date and day>p.due_date) else 'take_profit_limit_break_proxy'
                sell(p,day,limit,reason,'intraday');continue
            if p.pending_exit or (p.due_date and day>p.due_date):continue
            stop_price=stop(p)
            if sl is not None and dec(b.low)<=stop_price:
                if stop_price>limit:sell(p,day,min(dec(b.open),stop_price),'stop_loss_touch','intraday');continue
                if dec(b.high)>limit:sell(p,day,limit,'stop_loss_limit_break_proxy','intraday');continue
                delay(p,day,'sealed_lower_limit_stop');continue
            tp_price=target(p)
            if dec(b.high)>=tp_price:
                if tp_price>limit:sell(p,day,tp_price,'take_profit_touch','intraday');continue
                if dec(b.high)>limit:sell(p,day,limit,'take_profit_limit_break_proxy','intraday');continue
            if p.due_date==day:
                forced_close_candidates.append(code)
        # Close executions must follow *all* stocks' intraday executions.
        # No opening order can consume either intraday or close proceeds.
        for code in forced_close_candidates:
            p=positions[code];b=today[code];limit=lower(b,code,day)
            if dec(b.close)>limit:sell(p,day,b.close,'forced_B20_close','close')
            else:delay(p,day,'B20_close_at_lower_limit')
        # Registration-date closing ownership is captured after all close exits.
        for a in at_record.get(day,[]):
            p=positions.get(a.code)
            if p is None:continue
            if a.ex_date<=day:raise AuditBlocked('Record/ex-date ordering inconsistent')
            entitlements[a.action_id]=dict(code=a.code,lots=[dict(lot_id=l.lot_id,qty=l.qty,acquired=l.acquired) for l in p.lots])
        stock_value=ZERO;held_tax=ZERO
        for code,p in positions.items():
            b=today.get(code)
            if b is not None:
                p.last_price=money(b.close)
                p.trailing_wealth=max(p.trailing_wealth,money(p.qty()*p.last_price)+p.dividend_gross)
            stock_value+=money(p.qty()*p.last_price);held_tax+=p.estimated_tax(day)
        receivable=receive_total();equity=cash+stock_value+receivable-sold_tax-held_tax
        if cash<ZERO or cash-sold_tax<ZERO or len(positions)>20:raise AuditBlocked(f'Cash/slots invariant failed {day}')
        nav.append(dict(date=day,cash=cash,spendable_cash=cash-sold_tax,stock_value=stock_value,gross_receivable=receivable,
            sold_dividend_tax_payable=sold_tax,holding_estimated_dividend_tax=held_tax,equity=equity,positions=len(positions)))
    open_pnl=sum((money(p.qty()*p.last_price)+p.dividend_gross-p.estimated_tax(days[-1])-p.buy_gross-p.buy_fee for p in positions.values()),ZERO)
    closed_pnl=sum((t['pnl'] for t in trades),ZERO);terminal=nav[-1]['equity']
    if abs(terminal-Decimal('1000000.00')-closed_pnl-open_pnl)>CENT:raise AuditBlocked('Economic PNL reconciliation failed')
    previous=Decimal('1000000.00');yearly=[]
    frame=pd.DataFrame(nav)
    for year,g in frame.groupby(frame.date.str[:4]):
        peak=previous;dd=Decimal('0')
        for value in g.equity:
            peak=max(peak,value);dd=min(dd,value/peak-1)
        end=g.equity.iloc[-1];yearly.append(dict(year=int(year),return_pct=float(end/previous-1),max_drawdown=float(dd),end_equity=end));previous=end
    peak=Decimal('1000000.00');dd=Decimal('0')
    for row in nav:peak=max(peak,row['equity']);dd=min(dd,row['equity']/peak-1)
    span=(pd.Timestamp(end_date)-pd.Timestamp(start_date)).days+1
    summary=dict(unresolved_quote_events=len(unresolved_quotes),economic_status='CONDITIONAL_LAST_MARK_UNPRICED_ASSETS' if unresolved_quotes else 'FULLY_PRICED_WITH_EXECUTION_ASSUMPTIONS',scope=scope,capital=Decimal('1000000.00'),slots=20,slot_budget=Decimal('50000.00'),take_profit=tp,stop_loss=sl,trailing=trail,rank=rank,forced_day=horizon,
        final_equity=terminal,total_return=float(terminal/Decimal('1000000.00')-1),annualized_return=(float(terminal)/1000000)**(365.25/span)-1,
        max_drawdown=float(dd),closed_trades=len(trades),open_positions=len(positions),pending_signals=len(pending_signals),skipped=len(skips),
        corporate_events=len(corporate),total_transaction_fees=sum((r.get('total',ZERO) for r in journal if r['kind'] in ('buy','sell')),ZERO),
        sold_dividend_tax_payable=sold_tax,held_dividend_tax_estimate=nav[-1]['holding_estimated_dividend_tax'],cash_collection_dates_not_fabricated=True,
        closed_pnl=closed_pnl,open_marked_pnl=open_pnl,economic_pnl_residual=terminal-Decimal('1000000.00')-closed_pnl-open_pnl)
    return dict(unresolved_quotes=unresolved_quotes,summary=summary,yearly=yearly,nav=nav,journal=journal,trades=trades,skips=skips,delays=delays,corporate_actions=corporate,
        tax_assessments=tax_assessments,pending_signals=pending_signals,receivables=receivables,positions=positions)
