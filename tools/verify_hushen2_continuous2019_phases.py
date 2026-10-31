"""Verify continuous path slicing; phase returns must compound to each full account."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from replay_hushen2_live_approx import dump,sha
from replay_hushen2_continuous2019_phases import SOURCE

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert sha(SOURCE/'INPUT_PACK.pkl')==protocol['source_sha256']
    assert sha(SOURCE/'PHASES.json')==protocol['source_phases_sha256']
    m=pd.read_parquet(out/'START_METRICS.parquet');parts=pd.read_parquet(out/'SEGMENT_METRICS.parquet')
    index=pd.read_parquet(SOURCE/'SSE_INDEX.parquet').close
    assert len(m)==58 and len(parts)==58*18
    assert not json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8'))
    max_metric_error=max_compound_error=max_amount_error=0.;boundary_rows=[]
    def check(frame,base,include_first,days,row):
        e=frame.equity.to_numpy();daily=np.r_[e[0]/base-1,np.diff(e)/e[:-1]] if include_first else np.diff(e)/e[:-1]
        path=np.r_[base,e] if include_first else e
        actual={'cumulative_return':e[-1]/base-1,'annualized_return':(e[-1]/base)**(365/days)-1,
                'maximum_drawdown':(path/np.maximum.accumulate(path)-1).min()}
        if daily.std(ddof=0)>0:actual['sharpe']=np.sqrt(252)*daily.mean()/daily.std(ddof=0)
        return max(abs(actual[k]-float(row[k])) for k in actual)
    for row in m.to_dict('records'):
        ordinal=int(row['start_ordinal']);start=pd.Timestamp(row['start']);end=pd.Timestamp(row['end'])
        folder=out/'paths'/f'{ordinal:02d}_{row["start"]}'
        c=pd.read_parquet(folder/'EQUITY.parquet').sort_values('date').set_index('date')
        assert c.index.is_unique and c.index.min()==start and c.index.max()==end
        max_metric_error=max(max_metric_error,check(c,100000,True,(end-start).days,row))
        segments=parts.loc[parts.start_ordinal.eq(ordinal)].sort_values('phase')
        previous=100000.;product=1.;amount=0.
        for s in segments.to_dict('records'):
            left=pd.Timestamp(s['effective_start']);right=pd.Timestamp(s['end']);g=c.loc[left:right]
            assert abs(s['base_equity']-previous)<1e-8
            assert abs(s['end_equity']-float(g.equity.iloc[-1]))<1e-8
            max_metric_error=max(max_metric_error,check(g,s['base_equity'],s['phase']==1,(right-left).days,s))
            benchmark=float(index.loc[right]/index.loc[left]-1)
            assert abs(benchmark-s['benchmark_return'])<1e-12
            if s['phase']!=1:
                assert s['opening_positions']==int(c.loc[left,'positions'])
                assert s['opening_pending']==int(c.loc[left,'pending'])
            boundary_rows.append({k:s[k] for k in ['phase','start_ordinal','effective_start','base_equity','opening_positions','opening_pending','boundary_held_symbols']})
            product*=1+s['cumulative_return'];amount+=s['end_equity']-s['base_equity'];previous=s['end_equity']
        max_compound_error=max(max_compound_error,abs(product-c.equity.iloc[-1]/100000))
        max_amount_error=max(max_amount_error,abs(amount-(c.equity.iloc[-1]-100000)))
        trades=pd.read_parquet(folder/'TRADES.parquet')
        assert pd.to_datetime(trades.exit_date).gt(pd.to_datetime(trades.entry_date)).all()
        assert pd.to_datetime(trades.exit_date).le(end).all()
    assert max_metric_error<1e-10 and max_compound_error<1e-10 and max_amount_error<1e-6
    pd.DataFrame(boundary_rows).to_parquet(out/'BOUNDARY_STATES.parquet',index=False)
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
    summary['verification']=dict(metric_error=max_metric_error,compound_error=max_compound_error,amount_error=max_amount_error)
    summary['positive_paths']=int(m.cumulative_return.gt(0).sum())
    summary['best_path']=m.loc[m.cumulative_return.idxmax()].to_dict();summary['worst_path']=m.loc[m.cumulative_return.idxmin()].to_dict()
    dump(out/'SUMMARY.json',summary)
    dump(out/'VERIFICATION.json',dict(status='passed',continuous_paths=58,phase_slices=1044,
         no_phase_reset='Each worker calls the simulator once for the full2019-to-end account; boundaries are used only in post-run attribution.',
         metric_error=max_metric_error,compound_error=max_compound_error,amount_error=max_amount_error,
         source_quote_directory_read=False,production_or_account_modified=False,action_coverage_gaps=0,
         hashes={x.name:sha(x) for x in [out/'PROTOCOL.json',out/'INPUT_PACK.pkl',out/'START_METRICS.parquet',out/'SEGMENT_METRICS.parquet',out/'BOUNDARY_STATES.parquet']}))
    print(json.dumps(dict(status='passed',paths=58,slices=1044,metric_error=max_metric_error,compound_error=max_compound_error,amount_error=max_amount_error),ensure_ascii=False))

if __name__=='__main__':main()
