"""Behavioral regression plus reconciliation of completed historical runs."""
from types import SimpleNamespace as NS
import ast, copy, json, re
import numpy as np
import pandas as pd
import backtest as bt
import research as r

S='603325.SH'
D=pd.Timestamp('2020-01-02')

class Toy(dict):
    def __init__(self):
        super().__init__();self.outs={};self.dates=pd.bdate_range('2020-01-01',periods=4)
        self.actions=NS(ensure=lambda s,d:None)
        for d in self.dates:
            self[d]={S:NS(open=10.,high=10.5,low=9.5,close=10.,preclose=10.,volume=1000000.,amount=1e7,turn=1.,
                          tradestatus=1.,isST=0.,volume20=1000000.,prev_actual=10.,adjust_ratio=1.)}

def fresh():
    market=Toy();a=bt.Account(D,market);a.step(D,1,market.dates[0],{str(market.dates[0].date()):[S]})
    return a,market

def parse_logs(path):
    text=path.read_text(encoding='utf-8-sig');orders={};fills={}
    for line in text.splitlines():
        def get(pattern):
            m=re.search(pattern,line);return m.group(1) if m else None
        oid=get(r"'order_id': '([^']+)'")
        if not oid:continue
        if 'INFOORDER' in line:
            row=orders.setdefault(oid,dict(symbol=get(r"'symbol': '([^']+)'"),states=[],max_filled=0,log_rows=0))
            row['log_rows']+=1
            status=get(r"'status': ORDER_STATUS\.([A-Z_]+)")
            if status not in row['states']:row['states'].append(status)
            row['max_filled']=max(row['max_filled'],int(get(r"'filled_amount': (\d+)") or 0))
            row['limit']=float(get(r"'limit_price': ([0-9.]+)") or 0)
        if 'INFOFILL' in line:
            eid=get(r"'exec_id': '([^']+)'")
            row=fills.setdefault(eid,dict(order_id=oid,quantity=int(get(r"'last_quantity': (\d+)")),
                price=float(get(r"'last_price': ([0-9.]+)")),tax=float(get(r"'tax': ([0-9.]+)")),log_rows=0))
            row['log_rows']+=1
    return dict(versions=sorted(set(re.findall(r'version=([\w-]+)',text))),orders=orders,fills=fills,
                limitation='End-of-day rejection proves nonfill, not its root cause; no historical bid/ask or platform matching trace supplied.')

