"""Maximum future40-session high versus the signal close; no new strategy."""
from pathlib import Path
import json
import pandas as pd
import numpy as np

BASE=Path(__file__).resolve().parent/'holdout_restricted/patterns_v1'
OUT=BASE/'first_below_ma60_v1/peak_touch_summary'

def main():
    original=pd.read_parquet(BASE/'event_results_v1r2/events.parquet')
    original=original[original.rule.eq('first')].copy()
    filtered=pd.read_parquet(BASE/'first_below_ma60_v1/selected_events.parquet')
    paths=pd.read_parquet(BASE/'event_results_v1r2/daily_paths.parquet')
    paths=paths[paths.rule.eq('first')&paths.day.between(1,40)].copy()
    results=[]
    for name,data in [('原五阴接三阳',original),('五阴接三阳且低于MA60',filtered)]:
        cohort=data[data.complete_path].copy()
        p=paths[paths.event_id.isin(cohort.event_id)]
        counts=p.groupby('event_id').agg(n=('day','size'),valid=('valid_quote','sum'),first=('day','min'),last=('day','max'))
        assert (counts.n==40).all() and (counts.valid==40).all() and (counts['first']==1).all() and (counts['last']==40).all()
        peaks=p.groupby('event_id').high_change.max()
        checked=cohort.set_index('event_id').max_high_change.sort_index()
        np.testing.assert_allclose(checked,peaks.reindex(checked.index),atol=1e-12)
        results.append(dict(group=name,all_signals=len(data),complete40_sessions=len(cohort),
            excluded_incomplete=int((~data.complete_path).sum()),mean_peak_touch=float(checked.mean()),
            median_peak_touch=float(checked.median()),p10_peak_touch=float(checked.quantile(.1)),p90_peak_touch=float(checked.quantile(.9)),
            mean_terminal_same_cohort=float(cohort.adjusted_price_change.mean()),
            median_terminal_same_cohort=float(cohort.adjusted_price_change.median()),
            touch_5pct=float(checked.ge(.05).mean()),touch_10pct=float(checked.ge(.1).mean()),touch_20pct=float(checked.ge(.2).mean()),
            never_above_signal_close=int(checked.le(0).sum()),
            by_year=[dict(year=int(y),n=len(g),mean_peak=float(g.max_high_change.mean()),median_peak=float(g.max_high_change.median())) for y,g in cohort.groupby('year')]))
    summary=dict(definition='For each signal, max(adjusted high on next40exchange sessions)/adjusted signal close -1; then arithmetic mean across signals.',
        signal_day='Third positive candle close; signal-day high excluded.',
        cohort='Only40future sessions with valid quotes, no censored or missing-path inclusion.',
        price_basis='Vendor adjusted price change, no fees; hindsight maximum is not executable realized profit.',
        negative_peaks='Keep negative when every future high is below signal close; do not floor at zero.',
        current_pool_retrospective=True,period='2019-01-01 through2026-10-26',results=results)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
