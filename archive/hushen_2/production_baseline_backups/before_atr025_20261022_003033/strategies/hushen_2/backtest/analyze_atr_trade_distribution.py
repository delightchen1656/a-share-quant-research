"""Descriptive ATR buckets for selected replay; no strategy selection or account writes."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / 'results/holdout_restricted/fixed_ioc_atr_price_q1_2020/attempt_20261020_051613'


def summarize(frame):
    records = []
    for bucket, group in frame.groupby('atr_bucket', observed=False):
        r = group['return']
        records.append(dict(bucket=str(bucket), n=len(group),
            mean_return_pct=float(r.mean()*100) if len(r) else None,
            median_return_pct=float(r.median()*100) if len(r) else None,
            win_pct=float(r.gt(0).mean()*100) if len(r) else None,
            p10_return_pct=float(r.quantile(.1)*100) if len(r) else None,
            p90_return_pct=float(r.quantile(.9)*100) if len(r) else None,
            take_count=int(group.reason.eq('take').sum()),
            stop_count=int(group.reason.eq('stop').sum()),
            expiry_count=int(group.reason.eq('expiry').sum()),
            other_count=int((~group.reason.isin(['take','stop','expiry'])).sum())))
    return records


def main():
    protocol = json.loads((SOURCE/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert protocol['atr'] == 'price'
    trades = pd.read_parquet(SOURCE/'TRADES.parquet')
    signals = pd.read_parquet(SOURCE/'FROZEN_SIGNALS.parquet')
    joined = trades.merge(signals[['date','symbol','atr_pct']],
        left_on=['signal_date','symbol'], right_on=['date','symbol'], validate='many_to_one')
    assert len(joined) == len(trades) and joined.atr_pct.notna().all()
    assert joined.atr_pct.between(.015-1e-10,.05+1e-10).all()
    assert np.allclose(joined['return'], joined.pnl/joined.entry_cost)
    labels=['1.5–<2%','2–<2.5%','2.5–<3%','3–<3.5%','3.5–<4%','4–<4.5%','4.5–5%']
    joined['atr_bucket']=pd.cut(joined.atr_pct,[.015-1e-9,.02,.025,.03,.035,.04,.045,.05+1e-9],right=False,labels=labels)
    primary=joined.loc[joined.start_ordinal.eq(1)].copy()
    out=BASE/'results/holdout_restricted/atr_trade_distribution'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    result=dict(source=str(SOURCE), end=protocol['end'],
        policy='price TR SMA14 / signal close, clipped 1.5%-5%; fixed IOC; historical expiry close',
        method='Primary earliest start 2020-01-02, net trade returns including fees and corporate actions; split by entry year. Other starts are dependent sensitivity observations, not independent samples. No threshold optimization.',
        source_hashes={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ['TRADES.parquet','FROZEN_SIGNALS.parquet','PROTOCOL.json']},
        primary_trades=len(primary), reasons=primary.reason.value_counts().to_dict(),
        primary_all=summarize(primary),
        primary_pre2025=summarize(primary.loc[primary.entry_year.le(2024)]),
        primary_post2024=summarize(primary.loc[primary.entry_year.ge(2025)]),
        dependent_all_58_paths=summarize(joined),
        dependent_all_58_pre2025=summarize(joined.loc[joined.entry_year.le(2024)]),
        dependent_all_58_post2024=summarize(joined.loc[joined.entry_year.ge(2025)]),
        per_start_bucket_robustness=[],
        trade_return_histogram={})
    for bucket, group in joined.groupby('atr_bucket', observed=False):
        means=group.groupby('start_ordinal')['return'].mean()*100
        result['per_start_bucket_robustness'].append(dict(bucket=str(bucket), starts=len(means),
            equal_start_mean_pct=float(means.mean()), min_start_mean_pct=float(means.min()),
            max_start_mean_pct=float(means.max()), positive_start_count=int(means.gt(0).sum())))
    bins=[-np.inf,-.10,-.05,0,.05,.10,.20,np.inf]
    hist_labels=['<-10%','-10–<-5%','-5–<0%','0–<5%','5–<10%','10–<20%','>=20%']
    primary['return_bucket']=pd.cut(primary['return'],bins,labels=hist_labels,right=False)
    for bucket,group in primary.groupby('atr_bucket',observed=False):
        result['trade_return_histogram'][str(bucket)]={str(k):int(v) for k,v in group.return_bucket.value_counts(sort=False).items()}
    (out/'ATR_DISTRIBUTION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(out)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