def main():
    checks={}
    old=ast.parse((r.HERE/'uploaded_v5.py').read_text(encoding='utf-8-sig'))
    new=ast.parse(bt.ENTRY.read_text(encoding='utf-8'))
    f=lambda t:{n.name:ast.dump(n,include_attributes=False) for n in t.body if isinstance(n,ast.FunctionDef)}
    x,y=f(old),f(new)
    checks['original_signal_history_schedule_and_targets_unchanged']=all(x[k]==y[k] for k in ['compute_signals','_handle_bar','mainboard','_fetch'])
    before_old=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='_before_trading')
    before_new=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='_before_trading')
    before_new.body=[n for n in before_new.body if not (isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Attribute)
        and isinstance(n.targets[0].value,ast.Name) and n.targets[0].value.id=='g' and n.targets[0].attr.startswith('exec_'))]
    checks['before_trading_only_adds_receipt_reset']=ast.dump(before_old,include_attributes=False)==ast.dump(before_new,include_attributes=False)
    a,market=fresh()
    checks['opening_limit_respected']=bool(a.trades and a.trades[0]['price']<=a.order_audit[0]['limit'])
    checks['t_plus_one']=a.available(S)==0
    checks['positive_buy_lots']=all(t['qty']%100==0 for t in a.trades if t['qty']>0)
    checks['cash_conservation']=np.isclose(a.cash+sum(t['qty']*t['price'] for t in a.trades),100000-a.fees-a.tax)
    count=len(a.trades);a.m._handle_bar(a.context,a.bars)
    checks['same_day_duplicate_execution_blocked']=len(a.trades)==count
    checks['buy_below_open_not_forced_to_fill']=a.order(S,100,9.) is None and len(a.trades)==count
    checks['sell_above_open_not_forced_to_fill']=a.order(S,-100,11.) is None and len(a.trades)==count
    b=NS(open=2.71,high_limit=2.98,low_limit=2.44)
    checks['buy_tick_round_up']=a.m._limit_price(b,True)==2.72
    checks['sell_tick_round_down']=a.m._limit_price(b,False)==2.70
    try:
        a.m._init(NS(run_info=NS(frequency='1m')));checks['reject_minute_frequency']=False
    except ValueError:checks['reject_minute_frequency']=True
    a,market=fresh();m=a.m
    odr=NS(order_id='receipt',symbol=S,amount=100,filled_amount=100,limit_price=10.01,status='FILLED')
    m.g.alpha_order_ids.add('receipt');m.on_order(a.context,odr);m.on_order(a.context,odr)
    checks['duplicate_order_receipt_dedup']=len(m.g.exec_seen_orders)==1
    stale=copy.copy(odr);stale.status='ACTIVE';stale.filled_amount=0;m.on_order(a.context,stale)
    checks['late_receipt_no_state_regression']=m.g.exec_orders['receipt'].status=='FILLED'
    bad=NS(order_id='receipt',order_book_id=S,exec_id='fill',last_quantity=100,last_price=10.02,tax=0.,side='BUY')
    m.on_trade(a.context,bad);m.on_trade(a.context,bad)
    checks['duplicate_fill_dedup']=len(m.g.exec_seen_trades)==1
    checks['simulator_limit_breach_alert']=any('LIMIT_BREACH' in v for v in m.g.exec_audit)
    checks['limit_breach_stops_new_submissions']=m.g.exec_halt and m._submit(a.context,S,100,10.01) is None
    a.date=pd.Timestamp('2026-10-08')
    bad=NS(order_id='receipt',order_book_id=S,exec_id='tax',last_quantity=100,last_price=10.,tax=1.,side='SELL')
    m.on_trade(a.context,bad)
    checks['simulator_legacy_stamp_alert']=any('FEE_MISMATCH' in v for v in m.g.exec_audit)
    market=Toy();a=bt.Account(D,market);a.defer=True
    a.step(D,1,market.dates[0],{str(market.dates[0].date()):[S]})
    target=a.m.g.alpha_targets[S]
    checks['failed_orders_do_not_create_holdings']=not a.holdings and not a.trades and a.cash==100000
    a.defer=False;a.step(market.dates[2],2,D,{})
    checks['failed_target_retried_next_session']=a.holdings[S]['qty']==target and len(a.trades)==1
    market=Toy();a=bt.Account(D,market);real_order=a.m.order
    a.m.order=lambda s,q,price=None:real_order(s,min(100,q),price)
    a.step(D,1,market.dates[0],{str(market.dates[0].date()):[S]})
    target=a.m.g.alpha_targets[S]
    a.m.order=real_order;a.step(market.dates[2],2,D,{})
    checks['partial_fill_next_day_buys_only_remaining']=a.trades[0]['qty']==100 and a.trades[1]['qty']==target-100 and a.holdings[S]['qty']==target
    a,market=fresh();a.m.get_open_orders=lambda:[NS(order_id='foreign',symbol=S)]
    try:
        a.m._submit(a.context,S,100,10.01);checks['foreign_open_orders_rejected']=False
    except RuntimeError:checks['foreign_open_orders_rejected']=True
    results=json.loads((r.HERE/'halfyear_results.json').read_text(encoding='utf-8'))
    checks['fourteen_fresh_100k_accounts']=len(results)==14 and all(q['initial_cash']==100000 and q['end']=='2026-09-30' for q in results)
    checks['held_corporate_actions_resolved']=all(q['unresolved_actions']==0 and q['reference_differences']==0 for q in results)
    for row in results:
        prefix=r.HERE/'runs'/('start_'+row['requested_start'])
        q=pd.read_parquet(str(prefix)+'_equity.parquet');t=pd.read_parquet(str(prefix)+'_trades.parquet')
        assert q.cash.ge(-.01).all()
        assert np.isclose(t[['commission','transfer','stamp']].sum().sum(),row['transaction_fees'])
        assert np.isclose(t.dividend_tax.sum(),row['dividend_tax'])
        assert (t.loc[t.qty>0,'qty']%100==0).all()
    checks['all_accounts_fee_and_cash_reconciled']=True
    audit=json.loads((r.HERE/'data_audit.json').read_text(encoding='utf-8'))
    checks['data_integrity']=not audit['errors']
    checks['future_prefix_independence']=all(audit['prefix_independence'])
    checks['three_full_universe_platform_factor_parities']=all(q['equal'] for q in audit['platform_signal_parity'])
    logs={name:parse_logs(r.HERE/name) for name in ['simulator_retrained_log.txt','simulator_v4_log.txt']}
    r.dump('log_diagnostics.json',logs)
    r.dump('validation.json',checks)
    for k,v in checks.items():print('PASS' if v else 'FAIL',k)
    assert all(checks.values()),checks

if __name__=='__main__':main()
