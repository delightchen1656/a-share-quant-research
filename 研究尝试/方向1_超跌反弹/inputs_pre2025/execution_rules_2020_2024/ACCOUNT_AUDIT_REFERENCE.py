"""Independent replay checks for the frozen 1m/20-slot account result."""
from decimal import Decimal
from collections import defaultdict
import pandas as pd

ZERO=Decimal('0.00')

def audit_result(result,signals,calendar):
    """No file I/O. Reconcile every money/ownership step and daily NAV."""
    ordinal={x:i for i,x in enumerate(calendar)}
    journal=defaultdict(list)
    for row in result['journal']:journal[row['date']].append(row)
    schedule=defaultdict(list)
    signal_key=set()
    for item in signals:
        e=dict(item)
        if result['summary']['scope']=='leaders' and not e.get('is_leader',False):continue
        signal_key.add((e['code'],e['date']))
        i=ordinal[e['date']]+1
        if i<len(calendar):schedule[calendar[i]].append(e['code'])
    cash=Decimal('1000000.00');recv=ZERO;tax=ZERO;inventory={};bought={};locks=defaultdict(list)
    max_positions=0;max_budget=ZERO;max_residual=ZERO;closed_pnl=ZERO
    for nav in result['nav']:
        day=nav['date'];lastphase=-1;seen_open_buy=False
        actual_buys=[]
        for row in journal.get(day,[]):
            phase={'preopen':0,'open':1,'intraday':2,'close':3}[row['phase']]
            assert phase>=lastphase,('phase_order',day)
            lastphase=phase;code=row['code'];kind=row['kind']
            if kind=='buy':
                assert row['phase']=='open'
                seen_open_buy=True;actual_buys.append(code)
                assert code not in bought,('duplicate_hold',code,day)
                assert ordinal[day]==ordinal[row['signal_date']]+1
                assert (code,row['signal_date']) in signal_key
                qty=row['share_delta'];assert qty>0 and qty%100==0
                assert row['gross']==row['price']*qty
                budget=row['gross']+row['total'];assert budget<=Decimal('50000.00')
                assert budget<=cash-tax
                max_budget=max(max_budget,budget);bought[code]=day
            elif kind=='sell':
                if row['phase']=='open':assert not seen_open_buy,('open_exit_after_buy',day,code)
                assert code in bought and ordinal[day]>ordinal[bought[code]]
                assert row['share_delta']==-inventory.get(code,0)
                assert all(release<=day for release in locks[code])
                assert row['gross']==row['price']*(-row['share_delta'])
                del bought[code];locks.pop(code,None)
            elif kind=='stock_entitlement':
                assert code in bought and row['share_delta']>0
                locks[code].append(row['release'])
            cash+=row['cash_delta'];recv+=row['receivable_delta'];tax+=row['sold_tax_payable_delta']
            inventory[code]=inventory.get(code,0)+row['share_delta']
            assert inventory[code]>=0 and cash>=0 and cash-tax>=0
            assert cash==row['cash_after'] and recv==row['receivable_after'] and tax==row['sold_tax_payable_after']
            max_positions=max(max_positions,sum(q>0 for q in inventory.values()))
            assert max_positions<=20
        assert actual_buys==sorted(actual_buys),('code_priority',day)
        assert all(code in schedule.get(day,[]) for code in actual_buys)
        assert cash==nav['cash'] and recv==nav['gross_receivable'] and tax==nav['sold_dividend_tax_payable']
        assert cash-tax==nav['spendable_cash']
        assert nav['positions']==sum(q>0 for q in inventory.values())
        assert nav['equity']==cash+nav['stock_value']+recv-tax-nav['holding_estimated_dividend_tax']
    for trade in result['trades']:
        assert trade['pnl']==trade['sale_gross']-trade['fees']+trade['dividend_gross']-trade['dividend_tax']-trade['buy_gross']
        assert trade['buy_offset']==ordinal[trade['sell_date']]-ordinal[trade['buy_date']]
        closed_pnl+=trade['pnl']
    # Separate arbitrary year boundaries from the complete-account high-water mark.
    previous=Decimal('1000000.00');globalpeak=previous;globaldd=Decimal(0)
    frame=pd.DataFrame(result['nav']);annual=[]
    for year,g in frame.groupby(frame.date.str[:4]):
        peak=previous;dd=Decimal(0)
        for x in g.equity:
            peak=max(peak,x);dd=min(dd,x/peak-1);globalpeak=max(globalpeak,x);globaldd=min(globaldd,x/globalpeak-1)
        end=g.equity.iloc[-1];annual.append(dict(year=int(year),return_pct=float(end/previous-1),max_drawdown=float(dd)))
        expected=next(x for x in result['yearly'] if x['year']==int(year))
        assert abs(annual[-1]['return_pct']-expected['return_pct'])<1e-12
        assert abs(annual[-1]['max_drawdown']-expected['max_drawdown'])<1e-12
        previous=end
    summary=result['summary']
    assert abs(float(globaldd)-summary['max_drawdown'])<1e-12
    assert closed_pnl==summary['closed_pnl']
    assert summary['final_equity']==Decimal('1000000.00')+summary['closed_pnl']+summary['open_marked_pnl']
    return dict(passed=True,journal_records=len(result['journal']),nav_dates=len(result['nav']),closed_trades=len(result['trades']),
        max_concurrent_positions=max_positions,max_buy_cost_including_fees=max_budget,ledger_cash_and_receivables_replayed=True,
        sold_tax_liabilities_replayed=True,share_inventory_replayed=True,T_plus_1=True,strict_next_official_open=True,
        open_cash_timing=True,code_priority=True,locked_shares_not_sold=True,independent_yearly_and_global_drawdown=True,
        economic_pnl_residual=summary['final_equity']-Decimal('1000000.00')-closed_pnl-summary['open_marked_pnl'])
