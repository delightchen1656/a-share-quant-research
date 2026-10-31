"""Direction1 development account engine; extracted unchanged from v3."""
import json,math
from pathlib import Path
import numpy as np
import pandas as pd
OUT=Path(__file__).resolve().parent

def fee(gross,day,sell=False):
    commission=max(5.,gross*.0003)
    transfer=gross*(.00001 if day>='2022-04-29' else .00002)
    stamp=gross*(.0005 if day>='2023-08-28' else .001) if sell else 0.
    return commission+transfer+stamp

def fit_shares(budget,price,day):
    shares=int(budget/price/100)*100
    while shares and shares*price+fee(shares*price,day)>budget+1e-8:shares-=100
    return shares

def tick_up(price):return math.ceil((price-1e-9)*100)/100

def run(d,chosen,dates,ordinal,quotes,factors,actions,pool,filtered,capital,slots,missing_force='defer',forced_day=5,take_profit=.03,annual_rules=None,stop_loss=None,persist=True,quiet=False):
    assert forced_day in range(1,6)
    events=d.loc[d.is_leader] if pool=='leaders' else d
    if filtered:events=events.loc[[ (r.code,r.date) in chosen[pool] for r in events.itertuples()]]
    schedule={}
    for row in events.itertuples():schedule.setdefault(dates[ordinal[row.date]+1],[]).append(row)
    cash=float(capital);hold={};payments=[];trades=[];skips=[];ledger=[];nav=[];actionlog=[]
    budget=capital/slots

    def sell(code,day,price,reason):
        nonlocal cash
        h=hold[code];qty=h['available']
        if not qty:return
        gross=qty*price;cost=fee(gross,day,True);cash+=gross-cost
        h['sale_net']+=gross-cost;h['sale_gross']+=gross;h['sell_fee']+=cost;h['available']=0
        ledger.append(dict(date=day,kind='sell',code=code,qty=qty,price=price,gross=gross,fee=cost,cash=cash,reason=reason))
        h['reasons'].append(reason)
        if not h['locked']:
            trades.append(dict(code=code,name=h['name'],signal_date=h['signal_date'],buy_date=h['buy_date'],sell_date=day,
                buy_qty=h['buy_qty'],buy_price=h['buy_price'],cost=h['cost'],sale_gross=h['sale_gross'],
                dividend_net=h['div_net'],fees=h['buy_fee']+h['sell_fee'],
                pnl=h['sale_net']+h['div_net']-h['cost'],
                return_pct=(h['sale_net']+h['div_net'])/h['cost']-1,
                reason=';'.join(h['reasons']),buy_offset=ordinal[day]-ordinal[h['buy_date']],
                corporate_events=h['corporate_events']))
            del hold[code]

    for day in [x for x in dates if '2021-01-01'<=x<='2023-12-31']:
        # Cash is credited on payment dates, not ex-date; receivables remain in NAV.
        due=[x for x in payments if x['pay']<=day]
        for pay in due:
            cash+=pay['net'];ledger.append(dict(date=day,kind='dividend_payment',code=pay['code'],cash=cash,net=pay['net']))
        payments=[x for x in payments if x['pay']>day]
        for code in list(hold):
            h=hold[code]
            for lock in list(h['locked']):
                if lock['release']<=day:h['available']+=lock['qty'];h['locked'].remove(lock)
            action=actions.get((code,day))
            if action:
                old=h['available']+sum(x['qty'] for x in h['locked'])
                gross=old*action['cash'];tax=old*(action['cash']+action['taxable_stock'])*.2;net=gross-tax
                h['div_gross']+=gross;h['div_net']+=net;h['corporate_events']+=1
                extra=int(math.floor(old*action['stock']+1e-8))
                if extra:
                    if action['release']<=day:h['available']+=extra
                    else:h['locked'].append(dict(qty=extra,release=action['release']))
                if action['pay']<=day:cash+=net
                elif abs(net)>1e-12:payments.append(dict(code=code,pay=action['pay'],net=net))
                actionlog.append(dict(code=code,date=day,old_qty=old,bonus_qty=extra,net_dividend=net,**action))
            bar=quotes[code].get(day)
            if bar is not None:
                # Require major factor changes to have explicit action evidence.
                current=factors[code][day]
                if abs(current/h['last_factor']-1)>.0001 and not action:
                    raise ValueError(f'Unresolved corporate/reference change: {code} {day}')
                if action and action['reference_error']>.021:raise ValueError(f'Bad action reference {code} {day}')
                h['last_factor']=current
        # Only opening exits may fund opening entries. Intraday/close exits cannot.
        for code in list(hold):
            h=hold[code];bar=quotes[code].get(day)
            if bar is None:continue
            if day>h['due_date']:
                sell(code,day,float(bar.open),'forced_delayed_open');continue
            if day>h['buy_date'] and not h['locked']:
                if h['stop_loss'] is not None:
                    stop=math.floor(((h['buy_notional']*(1-h['stop_loss'])-h['div_gross'])/h['available']+1e-9)*100)/100
                    if bar.open<=stop+1e-9:sell(code,day,float(bar.open),'stop_loss_open');continue
                target=tick_up((h['buy_notional']*(1+h['take_profit'])-h['div_gross'])/h['available'])
                if bar.open>=target-1e-9:sell(code,day,float(bar.open),'take_profit_open')
        for event in sorted(schedule.get(day,[]),key=lambda x:x.code):
            code=event.code
            config=(annual_rules or {}).get(int(event.date[:4]),{})
            entry_slots=int(config.get('slots',slots));entry_budget=capital/entry_slots
            if code in hold:skips.append(dict(date=day,code=code,reason='already_held'));continue
            if len(hold)>=entry_slots:skips.append(dict(date=day,code=code,reason='slots_full'));continue
            bar=quotes[code].get(day)
            if bar is None:raise ValueError(f'Missing entry {code} {day}')
            price=float(bar.open);qty=fit_shares(min(entry_budget,cash),price,day)
            if not qty:skips.append(dict(date=day,code=code,reason='cannot_afford_100_shares'));continue
            gross=qty*price;cost=fee(gross,day);cash-=gross+cost
            horizon=int(config.get('forced_day',forced_day));tp=float(config.get('take_profit',take_profit))
            sl=config.get('stop_loss',stop_loss)
            hold[code]=dict(name=event.name,signal_date=event.date,buy_date=day,buy_price=price,buy_qty=qty,
                buy_notional=gross,cost=gross+cost,buy_fee=cost,available=qty,locked=[],due_date=dates[ordinal[day]+horizon],
                take_profit=tp,forced_day=horizon,stop_loss=sl,
                last_price=price,last_factor=factors[code][day],sale_net=0.,sale_gross=0.,sell_fee=0.,div_net=0.,div_gross=0.,corporate_events=0,reasons=[])
            ledger.append(dict(date=day,kind='buy',code=code,qty=qty,price=price,gross=gross,fee=cost,cash=cash))
        for code in list(hold):
            h=hold[code];bar=quotes[code].get(day)
            if bar is None:
                if day==h['due_date'] and missing_force=='last_close':
                    sell(code,day,h['last_price'],f"forced_B{h['forced_day']}_last_close_proxy")
                continue
            if day>h['buy_date'] and not h['locked']:
                if h['stop_loss'] is not None:
                    stop=math.floor(((h['buy_notional']*(1-h['stop_loss'])-h['div_gross'])/h['available']+1e-9)*100)/100
                    # With daily bars, conservatively execute stop before TP if both touched.
                    if bar.low<=stop+1e-9:sell(code,day,stop,'stop_loss_touch');continue
                target=tick_up((h['buy_notional']*(1+h['take_profit'])-h['div_gross'])/h['available'])
                if bar.high>=target-1e-9:sell(code,day,target,'take_profit_touch');continue
            if day==h['due_date']:sell(code,day,float(bar.close),f"forced_B{h['forced_day']}_close")
        value=0.
        for code,h in hold.items():
            bar=quotes[code].get(day)
            if bar is not None:h['last_price']=float(bar.close)
            qty=h['available']+sum(x['qty'] for x in h['locked']);value+=qty*h['last_price']
        receivable=sum(x['net'] for x in payments);equity=cash+value+receivable
        assert cash>=-1e-6 and len(hold)<=slots
        nav.append(dict(date=day,cash=cash,stock_value=value,receivable=receivable,equity=equity,positions=len(hold)))
    ending_open_pnl=sum(h['sale_net']+(h['available']+sum(x['qty'] for x in h['locked']))*h['last_price']+h['div_net']-h['cost'] for h in hold.values())
    f=pd.DataFrame(nav);t=pd.DataFrame(trades,columns=['code','name','signal_date','buy_date','sell_date','buy_qty','buy_price','cost','sale_gross','dividend_net','fees','pnl','return_pct','reason','buy_offset','corporate_events']);s=pd.DataFrame(skips,columns=['date','code','reason'])
    assert abs(float(f.equity.iloc[-1])-capital-t.pnl.sum()-ending_open_pnl)<.01, 'Cash/PNL reconciliation failed'
    peak=np.maximum.accumulate(np.r_[capital,f.equity.to_numpy()]);dd=np.r_[capital,f.equity.to_numpy()]/peak-1
    summary=dict(pool=pool,filtered=filtered,capital=capital,slots=None if annual_rules else slots,slot_budget=None if annual_rules else budget,forced_day=None if annual_rules else forced_day,take_profit=None if annual_rules else take_profit,stop_loss=None if annual_rules else stop_loss,annual_rules=annual_rules,signals=len(events),
        trades=len(t),skipped=len(s),final_equity=float(f.equity.iloc[-1]),total_return=float(f.equity.iloc[-1])/capital-1,
        annualized_return=(float(f.equity.iloc[-1])/capital)**(365.25/1095)-1,max_drawdown=float(dd.min()),
        takeprofit=int(t.reason.str.contains('take_profit').sum()),
        stoploss=int(t.reason.str.contains('stop_loss').sum()),
        forced=int(t.reason.str.contains('forced').sum()),net_win_rate=float((t.pnl>0).mean()) if len(t) else None,
        mean_trade_return=float(t.return_pct.mean()) if len(t) else None,fees=float(t.fees.sum()),
        max_positions=int(f.positions.max()),average_positions=float(f.positions.mean()),
        corporate_events=len(actionlog),delayed_exits=int(t.reason.str.contains('delayed').sum()),
        skipped_slots=int((s.reason=='slots_full').sum()) if len(s) else 0)
    yearly=[];previous=float(capital)
    for year,g in f.groupby(f.date.str[:4]):
        end=float(g.equity.iloc[-1]);v=np.r_[previous,g.equity.to_numpy()]
        yearly.append(dict(year=int(year),return_pct=end/previous-1,max_drawdown=float((v/np.maximum.accumulate(v)-1).min()),end_equity=end))
        previous=end
    key=f"{pool}_{'after' if filtered else 'before'}_{capital}_{slots}"
    if missing_force=='last_close':key+='_last_close_proxy'
    if persist:
        folder=OUT/key;folder.mkdir(exist_ok=True)
        for name,frame in [('daily_nav',f),('trades',t),('skips',s),('ledger',pd.DataFrame(ledger)),('actions',pd.DataFrame(actionlog))]:frame.to_parquet(folder/(name+'.parquet'),index=False)
        (folder/'summary.json').write_text(json.dumps(dict(summary=summary,yearly=yearly),ensure_ascii=False,indent=2),encoding='utf8')
    if not quiet:print(key,json.dumps(summary,ensure_ascii=False),flush=True)
    specials=[dict(code=r.code,signal_date=r.signal_date) for r in t.loc[t.reason.str.contains('delayed')].itertuples()]
    yearly_trades={int(y):len(g) for y,g in t.groupby(t.buy_date.str[:4])}
    return dict(key=key,summary=summary,yearly=yearly,specials=specials,yearly_trades=yearly_trades)
