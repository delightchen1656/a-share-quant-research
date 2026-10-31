"""Synthetic-only checks. Never imports or reads holdout prices."""
from pathlib import Path
import json
import datetime
import hashlib
import pandas as pd
from engine import simulate,fee,tick

HERE=Path(__file__).resolve().parent


def bars(rows):
    result=[]
    for row in rows:
        d,o,h,l,c,*extra=row
        result.append(dict(date=pd.Timestamp(d),open=o,high=h,low=l,close=c,preclose=extra[0] if extra else c,
                           volume=10000000,amount=100000000,tradestatus='1',isST='0'))
    return pd.DataFrame(result).set_index('date')


def run(frame,events=None):
    return simulate('TEST','合成',10.,12.,frame,events or [])


def main():
    tests={}
    assert tick(1.005)==1.01 and tick(1.001,'up')==1.01 and tick(1.009,'down')==1.
    assert abs(fee(10000,'buy')-5.1)<1e-9 and abs(fee(10000,'sell')-10.1)<1e-9
    tests['cent_rounding_and_costs']=True
    base=[('2023-12-29',10,10.05,9.9,10,10),('2024-01-02',10,10.4,9.95,10.3,10)]
    f=bars(base+[('2024-01-03',10.4,10.5,9,9.2,10.3),('2024-01-04',8.8,9.1,8.7,9,9.2)])
    s,t,d,l=run(f)
    assert t[0]['entry_date']=='2024-01-03' and t[0]['exit_date']=='2024-01-04'
    assert t[0]['price_return']<-.1 and s['tplus1_stop']==1
    tests['next_open_not_signal_close_tplus1_gap_stop']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',10.4,12.1,9.0,10.4,10.4)])
    s,t,d,l=run(f)
    assert t[0]['exit_reason']=='stop_intraday' and s['dual_touch']==1
    tests['samebar_dual_touch_stop_first']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',12.1,12.2,9,10.4,10.4)])
    s,t,d,l=run(f)
    assert t[0]['exit_reason']=='take_profit_open' and t[0]['exit_price']==11.9
    tests['opening_target_precedes_later_intraday_stop']=True
    f=bars(base+[('2024-01-03',11.33,11.33,11.33,11.33,10.3),('2024-01-04',10.4,10.6,10.2,10.4,11.33)])
    s,t,d,l=run(f)
    assert s['buy_fills']==0 and s['cancelled_buys']==1
    tests['one_price_upper_buy_blocked_and_cancelled']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',9.36,9.36,9.36,9.36,10.4),('2024-01-05',9.1,9.3,9.0,9.2,9.36)])
    s,t,d,l=run(f)
    assert t[0]['exit_date']=='2024-01-05' and s['stop_blocked']==1
    tests['one_price_lower_stop_delayed']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',10.2,10.4,10.1,10.3,10.2),('2024-01-05',10.3,10.5,10.2,10.3,10.3)])
    event=dict(ex_date='2024-01-04',register_date='2024-01-03',cash_payment_date='2024-01-05',cash_per_share=.2,supported=True)
    s,t,d,l=run(f,[event])
    qty=t[0]['qty']
    assert abs(d[1]['cash']-d[2]['cash'])<1e-9
    assert abs(d[2]['net_receivable']-qty*.2*.8)<1e-9
    assert abs(d[3]['cash']-d[2]['cash']-qty*.2*.8)<1e-9
    assert abs(d[2]['lower']-9.9)<1e-9
    tests['cash_record_close_exdate_receivable_payment_and_level_adjustment']=True
    f=bars([('2023-12-29',10,10.1,9.9,10,10),('2024-01-02',9.8,10.0,9.7,9.9,9.8)])
    event=dict(ex_date='2024-01-02',register_date='2023-12-29',cash_payment_date='2024-01-02',cash_per_share=.2,supported=True)
    s,t,d,l=run(f,[event])
    assert s['signals']==0
    tests['cash_exdate_does_not_create_cross']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',10.4,10.5,10.2,10.4,10.4)])
    s,t,d,l=run(f,[dict(ex_date='2024-01-04',supported=False,reason='test_non_cash')])
    assert s['account_unknown'] and s['ending_qty']>0 and len(t)==1
    tests['unsupported_held_event_preserves_unknown_position']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3)])
    f.loc[pd.Timestamp('2024-01-02'),'volume']=100
    s,t,d,l=run(f)
    assert not t and s['cancelled_buys']==1
    tests['capacity_from_prior_session_only']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',10.4,10.6,9.0,10.4,10.4)])
    s,t,d,l=run(f)
    assert len(t)==1 and s['signals']==1
    tests['exit_day_no_new_entry']=True
    f=bars(base+[('2024-01-03',10.4,10.5,10.2,10.4,10.3),('2024-01-04',10.4,10.6,9.0,10.4,10.4),('2024-01-05',9.36,9.36,9.36,9.36,10.4),('2024-01-08',9.1,9.4,9.0,9.2,9.36)])
    f.loc[pd.Timestamp('2024-01-04'),['tradestatus','volume','amount']]=['0',0,0]
    s,t,d,l=run(f)
    assert t[0]['exit_date']=='2024-01-08' and any(x['held_quote_stale'] for x in d)
    tests['suspension_preserves_position_until_resume']=True
    f=bars(base+[('2024-01-03',10.2,10.4,10.1,10.3,10.1)])
    event=dict(ex_date='2024-01-03',register_date='2024-01-02',cash_payment_date='2024-01-03',cash_per_share=.2,supported=True)
    s,t,d,l=run(f,[event])
    assert t[0]['gross_dividend']==0 and not any(x['kind']=='register_close_entitlement' for x in l)
    tests['buy_exdate_does_not_earn_prior_record_entitlement']=True
    (HERE/'execution_tests.json').write_text(json.dumps(dict(completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),engine_sha256=hashlib.sha256((HERE/'engine.py').read_bytes()).hexdigest(),synthetic_only=True,tests=tests,passed=True),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(tests,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
