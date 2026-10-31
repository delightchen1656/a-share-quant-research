"""Rebase existing frozen observations; preserve every shape/signal and all extreme dates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from refresh_mainboard_viewer import lock
from build_market_patterns import CURRENT,sha,dump
from observe_next_open60 import observe,OBSERVATION_VERSION,MATCH_DIRECTORY

def main():
    with lock('REFRESH.lock'):
        before=CURRENT.read_bytes();b=json.loads(before)
        if b.get('observation_version')==OBSERVATION_VERSION:print('Already rebased.');return
        for key,hkey in [('manifest','manifest_sha256'),('events','events_sha256')]:assert sha(b[key])==b[hkey]
        m=json.loads(Path(b['manifest']).read_text(encoding='utf-8'));lookup={(r['code'],r['mode']):r for r in m['files']}
        dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(b['calendar']).date));dates=dates[dates<=b['cutoff']]
        old=pd.read_parquet(b['events']);metrics=[]
        for n,(code,g) in enumerate(old.groupby('code'),1):
            fs={}
            for mode in ['raw','qfq']:
                r=lookup[(code,mode)];assert sha(r['path'])==r['snapshot_sha256']
                fs[mode]=pd.read_parquet(r['path']).set_index('date').reindex(dates)
            raw=fs['raw'];q=fs['qfq'];v=raw.volume.to_numpy(float)
            valid=raw.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(v)&(v>0)
            for f in [raw,q]:
                for col in ['open','high','low','close']:
                    a=f[col].to_numpy(float);valid &= np.isfinite(a)&(a>0)
            for e in g.itertuples():
                t=dates.get_loc(pd.Timestamp(e.signal_date))
                metrics.append(dict(event_id=e.event_id,raw_signal_close=float(raw.close.iloc[t]),
                    **observe(q.open.to_numpy(float),q.high.to_numpy(float),q.low.to_numpy(float),q.close.to_numpy(float),raw.open.to_numpy(float),valid,dates,t)))
            if n%250==0:print('Rebased',n,'stocks',flush=True)
        indexed=pd.DataFrame(metrics).set_index('event_id');final=old.copy()
        for col in indexed.columns:final[col]=final.event_id.map(indexed[col])
        changed={'adjusted_reference_price','raw_reference_price','adjusted_price_change','peak_return60','peak40_same_cohort','trough_return60','max_drop60'}
        preserved=[c for c in old.columns if c not in changed]
        pd.testing.assert_frame_equal(final[preserved],old[preserved])
        assert final.event_id.is_unique and len(final)==len(old)
        complete=final[final.peak_complete60]
        assert complete.entry_open.gt(0).all() and (complete.entry_date>complete.signal_date).all()
        assert np.allclose(complete.peak_return60,complete.peak_price60/complete.entry_open-1)
        assert np.allclose(complete.max_drop60,np.maximum(0,1-complete.trough_price60/complete.entry_open))
        out=Path(b['events']).parent.parent/MATCH_DIRECTORY;assert not out.exists();out.mkdir()
        final.to_parquet(out/'events.parquet',index=False)
        spec=json.loads((Path(b['events']).parent/'SPEC.json').read_text(encoding='utf-8'))
        spec.update(observation_version=OBSERVATION_VERSION,observation='D1..D60 extremes relative strict D1 adjusted open; entry-day high and low included; no roll forward if D1 missing.',source_events_sha256=b['events_sha256'])
        dump(out/'SPEC.json',spec)
        summary=json.loads(Path(b['summary']).read_text(encoding='utf-8'))
        summary['groups']['volume'].update(complete60=len(complete),mean_peak60=float(complete.peak_return60.mean()),median_peak60=float(complete.peak_return60.median()))
        summary.update(observation_version=OBSERVATION_VERSION,return_basis='next_session_open');dump(out/'SUMMARY.json',summary)
        audit=dict(status='ok',signals=len(final),complete60=len(complete),entry_available=int(final.entry_open.notna().sum()),
            source_generation=b['generation'],source_events_sha256=b['events_sha256'],preserved_columns=preserved,
            all_shapes_and_extreme_prices_dates_unchanged=True,no_rematching=True,no_market_sources_modified=True)
        dump(out/'REBASE_AUDIT.json',audit)
        updated=dict(b,events=str((out/'events.parquet').resolve()),events_sha256=sha(out/'events.parquet'),summary=str((out/'SUMMARY.json').resolve()),
            observation_version=OBSERVATION_VERSION,return_basis='next_session_open',rebase_audit=str((out/'REBASE_AUDIT.json').resolve()))
        updated['generation']=b['cutoff']+'_'+updated['events_sha256'][:14]
        dump(out/'READY.json',updated);assert CURRENT.read_bytes()==before;dump(CURRENT,updated)
        print(json.dumps({k:v for k,v in audit.items() if k!='preserved_columns'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
