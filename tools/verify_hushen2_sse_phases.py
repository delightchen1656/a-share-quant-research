"""Independent phase boundaries, path metrics and account-sample verification."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from replay_hushen2_live_approx import dump,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out)
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
    index=pd.read_parquet(out/'SSE_INDEX.parquet').close
    index.index=pd.to_datetime(index.index)
    phases=json.loads((out/'PHASES.json').read_text(encoding='utf-8'))
    metrics=pd.read_parquet(out/'START_METRICS.parquet')
    assert len(metrics)==90 and len(phases)==18
    assert not json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8'))
    error=0.
    for phase in phases:
        start=pd.Timestamp(phase['start']);end=pd.Timestamp(phase['end'])
        expected=list(index.index[(index.index>=start)&(index.index<=end)][:5])
        m=metrics.loc[metrics.phase.eq(phase['id'])].sort_values('start_number')
        assert list(pd.to_datetime(m.start))==expected
        if phase['complete']:
            confirmed=pd.Timestamp(phase['confirmed_at'])
            prices=index.loc[start:confirmed]
            assert confirmed>end
            if phase['direction']=='up':
                assert abs(index.loc[end]-prices.max())<1e-8
                assert index.loc[confirmed]/index.loc[end]<=.9+1e-12
            else:
                assert abs(index.loc[end]-prices.min())<1e-8
                assert index.loc[confirmed]/index.loc[end]>=1.1-1e-12
        for row in m.itertuples():
            folder=out/'paths'/f'{phase["id"]:02d}_{row.start_number}_{row.start}'
            curve=pd.read_parquet(folder/'EQUITY.parquet').sort_values('date')
            assert pd.Timestamp(curve.date.min())==pd.Timestamp(row.start)
            assert pd.Timestamp(curve.date.max())==end
            equity=curve.equity.to_numpy();daily=np.r_[equity[0]/100000-1,np.diff(equity)/equity[:-1]]
            values=dict(cumulative_return=equity[-1]/100000-1,maximum_drawdown=(equity/np.maximum.accumulate(equity)-1).min(),
                        benchmark_return=index.loc[end]/index.loc[pd.Timestamp(row.start)]-1)
            values['cumulative_excess']=values['cumulative_return']-values['benchmark_return']
            if daily.std(ddof=0)>0:values['sharpe']=np.sqrt(252)*daily.mean()/daily.std(ddof=0)
            error=max(error,max(abs(float(getattr(row,k))-v) for k,v in values.items()))
            trades=pd.read_parquet(folder/'TRADES.parquet')
            if len(trades):
                assert pd.to_datetime(trades.entry_date).gt(pd.to_datetime(trades.signal_date)).all()
                assert pd.to_datetime(trades.entry_date).le(pd.to_datetime(trades.signal_date)+pd.Timedelta(days=7)).all()
                assert pd.to_datetime(trades.exit_date).gt(pd.to_datetime(trades.entry_date)).all()
                assert pd.to_datetime(trades.exit_date).le(end).all()
    assert error<1e-10
    groups=[]
    for direction in ('up','down'):
        rows=[r for r in summary['summaries'] if r['complete'] and r['direction']==direction]
        group=dict(direction=direction,complete_phases=len(rows),start_paths=sum(r['starts'] for r in rows),
             positive_phases=sum(r['means']['cumulative_return']>0 for r in rows),
             beat_phases=sum(r['means']['cumulative_excess']>0 for r in rows),
             mean_sessions=float(np.mean([r['sessions'] for r in rows])))
        for k in ['cumulative_return','benchmark_return','cumulative_excess','maximum_drawdown']:
            group[k]=float(np.mean([r['means'][k] for r in rows]))
        group['median_phase_return']=float(np.median([r['means']['cumulative_return'] for r in rows]))
        groups.append(group)
    summary['completed_phase_groups']=groups
    summary['verification_max_error']=error
    summary['mean_aggregation']='Equal completed-phase weights,then first-week start averages; phase lengths differ; ongoing phase excluded from grouped results'
    dump(out/'SUMMARY.json',summary)
    input_audit=json.loads((out/'INPUT_AUDIT.json').read_text(encoding='utf-8'))
    input_audit['initial_pack_hash_stage']='prepared before supplemental action coverage receipts'
    input_audit['post_coverage_input_pack_sha256']=sha(out/'INPUT_PACK.pkl')
    dump(out/'INPUT_AUDIT.json',input_audit)
    dump(out/'VERIFICATION.json',dict(status='passed',phases=18,paths=90,metric_error=error,
         first5_starts_checked=True,extreme_and_confirmation_dates_checked=True,T1_and7calendar_checked=True,
         accounting_checked_in_workers=True,action_coverage_gaps=0,production_or_account_modified=False,
         hashes={x.name:sha(x) for x in [out/'PROTOCOL.json',out/'PHASES.json',out/'SIGNALS.parquet',out/'START_METRICS.parquet',out/'INPUT_PACK.pkl',Path(__file__).with_name('replay_hushen2_sse_phases.py')]}))
    print(json.dumps(groups,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
