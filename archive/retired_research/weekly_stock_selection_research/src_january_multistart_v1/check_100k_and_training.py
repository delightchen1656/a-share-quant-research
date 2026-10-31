import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
import json
import math
import numpy as np
import pandas as pd
from common import BASE,AUDIT,dump,fee,install_development_guard
from checks import ToyQuotes
from portfolio import simulate
from account_validation import independent_account
from annual_training import fit_year,predict_year
from panel_builder import symbol_panel

def main():
    install_development_guard()
    q=ToyQuotes();mon='2021-01-04'
    scores=pd.DataFrame([dict(method='TEST',symbol='SYNTH_A',monday=mon,rank=1)])
    plan=pd.DataFrame([dict(signal_date='2020-12-31',monday=mon,tuesday='2021-01-05',year=2021)])
    r=simulate('TEST',scores,q,[],plan=plan,start=mon,end='2021-01-05')
    buy=r['transactions'].query("side == 'buy'").iloc[0]
    assert r['initial_cash']==100000. and buy.qty==900 and buy.fee==5.18
    assert math.isclose(r['daily'].equity.iloc[-1],100000+450-fee(9000,'buy',mon)-fee(9450,'sell','2021-01-05'),abs_tol=1e-7)
    independent_account(r,[],q)
    terminal=simulate('TEST',scores,q,[],plan=plan,start=mon,end=mon)
    assert terminal['daily'].positions.iloc[-1]==1 and terminal['trades'].status.iloc[0]=='open'
    independent_account(terminal,[],q)
    old=BASE/'audits/holdout_restricted'
    panel=pd.read_parquet(old/'research_v1/weekly_factor_panel.parquet')
    extra=pd.read_parquet(old/'monday_factor_v4/new_factor_panel.parquet')
    assert panel[['signal_date','symbol']].equals(extra[['signal_date','symbol']])
    panel['momentum120']=extra.momentum120
    pack,audit=fit_year(panel,2019)
    predicted=predict_year(pack,panel,2019)
    reference=pd.read_parquet(old/'monday_factor_v5/fold_scores_2019.parquet')
    reference=reference.loc[reference.variant.eq('combine__long_momentum')&reference['rank'].le(10)]
    assert list(zip(predicted.signal_date,predicted.symbol,predicted['rank']))==list(zip(reference.signal_date,reference.symbol,reference['rank']))
    np.testing.assert_allclose(predicted.score,reference.score,atol=1e-11,rtol=1e-11)
    # Reconstructed later-period adapter must reproduce existing feature/label values.
    schedule=pd.read_parquet(old/'research_v1/weekly_schedule.parquet')
    for symbol in ['600000.SH','000001.SZ','600519.SH']:
        frame=pd.read_parquet(BASE/'inputs_pre2025/kline_dev_v1'/f'{symbol}.parquet')
        rebuilt=symbol_panel(symbol,frame,qdays(),schedule)
        prior=panel.loc[panel.symbol.eq(symbol)].sort_values('signal_date')
        rebuilt=rebuilt.sort_values('signal_date')
        assert rebuilt.signal_date.tolist()==prior.signal_date.tolist()
        from common import SPEC
        np.testing.assert_allclose(rebuilt[SPEC['factors']+['ordinary_quote_excess']],prior[SPEC['factors']+['ordinary_quote_excess']],atol=1e-12,rtol=1e-12,equal_nan=True)
    dump(AUDIT/'training_and_100k_validation.json',dict(passed=True,
        actual_100k_lot_and_minimum_commission_checked=True,cutoff_open_positions_retained=True,
        annual2019fit_reproduces_saved_top10_and_scores=True,training_audit=audit,
        panel_builder_reproduces_3_pre2024symbols=True,no_posterior_read=True))
    print('100k fees/lots, terminal inventory, annual2019 scores and feature/label adapter verified.',flush=True)

def qdays():
    c=pd.read_parquet(BASE/'inputs_pre2025/calendar_dev_v1.parquet')
    return pd.DatetimeIndex(c.loc[c.is_trading_day.eq(1),'calendar_date'])

if __name__=='__main__':main()
