"""Fully funded calendar-staggered books; sum dollar NAV before measuring returns."""
import hashlib,itertools
import numpy as np
import pandas as pd
import research as r
import execution as original_engine
import round08_long_momentum as signals
import round09_affordability as base
from round03 import calendar_dates

CONFIGS=[dict(id='T%02d'%(i+1),family='carry_long',size='mid',cadence='staggered',interval=20*books,
    books=books,count=count,buffer=2*count,exposure=exposure,power=0,minimum=1500,affordable=True)
    for i,(books,count,exposure) in enumerate(itertools.product((2,3),(4,6,8),(.85,.95)))]

def allocations(books):
    cents=10_000_000;part=cents//books
    return [part/100.]*(books-1)+[(cents-part*(books-1))/100.]

def schedule(cal,start,end,books,phase):
    return [d for d in calendar_dates(cal,start,end,'monthly') if d==start or (d.month-1)%books==phase]

def combine_curves(curves):
    dates=curves[0].date.reset_index(drop=True)
    for c in curves:pd.testing.assert_series_equal(c.date.reset_index(drop=True),dates)
    out=pd.DataFrame({'date':dates})
    for col in ('equity','cash','stock_value'):
        out[col]=sum(c[col].to_numpy(float) for c in curves)
    out['holding_slots']=sum(c.holdings.to_numpy(int) for c in curves)
    assert out.cash.min()>=-.01
    assert (out.equity-out.cash-out.stock_value>=-.01).all()
    return out

def audit_trades(trades,prepared):
    if trades.empty:return 0.
    assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty,'Same-day opposite orders'
    assert (trades[trades.side=='BUY'].quantity%100==0).all()
    peak=0.
    for (date,symbol),qty in trades.groupby(['date','symbol']).quantity.sum().items():
        volume=float(prepared[pd.Timestamp(date)].loc[symbol,'volume'])
        assert volume>0
        peak=max(peak,float(qty)/volume)
    assert peak<=.05+1e-12,'Splitting accounts must not multiply allowed market volume'
    return peak

class Study(base.Study):
    def run(self,cfg,start,end=None,stress=False):
        e=r.e;end=min(r.END,start+pd.DateOffset(months=24)-pd.Timedelta(days=1)) if end is None else end
        cash_before=e.INITIAL_CASH;curves=[];orders=[];unknown=retired=0
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.cost]
        e.SELECTOR_CONTEXT=base.affordable_select
        try:
            for phase,capital in enumerate(allocations(cfg['books'])):
                e.INITIAL_CASH=capital
                e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.DELISTING_EVENTS=[]
                ranks={d:self.ranks[(cfg['family'],cfg['size'])][d].copy()
                    for d in schedule(self.cal,start,end,cfg['books'],phase)}
                for q in ranks.values():q['downside']=q.downside.pow(cfg['power'])
                # Allocate capacity budget conservatively; unused book capacity is not borrowed.
                curve,trades=e.simulate(ranks,.05/cfg['books'],cfg['count'],cfg['buffer'],cfg['exposure'],1.5,
                    self.panel,min_adjustment=cfg['minimum'])
                assert curve.cash.min()>=-.01
                curves.append(curve);orders.append(trades.assign(book=phase))
                unknown+=len(e.UNRESOLVED_ACTIONS);retired+=len(e.DELISTING_EVENTS)
        finally:
            e.INITIAL_CASH=cash_before;e.SELECTOR_CONTEXT=None
        curve=combine_curves(curves);trades=pd.concat(orders,ignore_index=True).sort_values(['date','book','symbol']).reset_index(drop=True)
        capacity=audit_trades(trades,e.PREPARED)
        z=dict(**r.measure(curve,initial_cash=100000.,risk_free_annual=.02),**r.exposure(curve),
            start=str(start.date()),end=str(curve.date.iloc[-1].date()),
            fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),
            unresolved_actions=unknown,delisting_writeoffs=retired,books=cfg['books'],
            max_aggregate_volume_fraction=capacity)
        return z,curve,trades

def install():
    r.e=original_engine;r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round22_staggered';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='12 predeclared2/3calendarphase books x4/6/8stocks each x85/95%;sum100000yuan in cents;allbooksenterfirstday;thenphase-specificmonthlycalendar,2/3monthperbook;carry_long mid equalweight;sumdollarNAV then measure;no cash borrowing or averaging Sharpe',
            fees='Original per-order fees in each book;minimum commission not shared,conservative duplicate first-entry orders;individual volume cap5%/books and total audit<=5%;minimumadjustment1500/book',
            holdings='holding_slots sums book counts,NOT unique underlying stocks; corporate-action event counts can repeat acrossbooks',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
