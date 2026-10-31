"""Independent risk and order reconciliation for the refill comparison."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);out=parser.parse_args().output
    report=json.loads((out/'COMPARISON.json').read_text(encoding='utf-8'))
    assert report['status']=='verified' and not report['unresolved_action_gaps'] and not report['held_action_conflicts']
    assert report['no_refill_control_exactly_matches_prior'] and all(report['protected_unchanged'].values())
    base=Path(__file__).resolve().parents[1]
    prior=base/'results/holdout_restricted/atr025_annual_post2024/attempt_20261022_001047'
    assert (out/'SIMULATE_SOURCE.txt').read_bytes()==(prior/'SIMULATE_SOURCE.txt').read_bytes()
    ranking=json.loads((out/'RANKING_VERIFICATION.json').read_text(encoding='utf-8'))
    assert ranking['membership_differences']==0 and ranking['score_max_abs_error']==0 and ranking['atr_max_abs_error']==0
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((out/'RUNNER_SNAPSHOT.py').read_bytes()).hexdigest()==protocol['script_sha256']
    assert protocol['slots']==5 and protocol['initial_cash']==100000 and protocol['threshold']==.025
    index=pd.read_parquet(prior/'SSE_PRICE_INDEX.parquet').set_index('date').close
    no=pd.read_parquet(out/'NO_REFILL_SIGNALS.parquet');yes=pd.read_parquet(out/'REFILL_SIGNALS.parquet')
    assert len(no.merge(yes,on=['date','symbol']))==len(no)
    added=yes.merge(no[['date','symbol']],on=['date','symbol'],how='left',indicator=True)
    assert added.loc[added._merge.eq('left_only'),'original_rank'].gt(3).all()
    assert yes.atr_pct.ge(.025).all() and no.atr_pct.ge(.025).all()
    assert yes.groupby('date').size().le(3).all() and no.original_rank.le(3).all()
    groups=[]
    for summary in report['summaries']:
        folder=out/summary['variant']/summary['group']
        m=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet')
        t=pd.read_parquet(folder/'TRADES.parquet');a=pd.read_parquet(folder/'FIXED_ORDER_ATTEMPTS.parquet')
        assert len(m)==summary['runs']
        signals=no if summary['variant']=='no_refill' else yes
        joined=t.merge(signals[['date','symbol','atr_pct']],left_on=['signal_date','symbol'],right_on=['date','symbol'],how='left',validate='many_to_one')
        assert joined.atr_pct.ge(.025).all()
        for row in m.itertuples():
            cc=c.loc[c.start_ordinal.eq(row.start_ordinal)].sort_values('date')
            tt=t.loc[t.start_ordinal.eq(row.start_ordinal)];aa=a.loc[a.start_ordinal.eq(row.start_ordinal)]
            e=cc.equity.to_numpy();returns=np.r_[e[0]/100000-1,e[1:]/e[:-1]-1]
            span=(cc.date.iloc[-1]-cc.date.iloc[0]).days
            annual=(e[-1]/100000)**(365/span)-1
            bench=(index.loc[cc.date.iloc[-1]]/index.loc[cc.date.iloc[0]])**(365/span)-1
            expected=[e[-1]/100000-1,annual,bench,annual-bench,(e/np.maximum.accumulate(e)-1).min(),np.sqrt(252)*returns.mean()/returns.std(ddof=0)]
            actual=[row.cumulative_return,row.annualized_return,row.benchmark_annualized,row.annualized_excess,row.maximum_drawdown,row.sharpe_zero_rf_252_ddof0]
            assert np.allclose(expected,actual,rtol=0,atol=1e-12)
            assert aa.filled_quantity.gt(0).sum()==len(tt)==row.filled_orders
            assert not aa.duplicated(['symbol','signal_date']).any()
            assert row.unfilled_orders==row.expired_entry_orders+aa.filled_quantity.eq(0).sum()
            assert row.pending_orders_created==row.filled_orders+row.unfilled_orders
            assert row.filled_orders==row.take_count+row.stop_count+row.expiry_count
            assert not row.open_positions_at_end and not row.pending_orders_at_end
            for reason in ['take','stop','expiry']:assert tt.reason.eq(reason).sum()==getattr(row,reason+'_count')
            filled=aa.loc[aa.filled_quantity.gt(0)]
            matched=tt.assign(signal_date=tt.signal_date.astype(str)).merge(filled[['symbol','signal_date','date']],on=['symbol','signal_date'],validate='one_to_one')
            assert len(matched)==len(tt) and pd.to_datetime(matched.date).eq(matched.entry_date).all()
            assert (tt.entry_date>tt.signal_date).all() and ((tt.entry_date-tt.signal_date).dt.days<=7).all()
            assert (tt.exit_date>tt.entry_date).all()
        for key,value in summary['means'].items():assert abs(m[key].mean()-value)<1e-12
        if summary['variant']=='no_refill':
            old=pd.read_parquet(prior/summary['group']/'EQUITY_CURVES.parquet')
            pd.testing.assert_frame_equal(c[['start_ordinal','date','equity']],old[['start_ordinal','date','equity']],check_exact=True)
        groups.append(dict(variant=summary['variant'],group=summary['group'],paths=len(m),risk_recomputed=True,orders_reconciled=True))
    verified=dict(status='verified',total_paths=sum(x['paths'] for x in groups),groups=groups,
        atr_threshold_and_no_refill_subset_verified=True,signal_window_and_tplus1_verified=True,
        original_account_engine_byte_identical=True,original_top3_scores_and_atr_exact=True,
        input_hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.parquet')})
    (out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(verified,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in verified.items() if k!='input_hashes'},ensure_ascii=False))


if __name__=='__main__':main()
