"""Current tracker approximation, all exchange starts in one requested month."""
from pathlib import Path
import argparse,json,pickle,sys
import pandas as pd
import numpy as np
import replay_hushen2_live_approx as replay

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--month',required=True);ap.add_argument('--out',required=True);args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    if not (out/'INPUT_PACK.pkl').exists():replay.prepare(out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    protocol['start_population']=f'all {args.month} exchange sessions; each starts empty, first signal at that close'
    replay.dump(out/'PROTOCOL.json',protocol)
    replay.initialize(out);p=replay.G['p']
    starts=[d for d in p['calendar'] if d.strftime('%Y-%m')==args.month and d<=p['end']]
    assert starts
    replay.dump(out/'COHORT_PROTOCOL.json',dict(month=args.month,starts=starts,end=p['end'],engine_source=replay.engine().source,execution='Same current tracker approximation as replay_hushen2_live_approx; no production/account changes'))
    rows=[];gaps=set()
    for i,start in enumerate(starts,1):
        row,missing=replay.job((i,start));rows.append(row);gaps.update(missing)
        print('PATH',i,len(starts),str(start.date()),'gaps',len(gaps),flush=True)
    replay.dump(out/'ACTION_GAPS.json',sorted(gaps))
    if gaps:
        replay.fetch_actions(out);replay.initialize(out);rows=[];gaps=set()
        for i,start in enumerate(starts,1):
            row,missing=replay.job((i,start));rows.append(row);gaps.update(missing)
    assert not gaps,sorted(gaps)
    m=pd.DataFrame(rows).sort_values('start_ordinal');m.to_parquet(out/'START_METRICS.parquet',index=False)
    keys=['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','ending_equity','filled','failed','cash_rejected','takes','stops','expiries','terminal_positions','terminal_pending']
    summary=dict(status='verified',month=args.month,starts=len(starts),end=p['end'],mean={k:float(m[k].mean()) for k in keys},median={k:float(m[k].median()) for k in keys},best=m.loc[m.cumulative_return.idxmax()].to_dict(),worst=m.loc[m.cumulative_return.idxmin()].to_dict(),positive_fraction=float(m.cumulative_return.gt(0).mean()),action_gaps=[])
    # Independent closing-equity risk recomputation; include initial capital peak.
    for folder in sorted((out/'paths').iterdir()):
        c=pd.read_parquet(folder/'EQUITY.parquet');r=json.loads((folder/'METRICS.json').read_text())
        e=c.equity.to_numpy();ret=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
        assert abs(e[-1]/100000-1-r['cumulative_return'])<1e-10
        assert abs((e/np.maximum.accumulate(np.r_[100000,e])[1:]-1).min()-r['maximum_drawdown'])<1e-10
        assert abs(np.sqrt(252)*ret.mean()/ret.std(ddof=0)-r['sharpe_zero_rf_252_ddof0'])<1e-10
    replay.dump(out/'SUMMARY.json',summary);print(json.dumps(summary,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__':main()
