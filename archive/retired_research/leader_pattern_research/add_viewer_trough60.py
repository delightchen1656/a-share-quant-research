"""Add downside observations to the published frozen events without rematching."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from compute_peak60 import peak
from compute_trough60 import trough,OBSERVATION_VERSION,MATCH_DIRECTORY
from refresh_mainboard_viewer import lock
from build_market_patterns import CURRENT,sha,dump

def main():
    with lock('REFRESH.lock'):
        before=CURRENT.read_bytes();bundle=json.loads(before)
        if bundle.get('observation_version')==OBSERVATION_VERSION:
            print('Already published high/low60 observations.');return
        for key,hash_key in [('events','events_sha256'),('universe','universe_sha256'),('manifest','manifest_sha256')]:
            assert sha(bundle[key])==bundle[hash_key],key
        manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
        lookup={(r['code'],r['mode']):r for r in manifest['files']}
        dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(bundle['calendar']).date))
        dates=dates[dates<=bundle['cutoff']]
        events=pd.read_parquet(bundle['events']);metrics=[]
        for n,(code,g) in enumerate(events.groupby('code'),1):
            fs={}
            for mode in ['raw','qfq']:
                record=lookup[(code,mode)];p=Path(record['path'])
                assert sha(p)==record['snapshot_sha256'],(code,mode)
                fs[mode]=pd.read_parquet(p).set_index('date').reindex(dates)
            raw=fs['raw'];q=fs['qfq'];v=raw.volume.to_numpy(float)
            valid=raw.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(v)&(v>0)
            for frame in [raw,q]:
                for col in ['open','high','low','close']:
                    a=frame[col].to_numpy(float);valid &= np.isfinite(a)&(a>0)
            for e in g.itertuples():
                t=dates.get_loc(pd.Timestamp(e.signal_date));reference=float(e.signal_close)
                assert np.isclose(reference,q.close.iloc[t],rtol=0,atol=1e-10)
                checked=peak(q.high.to_numpy(float),valid,dates,t,reference)
                for k,value in checked.items():
                    old=getattr(e,k)
                    if value is None:assert pd.isna(old),(e.event_id,k)
                    elif isinstance(value,float):assert np.isclose(value,old,rtol=0,atol=1e-12),(e.event_id,k)
                    else:assert value==old,(e.event_id,k)
                added=trough(q.low.to_numpy(float),valid,dates,t,reference)
                assert added['trough_complete60']==bool(e.peak_complete60)
                assert added['trough_status60']==e.peak_status60
                metrics.append(dict(event_id=e.event_id,**added))
            if n%250==0:print('Observed',n,'stocks',flush=True)
        indexed=pd.DataFrame(metrics).set_index('event_id')
        final=events.copy()
        for col in indexed.columns:final[col]=final.event_id.map(indexed[col])
        pd.testing.assert_frame_equal(final[events.columns],events)
        assert final.event_id.is_unique and len(final)==len(events)
        out=Path(bundle['events']).parent.parent/MATCH_DIRECTORY
        assert not out.exists(),'Preserve observation snapshots'
        out.mkdir()
        final.to_parquet(out/'events.parquet',index=False)
        spec=json.loads((Path(bundle['events']).parent/'SPEC.json').read_text(encoding='utf-8'))
        spec.update(observation_version=OBSERVATION_VERSION,
            observation='D+1..D+60 max adjusted high and min adjusted low relative signal close; max_drop=max(0,1-minlow/close); full valid window only.',
            signal_day_excluded=True,earliest_tied_low=True,source_events_sha256=bundle['events_sha256'])
        dump(out/'SPEC.json',spec)
        audit=dict(status='ok',signals=len(final),stocks=int(final.code.nunique()),
            complete60=int(final.trough_complete60.sum()),existing_columns_unchanged=True,
            peak_recomputed_unchanged=True,source_generation=bundle['generation'],
            source_events_sha256=bundle['events_sha256'],source_current_sha256=hashlib.sha256(before).hexdigest(),
            source_manifest_sha256=bundle['manifest_sha256'],observation_version=OBSERVATION_VERSION,
            no_rematching=True,no_protected_assets_modified=True)
        dump(out/'DOWNSIDE_AUDIT.json',audit)
        updated=dict(bundle,events=str((out/'events.parquet').resolve()),events_sha256=sha(out/'events.parquet'),
            observation_version=OBSERVATION_VERSION,downside_audit=str((out/'DOWNSIDE_AUDIT.json').resolve()))
        updated['generation']=bundle['cutoff']+'_'+updated['events_sha256'][:14]
        dump(out/'READY.json',updated)
        assert CURRENT.read_bytes()==before,'CURRENT changed during observation calculation'
        dump(CURRENT,updated)
        print(json.dumps(audit,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
