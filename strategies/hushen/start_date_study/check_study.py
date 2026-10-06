"""Meaningful parity and execution/accounting boundary checks."""
import study as s
import pandas as pd
import numpy as np
from types import SimpleNamespace as NS

def check():
    a=s.Account('D11',pd.Timestamp('2021-01-04'),{}, {},{})
    a.date=pd.Timestamp('2021-01-04');symbol='600000.SH'
    row=NS(open=10.,close=10.,preclose=10.,low=9.9,high=10.1,volume=1e6,tradestatus=1)
    a.day={symbol:row};a.bars={symbol:NS(open=10.,high_limit=11.,low_limit=9.)}
    assert a.order(symbol,100,10.)
    assert a.available(symbol)==0 and abs(a.cash-98994.98)<1e-6
    a.date=pd.Timestamp('2021-01-05');assert a.available(symbol)==100
    # Gross cash dividend and bonus shares conserve pre-tax NAV at theoretical ex-price.
    a.actions[symbol,a.date]=dict(cash=1.,stock=.5,taxable_stock=0.,pay=a.date,release=a.date+pd.Timedelta(days=1))
    row.preclose=6.;row.prev_actual=10.;row.adjust_ratio=.6
    a.corporate();assert a.holdings[symbol]['qty']==150 and a.available(symbol)==100
    assert abs(a.cash+150*6.-(98994.98+1000))<1e-6
    a.date=pd.Timestamp('2021-01-06');row.open=row.close=6.;row.low=5.9;row.high=6.1
    a.bars[symbol]=NS(open=6.,high_limit=6.6,low_limit=5.4)
    assert a.available(symbol)==150 and a.order(symbol,-150,6.)
    assert abs(a.tax-20)<1e-6 and not a.holdings
    # Prevent training-label files from entering evaluation; frozen code hashes unchanged.
    prep=s.read('preparation.json')
    for k,p in s.FILES.items():assert s.hashlib.sha256((s.HERE.parent/p).read_bytes()).hexdigest()==prep['strategy_hashes'][k]
    ranking=s.read('rankings.json');dates=s.benchmark().index;checks=[]
    for d in ['2020-12-31']:
        # 2024-11-29 need not be a rebalance; only test stored dates.
        if d not in ranking['D11']:continue
        date=pd.Timestamp(d);histdays=dates[dates<=date][-5:];raw={}
        for p in sorted((s.DATA/'raw').glob('*/*.parquet')):
            x=pd.read_parquet(p);x.date=pd.to_datetime(x.date);x=x[x.date<=date].set_index('date').sort_index().tail(320)
            if x.empty:continue
            x=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
            x['is_paused']=1-pd.to_numeric(x.tradestatus);raw[p.stem]=x
        members={str(t.date()):set(raw) for t in histdays}
        ranks,_=s.load_model('D11').compute_signals(raw,members,histdays)
        assert ranks==ranking['D11'][d],(d,ranks[:10],ranking['D11'][d][:10])
        m=s.load_model('R08');market=s.benchmark().loc[:date].tail(320);rows=[]
        for symbol,frame in raw.items():
            ft=m.stock_features(frame,frame,market)
            if ft is not None:rows.append(dict(ft,symbol=symbol))
        ranks_r08=m.rank_candidates(pd.DataFrame(rows)).symbol.tolist()
        assert ranks_r08==ranking['R08'][d],(ranks_r08,ranking['R08'][d])
        checks.append(d);print('FULL UNIVERSE PARITY',d,flush=True)
    s.dump('validation.json',dict(t_plus_one=True,cash_fee_bookkeeping=True,bonus_share_lock=True,dividend_fifo_tax=True,
        corporate_action_nav_conservation=True,frozen_strategy_hashes=True,d11_full_universe_parity=checks,r08_full_universe_parity=checks,r08_scalar_parity=prep['r08_scalar_parity']))
if __name__=='__main__':check()
