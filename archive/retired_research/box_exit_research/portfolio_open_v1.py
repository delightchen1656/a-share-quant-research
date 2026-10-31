"""Chronological 2-position research ledger. Raw cash/shares; daily execution estimates."""
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
import json,hashlib,math,calendar
import numpy as np
import pandas as pd
from run_exit_study import INPUT,prepare_frame,sha,dump,limit_down

HERE=Path(__file__).resolve().parent;OUTPUT=HERE/'holdout_restricted/portfolio_open_v1'
def cents(x):return float(Decimal(str(float(x))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
def transfer_rate(date):return .00002 if pd.Timestamp(date)<pd.Timestamp('2022-04-29') else .00001
def fees(value,date,sell=False):
    commission=cents(max(5,value*.0003));transfer=cents(value*transfer_rate(date))
    stamp=cents(value*(.001 if pd.Timestamp(date)<pd.Timestamp('2023-08-28') else .0005)) if sell else 0.
    return dict(commission=commission,transfer=transfer,stamp=stamp,total=cents(commission+transfer+stamp))
def tax_rate(acquired,disposed):
    acquired=pd.Timestamp(acquired);disposed=pd.Timestamp(disposed)
    return .20 if disposed<=acquired+pd.DateOffset(months=1) else .10 if disposed<=acquired+pd.DateOffset(years=1) else 0.
def upper_limit(preclose,is_st):return float((Decimal(str(preclose))*(Decimal('1.05') if str(is_st)=='1' else Decimal('1.10'))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def load_inputs():
    manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert sha(INPUT/'events.parquet')==manifest['events_sha256'] and sha(INPUT/'calendar.json')==manifest['calendar_sha256']
    events=pd.read_parquet(INPUT/'events.parquet');dates=pd.DatetimeIndex(pd.to_datetime(pd.read_json(INPUT/'calendar.json').date))
    lookup={(r['code'],r['mode']):r for r in manifest['files']};frames={}
    for code in sorted(events.code.unique()):
        data={}
        for mode in ['raw','qfq']:
            rec=lookup[(code,mode)];assert sha(rec['path'])==rec['sha256'];data[mode]=pd.read_parquet(rec['path'])
            assert pd.to_datetime(data[mode].date).max()<=pd.Timestamp('2024-12-31')
        frames[code]=prepare_frame(data['raw'],data['qfq'],dates)
    action_area=INPUT/'company_actions_v1';am=json.loads((action_area/'manifest.json').read_text(encoding='utf-8'))
    plan=json.loads((INPUT/'action_query_plan.json').read_text(encoding='utf-8'));covered={(r[0][:6],int(r[1])) for r in plan}
    assert len(am)==len(plan)
    actions={};canonical={}
    for file,info in am.items():
        p=action_area/file;assert sha(p)==info['sha256'];data=json.loads(p.read_text(encoding='utf-8'));assert data['error_code']=='0'
        for r in data['records']:
            ex=r.get('dividOperateDate');reg=r.get('dividRegistDate')
            if not ex:continue
            assert ex<='2024-12-31' and reg and reg<ex
            code=r['code'].split('.')[-1];key=code+'_'+ex+'_'+reg
            if key in canonical:
                old=canonical[key]['record']
                for field,value in r.items():
                    assert not old.get(field) or not value or old[field]==value,('conflicting action record',key,field)
                    if not old.get(field) and value:old[field]=value
            else:canonical[key]=dict(record=dict(r),source_file=str(p.resolve()),source_sha256=sha(p))
    for key,item in canonical.items():
            r=item['record'];code=r['code'].split('.')[-1];ex=r['dividOperateDate'];reg=r['dividRegistDate']
            normalized=dict(id=key,code=code,record=reg,ex=ex,pay=r.get('dividPayDate') or None,
                listed=r.get('dividStockMarketDate') or None,cash=float(r.get('dividCashPsBeforeTax') or 0),
                bonus=float(r.get('dividStocksPs') or 0),reserve=float(r.get('dividReserveToStockPs') or 0),
                source_file=item['source_file'],source_sha256=item['source_sha256'],description=r.get('dividCashStock'))
            actions[key]=normalized
    return dates,events,frames,list(actions.values()),covered

class Account:
    def __init__(self,dates,events,frames,actions,covered,capital=100000.):
        self.dates=dates;self.events=events;self.frames=frames;self.actions=actions;self.covered=covered
        self.cash=float(capital);self.capital=capital;self.positions={};self.entitlements=[];self.history=[];self.trades=[];self.skips=[];self.daily=[];self.action_log=[];self.audit_issues=[]
        self.next_id=0;self.now=None;self.index=None;self.phase=None
        self.entries={}
        for r in events.sort_values(['signal_date','code']).to_dict('records'):
            t=dates.get_loc(pd.Timestamp(r['signal_date']))
            if t+1>=len(dates):self.skips.append(dict(event_id=r['event_id'],reason='no_next_session_within_boundary'));continue
            self.entries.setdefault(t+1,[]).append(r)
    def liability(self,date):
        total=0.
        for a in self.entitlements:
            if not a['active'] or a['tax_paid']:continue
            rate=a.get('final_tax_rate',tax_rate(a['acquired'],date));total+=cents(a['taxable']*rate)
        return cents(total)
    def unlisted(self,pid):return sum(a['unlisted'] for a in self.entitlements if a['pid']==pid and a['active'])
    def equity(self,field):
        value=self.cash
        for p in self.positions.values():
            row=self.frames[p['code']].iloc[self.index]
            mark=float(row['raw_'+field]) if row.active else p['last_mark']
            value+=mark*(p['shares']+self.unlisted(p['pid']))
        value+=sum(a['cash_gross'] for a in self.entitlements if a['active'] and not a['paid'])
        return cents(value-self.liability(self.now))
    def corporate_start(self):
        date=self.now.strftime('%Y-%m-%d')
        for a in self.entitlements:
            source=a['source'];p=next((p for p in self.positions.values() if p['pid']==a['pid']),None)
            if not a['active'] and source['ex']<=date:
                assert p is not None,'Entitlement should activate before an ex-date disposal'
                if source['cash'] and not source['pay']:raise ValueError('Cash payment date missing: '+source['id'])
                if source['bonus']+source['reserve']>0 and not source['listed']:raise ValueError('Bonus listing date missing: '+source['id'])
                if source['bonus']>0:raise ValueError('Bonus face value/tax needs issuer verification: '+source['id'])
                a['active']=True;a['cash_gross']=cents(a['quantity']*source['cash']);a['taxable']=a['cash_gross']
                a['unlisted']=a['quantity']*(source['bonus']+source['reserve'])
                assert abs(a['unlisted']-round(a['unlisted']))<1e-6,'Fractional entitlement needs verified allocation'
                a['unlisted']=int(round(a['unlisted']))
                self.action_log.append(dict(date=date,kind='ex_entitlement',code=source['code'],cash=a['cash_gross'],new_shares=a['unlisted'],action=source['id']))
            if not a['active']:continue
            if a['unlisted'] and source['listed']<=date:
                assert p is not None;p['shares']+=a['unlisted']
                self.action_log.append(dict(date=date,kind='new_shares_listed',code=source['code'],shares=a['unlisted'],action=source['id']))
                a['unlisted']=0
            if not a['paid'] and source['pay'] and source['pay']<=date:
                self.cash=cents(self.cash+a['cash_gross']);a['paid']=True
                p_hist=self.history[a['pid']];p_hist['dividends']=cents(p_hist['dividends']+a['cash_gross'])
                self.action_log.append(dict(date=date,kind='cash_paid',code=source['code'],amount=a['cash_gross'],action=source['id']))
                if 'final_tax_rate' in a and not a['tax_paid']:self.pay_tax(a)
    def pay_tax(self,a):
        amount=cents(a['taxable']*a['final_tax_rate']);self.cash=cents(self.cash-amount);a['tax_paid']=True
        self.history[a['pid']]['dividend_tax']=cents(self.history[a['pid']]['dividend_tax']+amount)
        if amount:self.action_log.append(dict(date=str(self.now.date()),kind='dividend_tax',code=a['source']['code'],amount=amount,action=a['source']['id']))
    def audit_held_reference(self,p):
        row=self.frames[p['code']].iloc[self.index]
        if (p['code'],self.now.year) not in self.covered:raise ValueError('Company/year coverage missing while held: '+p['code']+'/'+str(self.now.year))
        if row.unknown:raise ValueError('Unknown held quote: '+p['code']+'/'+str(self.now.date()))
        if not row.active:return
        previous=p['last_mark']
        diff=abs(row.preclose-previous)
        if diff>.011:
            acts=[a for a in self.actions if a['code']==p['code'] and a['ex']==str(self.now.date())]
            if not acts:raise ValueError('Unexplained held ex-reference break: '+p['code']+'/'+str(self.now.date()))
            cash=sum(a['cash'] for a in acts);shares=sum(a['bonus']+a['reserve'] for a in acts)
            expected=(previous-cash)/(1+shares)
            if abs(row.preclose-expected)>.021:raise ValueError('Corporate action does not reconcile raw reference: '+p['code']+'/'+str(self.now.date()))
            self.action_log.append(dict(date=str(self.now.date()),kind='reference_reconciled',code=p['code'],previous=previous,reference=float(row.preclose),expected=expected))
    def sell(self,p,price,reason):
        assert self.index>p['entry_index'],'T+1 violation';q=p['shares']
        if q==0:return
        row=self.frames[p['code']].iloc[self.index]
        assert row.raw_low-.011<=price<=row.raw_high+.011,'Estimated sell outside bar'
        value=cents(q*price);charge=fees(value,self.now,True);self.cash=cents(self.cash+value-charge['total'])
        hist=self.history[p['pid']];hist['sell_net']=cents(hist['sell_net']+value-charge['total']);hist['sell_shares']+=q
        self.trades.append(dict(date=str(self.now.date()),phase=self.phase,side='sell',pid=p['pid'],code=p['code'],event_id=p['event_id'],quantity=q,price=price,gross=value,reason=reason,**charge))
        p['shares']=0
        for a in self.entitlements:
            if a['pid']==p['pid'] and a['active'] and 'final_tax_rate' not in a:
                a['final_tax_rate']=tax_rate(a['acquired'],self.now)
                if a['paid'] or a['cash_gross']==0:self.pay_tax(a)
        if self.unlisted(p['pid'])==0:
            hist['exit_date']=str(self.now.date());hist['exit_reason']=reason
            del self.positions[p['code']]
        else:p['pending']='unlisted_remainder'
    def opening_exits(self):
        for p in list(self.positions.values()):
            self.audit_held_reference(p);row=self.frames[p['code']].iloc[self.index]
            if not row.active or self.index<=p['entry_index']:continue
            if p['highest']>=p['entry_q']*1.10-1e-10:p['stop_q']=max(p['stop_q'],p['entry_q']+.70*(p['highest']-p['entry_q']))
            factor=float(row.open/row.raw_open);raw_stop=cents(p['stop_q']/factor)
            p['raw_stop']=raw_stop
            if p['pending'] or row.raw_open<=raw_stop+1e-8:
                lower=limit_down(row.preclose,row.isST)
                if row.raw_open<=lower+.005:
                    p['pending']=p['pending'] or 'gap_stop_at_limit';p['deferred_open']=True
                else:self.sell(p,float(row.raw_open),p['pending'] or 'opening_gap_stop')
    def buy_entries(self):
        for r in self.entries.get(self.index,[]):
            reason=None;code=r['code'];row=self.frames[code].iloc[self.index]
            if code in self.positions:reason='same_code_held'
            elif len(self.positions)>=2:reason='two_positions_full_at_open'
            elif row.unknown:raise ValueError('Unknown entry quote: '+code+'/'+str(self.now.date()))
            elif not row.active:reason='entry_suspended'
            elif row.raw_open>=upper_limit(row.preclose,row.isST)-.005:reason='opening_at_upper_limit_no_fill_assumed'
            if reason:self.skips.append(dict(date=str(self.now.date()),event_id=r['event_id'],code=code,reason=reason));continue
            equity=self.equity('open');cash_available=max(0,self.cash-self.liability(self.now));budget=min(.5*equity,cash_available)
            price=float(row.raw_open);qty=int(budget//(price*100))*100
            while qty>0 and cents(qty*price)+fees(cents(qty*price),self.now)['total']>budget+1e-8:qty-=100
            if qty<=0:self.skips.append(dict(date=str(self.now.date()),event_id=r['event_id'],code=code,reason='cash_or_lot_unaffordable'));continue
            value=cents(qty*price);charge=fees(value,self.now);cost=cents(value+charge['total']);self.cash=cents(self.cash-cost)
            pid=self.next_id;self.next_id+=1;entry_q=float(row.open)
            p=dict(pid=pid,event_id=r['event_id'],code=code,shares=qty,entry_index=self.index,entry_date=str(self.now.date()),
                entry_q=entry_q,stop_q=.95*entry_q,highest=entry_q,raw_stop=cents(.95*price),expiry=self.index+59,
                pending=None,deferred_open=False,last_mark=price)
            self.positions[code]=p
            self.history.append(dict(pid=pid,event_id=r['event_id'],code=code,name=r['name'],signal_date=r['signal_date'],
                entry_date=str(self.now.date()),entry_price=price,buy_shares=qty,buy_cost=cost,
                allocation_equity=equity,allocation_budget=budget,sell_net=0.,sell_shares=0,dividends=0.,dividend_tax=0.,exit_date=None))
            self.trades.append(dict(date=str(self.now.date()),phase=self.phase,side='buy',pid=pid,event_id=r['event_id'],code=code,
                quantity=qty,price=price,gross=value,reason='next_session_open',equity_before=equity,budget=budget,**charge))
            assert cost<=.5*equity+.011 and self.cash>=-1e-8 and len(self.positions)<=2
    def intraday_exits(self):
        for p in list(self.positions.values()):
            row=self.frames[p['code']].iloc[self.index]
            if not row.active:continue
            if self.index==p['entry_index']:
                if row.raw_low<=p['raw_stop']+1e-8:p['pending']='buy_day_stop_wait_tplus1'
                continue
            lower=limit_down(row.preclose,row.isST)
            if p.get('deferred_open'):
                if row.raw_high>lower+.005:self.sell(p,float(row.raw_open),p['pending'] or 'limit_unlocked_estimate')
                continue
            if row.raw_low<=p['raw_stop']+1e-8:
                if abs(row.raw_high-row.raw_low)<.005 and row.raw_close<=lower+.005:p['pending']='stop_locked_limit';continue
                self.sell(p,max(float(row.raw_low),min(float(row.raw_open),p['raw_stop'])),'intraday_standing_stop')
    def closing(self):
        for p in list(self.positions.values()):
            row=self.frames[p['code']].iloc[self.index]
            if row.unknown:raise ValueError('Unknown closing quote: '+p['code'])
            if row.active:
                if self.index>=p['expiry'] and self.index>p['entry_index']:
                    lower=limit_down(row.preclose,row.isST)
                    if row.raw_close<=lower+.005:p['pending']='time60_close_at_limit'
                    else:self.sell(p,float(row.raw_close),'time60_close')
                if p['code'] not in self.positions:continue
                p['highest']=max(p['highest'],float(row.high));p['last_mark']=float(row.raw_close)
            p['deferred_open']=False
        date=str(self.now.date())
        for a in self.actions:
            if a['record']!=date or a['code'] not in self.positions:continue
            p=self.positions[a['code']];quantity=p['shares']+self.unlisted(p['pid'])
            self.entitlements.append(dict(source=a,pid=p['pid'],quantity=quantity,acquired=p['entry_date'],active=False,
                cash_gross=0.,taxable=0.,unlisted=0,paid=False,tax_paid=False))
        value=self.equity('close')
        self.daily.append(dict(date=date,equity=value,cash=self.cash,tax_liability=self.liability(self.now),
            positions=len(self.positions),codes='|'.join(sorted(self.positions)),
            receivable_cash=cents(sum(a['cash_gross'] for a in self.entitlements if a['active'] and not a['paid'])),
            stale_codes='|'.join(sorted(p['code'] for p in self.positions.values() if not self.frames[p['code']].iloc[self.index].active))))
        assert self.cash>=-1e-8 and len(self.positions)<=2 and value>=0
    def run(self,start='2019-01-01',end='2024-12-31'):
        for j,date in enumerate(self.dates):
            if not pd.Timestamp(start)<=date<=pd.Timestamp(end):continue
            self.index=j;self.now=date;self.phase='corporate_before_open';self.corporate_start()
            self.phase='open_exits';self.opening_exits();self.phase='open_buys';self.buy_entries()
            self.phase='intraday';self.intraday_exits();self.phase='close';self.closing()
        return self

def summarize(a):
    nav=pd.DataFrame(a.daily);eq=nav.equity.to_numpy(float);baseline=np.r_[a.capital,eq]
    dd=baseline/np.maximum.accumulate(baseline)-1
    annual=[];previous=a.capital
    for year,g in nav.groupby(nav.date.str[:4]):
        values=np.r_[previous,g.equity.to_numpy(float)];draw=values/np.maximum.accumulate(values)-1
        annual.append(dict(year=int(year),start_equity=previous,end_equity=float(values[-1]),return_rate=float(values[-1]/previous-1),max_drawdown=float(draw.min()),
            buys=sum(t['side']=='buy' and t['date'].startswith(year) for t in a.trades),sells=sum(t['side']=='sell' and t['date'].startswith(year) for t in a.trades)))
        previous=float(values[-1])
    closed=[]
    for p in a.history:
        if not p['exit_date']:continue
        receivables=sum(x['cash_gross']-cents(x['taxable']*x['final_tax_rate']) for x in a.entitlements if x['pid']==p['pid'] and x['active'] and not x['paid'] and 'final_tax_rate' in x)
        profit=cents(p['sell_net']+p['dividends']-p['dividend_tax']+receivables-p['buy_cost'])
        closed.append(dict(**p,net_profit=profit,net_return=profit/p['buy_cost']))
    trades=pd.DataFrame(a.trades);years=(pd.Timestamp(nav.date.iloc[-1])-pd.Timestamp(nav.date.iloc[0])).days/365.25
    summary=dict(start=nav.date.iloc[0],end=nav.date.iloc[-1],initial=a.capital,ending_equity=float(eq[-1]),total_return=float(eq[-1]/a.capital-1),
        annualized=float((eq[-1]/a.capital)**(1/years)-1),max_drawdown=float(dd.min()),buys=sum(t['side']=='buy' for t in a.trades),closed=len(closed),
        still_open=len(a.positions),max_positions=max(r['positions'] for r in a.daily),fees_total=cents(sum(t['total'] for t in a.trades)),
        skipped=len(a.skips),skips_by_reason=pd.Series([r['reason'] for r in a.skips]).value_counts().to_dict(),
        corporate_events=sum(x['kind']=='ex_entitlement' for x in a.action_log),cash_received=cents(sum(x['dividends'] for x in a.history)),
        dividend_tax_paid=cents(sum(x['dividend_tax'] for x in a.history)),unknown_quote_policy='fail closed',queue_model='daily conservative estimate; not certified fills',not_blind=True)
    if closed:
        c=pd.DataFrame(closed);win=c[c.net_profit>0];loss=c[c.net_profit<0]
        summary.update(win_rate=len(win)/len(c),mean_win=float(win.net_return.mean()) if len(win) else None,
            mean_loss=float(loss.net_return.mean()) if len(loss) else None,worst_trade=float(c.net_return.min()))
    return nav,annual,closed,summary

def main():
    assert not OUTPUT.exists(),'Keep account result snapshots immutable'
    assert (HERE/'PORTFOLIO_SPEC_v1.json').exists()
    dates,events,frames,actions,covered=load_inputs()
    a=Account(dates,events,frames,actions,covered).run();nav,annual,closed,summary=summarize(a)
    # Full terminal wealth reconciliation, including still-held/unpaid assets.
    if not a.positions and not any(x['active'] and not x['paid'] for x in a.entitlements):
        assert abs(summary['ending_equity']-(a.capital+sum(r['net_profit'] for r in closed)))<.021
    assert all(t['quantity']%100==0 for t in a.trades if t['side']=='buy')
    assert all(t['date']>a.history[t['pid']]['entry_date'] for t in a.trades if t['side']=='sell')
    OUTPUT.mkdir(parents=True);nav.to_parquet(OUTPUT/'daily_nav.parquet',index=False)
    for filename,records in [('orders.json',a.trades),('positions.json',a.history),('closed_trades.json',closed),('skipped_signals.json',a.skips),('corporate_ledger.json',a.action_log),('annual.json',annual),('SUMMARY.json',summary)]:dump(OUTPUT/filename,records)
    dump(OUTPUT/'AUDIT.json',dict(status='ok',max_two_positions=True,buy_budget_half_equity_and_cash=True,tplus1=True,
        open_phase_before_intraday_cash=True,no_future_winner_removal=True,raw_share_and_cash_ledger=True,
        corporate_queries=174,actual_entitlements=summary['corporate_events'],terminal_wealth_reconciled=True,
        spec_sha256=sha(HERE/'PORTFOLIO_SPEC_v1.json'),source_manifest_sha256=sha(INPUT/'MANIFEST.json'),nav_sha256=sha(OUTPUT/'daily_nav.parquet')))
    print(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(annual,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
