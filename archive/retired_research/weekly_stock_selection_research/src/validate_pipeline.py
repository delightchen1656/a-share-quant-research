import json
import math
import numpy as np
import pandas as pd
from common import BASE,AUDIT,FACTORS,dump,sha
from portfolio import simulate,Quotes
from execution import ordinary_label,fee


class ToyQuotes:
    def __init__(self,split=False,blocked=False):
        self.days=pd.to_datetime(['2020-12-31','2021-01-04','2021-01-05','2021-01-06','2021-01-11','2021-01-12'])
        if split:
            closes=[10.,10.,5.5,5.6,6.,6.]
            pres=[10.,10.,4.95,5.5,5.6,6.]
        elif blocked:
            closes=[10.,10.,9.,9.5,10.,10.5]
            pres=[10.,10.,10.,9.,9.5,10.]
        else:
            closes=[10.,10.,11.,11.,11.,11.]
            pres=[10.,10.,10.,11.,11.,11.]
        self.bars=[dict(active=True,st=False,status='1',open=close,high=close,low=close,close=close,preclose=pre,volume=1e7,amount=1e8,pctChg=0.) for close,pre in zip(closes,pres)]
        self.bars[1]['open']=10.
    def bar(self,symbol,i):
        if i<0:
            return dict(active=False,volume=0.)
        return self.bars[i]


def main():
    score=pd.DataFrame([dict(method='TEST',symbol='TEST',monday='2021-01-04',rank=1)])
    result=simulate('TEST',score,ToyQuotes(),[])
    t=result['trades'].iloc[0]
    assert t.entry_date=='2021-01-04' and t.exit_date=='2021-01-05'
    expected=1e6+9900*(11-10)-fee(99000,'buy','2021-01-04')-fee(108900,'sell','2021-01-05')
    assert math.isclose(result['daily'].equity.iloc[-1],expected,abs_tol=1e-7) and result['complete']
    delayed=simulate('TEST',score,ToyQuotes(blocked=True),[])
    assert delayed['trades'].exit_date.iloc[0]=='2021-01-12'
    assert delayed['transactions'].loc[delayed['transactions'].side.eq('sell'),'date'].tolist()==['2021-01-12']
    event=dict(event_id='TEST_SPLIT',symbol='TEST',register_date='2021-01-04',ex_date='2021-01-05',pay_date='2021-01-11',
               listing_date='2021-01-06',cash_ps=.1,bonus_ps=1.,transfer_ps=0.,supported=True,reason='')
    split=simulate('TEST',score,ToyQuotes(split=True),[event])
    t=split['trades'].iloc[0]
    assert t.entitled_extra_shares==9900 and t.gross_dividend==990 and t.sold_shares==19800
    assert t.exit_date=='2021-01-12' and split['complete']
    assert split['daily'].loc[split['daily'].date.eq('2021-01-05'),'cash_receivable'].iloc[0]==990.
    assert split['daily'].loc[split['daily'].date.eq('2021-01-11'),'cash_receivable'].iloc[0]==0.
    bad=simulate('TEST',score,ToyQuotes(split=True),[dict(event,supported=False,reason='unsupported')])
    assert not bad['complete']
    # Historical prefix replay: recompute the registered features without any
    # rows later than each sampled signal date, including cases with unknown labels.
    panel=pd.read_parquet(AUDIT/'weekly_factor_panel.parquet')
    chosen=panel.iloc[np.linspace(0,len(panel)-1,60,dtype=int)]
    q=Quotes()
    checked_labels=0
    for row in chosen.itertuples():
        df=pd.read_parquet(BASE/'inputs_pre2025/kline_dev_v1'/f'{row.symbol}.parquet',filters=[('date','<=',pd.Timestamp(row.signal_date))])
        frame=df.set_index('date').reindex(q.days[q.days<=pd.Timestamp(row.signal_date)])
        from common import quote_valid
        valid,num=quote_valid(frame)
        lr=np.log1p(num.pctChg/100).where(valid)
        chain=lr.cumsum()
        amt=num.amount.where(valid)
        vol=num.volume.where(valid)
        turn=pd.to_numeric(frame.turn,errors='coerce').where(valid)
        feats={}
        for n in [20,60]:
            minimum=int(np.ceil(n*.9))
            feats[f'quote_momentum{n}']=np.expm1(lr.rolling(n,min_periods=minimum).sum().iloc[-1])
            feats[f'quote_volatility{n}']=lr.rolling(n,min_periods=minimum).std().iloc[-1]
        feats['quote_reversal5']=-np.expm1(lr.rolling(5,min_periods=5).sum().iloc[-1])
        feats['quote_reversal1']=-np.expm1(lr.iloc[-1])
        feats['log_median_amount20']=np.log(amt.rolling(20,min_periods=18).median().iloc[-1])
        feats['volume_ratio5_20']=vol.rolling(5,min_periods=5).mean().iloc[-1]/vol.rolling(20,min_periods=18).mean().iloc[-1]
        feats['turnover_mean20']=turn.rolling(20,min_periods=18).mean().iloc[-1]
        lo=chain.rolling(20,min_periods=18).min().iloc[-1]
        hi=chain.rolling(20,min_periods=18).max().iloc[-1]
        feats['quote_high_position20']=(chain.iloc[-1]-lo)/(hi-lo) if hi>lo else .5
        feats['quote_efficiency20']=abs(lr.rolling(20,min_periods=18).sum().iloc[-1])/lr.abs().rolling(20,min_periods=18).sum().iloc[-1]
        feats['last_quote_change']=np.expm1(lr.iloc[-1])
        for feature in FACTORS:
            np.testing.assert_allclose(feats[feature],getattr(row,feature),rtol=1e-10,atol=1e-10,equal_nan=True)
        m=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.monday)))
        e=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.tuesday)))
        y=ordinary_label(m['open'],e['close'],m['active'],e['active'],m['close'],e['preclose'],row.market_return)
        np.testing.assert_allclose(y,row.ordinary_quote_excess,atol=1e-12,rtol=1e-12,equal_nan=True)
        checked_labels+=1
    train=json.loads((AUDIT/'training_audit.json').read_text(encoding='utf-8'))
    assert all(f['last_training_label_date']<f"{f['year']}-01-01" for f in train['folds'])
    scores=pd.read_parquet(AUDIT/'selection_scores_top30.parquet')
    assert (pd.to_datetime(scores.signal_date)<pd.to_datetime(scores.monday)).all()
    checks=dict(full_ordinary_portfolio_reconciled=True,blocked_exit_retained_until_later_Tuesday=True,
                cash_share_listing_and_payment_dates_separate=True,unsupported_events_not_silently_deleted=True,
                historical_prefix_factor_replays=60,ordinary_label_replays=checked_labels,
                all_models_labels_mature_before_fold=True,no_Monday_close_in_selection=True)
    dump(AUDIT/'pipeline_validation.json',dict(passed=True,checks=checks,portfolio_code_sha256=sha(BASE/'src/portfolio.py')))
    print(checks,flush=True)


if __name__=='__main__':
    main()
