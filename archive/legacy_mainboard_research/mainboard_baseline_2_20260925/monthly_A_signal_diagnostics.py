"""Read-only signal comparison; platform choices never feed local ranking."""
import json
import pandas as pd
import group_research as g
from execution_engine import rank01

def main():
    out=g.HERE/'monthly_A_alignment_20260924'
    signals=json.loads((out/'platform_signals.json').read_text(encoding='utf-8'))
    factors=pd.read_parquet(g.HERE/'cadence_multiround_100k/exact_date_factors.parquet')
    index=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet');index['date']=pd.to_datetime(index.date)
    rows=[]
    for signal in signals:
        d=pd.Timestamp(signal['date']);x=factors[factors.execute_date==d].sort_values('symbol').copy()
        h=index[index.date<=x.signal_date.iloc[0]].sort_values('date')
        strong=h.close.iloc[-1]>h.close.tail(120).mean()
        eligible=set(x.symbol)
        if strong:
            x['score']=.25*rank01(x.amount20.to_numpy(),True)+.20*rank01(x.near_high.to_numpy())+.55*rank01(x.dividend.to_numpy())
        else:x=g.score(x[x.float_cap_proxy_group==1],'quality')
        x=x.sort_values(['score','symbol'],ascending=[False,True]);ranks={s:i+1 for i,s in enumerate(x.symbol)}
        selected=signal['selected'];top24=set(x.head(24).symbol)
        rows.append(dict(date=signal['date'],year=d.year,local_regime='STRONG' if strong else 'WEAK',platform_regime=signal['regime'],local_eligible=len(x),platform_eligible=signal['eligible'],platform_in_local_top24=len(set(selected)&top24),platform_in_local_eligible=len(set(selected)&eligible),platform_local_ranks={s:ranks.get(s) for s in selected}))
    f=pd.DataFrame(rows);summary=[]
    for year,z in f.groupby('year'):
        summary.append(dict(year=int(year),signals=len(z),regime_mismatches=int((z.local_regime!=z.platform_regime).sum()),mean_platform_in_local_top24=float(z.platform_in_local_top24.mean()),mean_platform_in_local_eligible=float(z.platform_in_local_eligible.mean()),mean_local_eligible=float(z.local_eligible.mean()),mean_platform_eligible=float(z.platform_eligible.mean())))
    (out/'signal_diagnostics.json').write_text(json.dumps(dict(summary=summary,rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
