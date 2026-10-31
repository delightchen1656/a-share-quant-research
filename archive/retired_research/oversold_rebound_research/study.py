"""Direction 2 morphology pilot. Pre-2025 whitelist only, no fitting or holdout reads."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'box60_selection_research' / 'inputs_pre2025'
OUT = ROOT / 'results_v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan(q, r):
    """All feature windows are trailing. Returned candidates have no future fields."""
    valid = (pd.to_numeric(r.tradestatus) == 1) & (r.volume > 0) & (r.open > 0)
    q = q.loc[valid].reset_index(drop=True)
    r = r.loc[valid].reset_index(drop=True)
    c, h, l = q.close, q.high, q.low
    span = (r.high-r.low).replace(0, np.nan)
    f = pd.DataFrame({'date': q.date})
    f['ret20'] = c.shift(1)/c.shift(21)-1
    f['ret5'] = c.shift(1)/c.shift(6)-1
    f['below_ma20'] = c/c.rolling(20).mean()-1
    f['below_ma60'] = c/c.rolling(60).mean()-1
    f['low_recent'] = l.rolling(3).min()/l.rolling(20).min()-1
    f['rebound_from_low'] = c/l.rolling(3).min()-1
    f['body'] = (r.close-r.open)/span
    f['upper'] = (r.high-r.close)/span
    f['lower'] = (r.open.where(r.open < r.close, r.close)-r.low)/span
    f['volume_ratio'] = r.volume/r.volume.shift(1).rolling(20).mean()
    f['last3_volume_ratio'] = r.volume.shift(1).rolling(3).mean()/r.volume.shift(4).rolling(10).mean()
    f['close_over_prev_high'] = c/h.shift(1)-1
    # Simple prespecified visual prototype, not thresholds chosen by future outcome.
    base = ((f.ret20 <= -.15) & (f.ret5 <= -.08) &
            (f.below_ma20 < 0) & (f.below_ma60 < 0) &
            (f.low_recent <= .02) & (f.rebound_from_low <= .12) &
            (r.close > r.open) & (f.body >= .40) & (f.upper <= .30))
    f['candidate'] = base.fillna(False)
    f['q_position'] = np.arange(len(q))
    return f, q, r


def independent(mask):
    """First qualifying signal in each 10-observed-session cooldown, before labels."""
    keep = []
    last = -100
    for i in np.flatnonzero(np.asarray(mask)):
        if i-last >= 10:
            keep.append(i)
            last = i
    return keep


def summarize(frame):
    d = frame.loc[frame.complete60].copy()
    if not len(d):
        return {'signals':len(frame), 'complete60':0}
    return dict(signals=len(frame), complete60=len(d), stocks=d.code.nunique(),
                touch5=float((d.max_up60 >= .05).mean()),
                touch10=float((d.max_up60 >= .10).mean()),
                fall30=float((d.max_down60 <= -.30).mean()),
                mean_max_up60=float(d.max_up60.mean()),
                median_max_up60=float(d.max_up60.median()),
                mean_max_down60=float(d.max_down60.mean()),
                mean_close20=float(d.close20.mean()),
                mean_close60=float(d.close60.mean()),
                positive_close60=float((d.close60 > 0).mean()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    assert m['boundary'] == '2024-12-31'
    assert digest(SOURCE/'calendar.parquet') == m['calendar_sha256']
    calendar = pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date)
    dates = list(calendar.dt.strftime('%Y-%m-%d'))
    positions = {d:i for i,d in enumerate(dates)}
    hashes = {x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    meta = pd.read_parquet(SOURCE/'events.parquet')
    assert digest(SOURCE/'events.parquet') == m['events_sha256']
    meta = meta.groupby('code').agg(name=('name','first'), is_leader=('is_leader','max'))
    rows = []
    for n, code in enumerate(meta.index):
        code = str(code).zfill(6)
        frames = []
        for mode in ['qfq','raw']:
            p = SOURCE/mode/(code+'.parquet')
            assert digest(p) == hashes[f'{mode}/{code}.parquet'], str(p)
            d = pd.read_parquet(p).sort_values('date').reset_index(drop=True)
            d['date'] = pd.to_datetime(d.date).dt.strftime('%Y-%m-%d')
            assert d.date.max() <= '2024-12-31'
            frames.append(d)
        q,r = frames
        assert list(q.date) == list(r.date)
        f, q, r = scan(q,r)
        indexed = q.set_index('date')
        for t in independent(f.candidate):
            item = f.iloc[t].to_dict()
            day = item['date']; k = positions[day]
            item.update(code=code,name=meta.loc[code,'name'],is_leader=bool(meta.loc[code,'is_leader']),year=int(day[:4]))
            # Entry is the next official session; do not skip a suspended entry day.
            entry_day = dates[k+1] if k+1 < len(dates) else None
            item['entry_date'] = entry_day
            item['entry_valid'] = entry_day in indexed.index
            item['complete60'] = bool(item['entry_valid'] and k+60 < len(dates))
            if item['entry_valid']:
                entry = float(indexed.loc[entry_day,'open'])
                future = indexed.loc[indexed.index.isin(dates[k+1:k+61])]
                item['observed60'] = len(future)
                item['max_up60'] = max(0.,float(future.high.max()/entry-1))
                item['max_down60'] = min(0.,float(future.low.min()/entry-1))
                for horizon in [20,60]:
                    end = dates[k+horizon] if k+horizon < len(dates) else None
                    item[f'close{horizon}'] = float(indexed.loc[end,'close']/entry-1) if end in indexed.index else np.nan
                item['complete60'] = bool(item['complete60'] and np.isfinite(item['close60']))
            rows.append(item)
        if (n+1)%200 == 0: print('scanned',n+1,flush=True)
    d = pd.DataFrame(rows)
    d.to_parquet(OUT/'events.parquet',index=False)
    variants = {
        'baseline':pd.Series(True,index=d.index),
        'signal_volume_ge_1_2':d.volume_ratio >= 1.2,
        'signal_volume_ge_1_5':d.volume_ratio >= 1.5,
        'prior3_volume_shrink':d.last3_volume_ratio <= .8,
        'strong_body_ge_0_6':d.body >= .6,
        'close_above_prev_high':d.close_over_prev_high >= 0,
        'long_lower_shadow':d.lower >= .2,
        'deep_below_ma20':d.below_ma20 <= -.10,
    }
    reports = []
    yearly = []
    for pool, poolmask in [('sample_mainboard',pd.Series(True,index=d.index)),('leaders',d.is_leader)]:
        for label,mask in variants.items():
            sub = d.loc[mask & poolmask]
            reports.append(dict(pool=pool,rule=label,**summarize(sub)))
            for year,g in sub.groupby('year'):
                yearly.append(dict(pool=pool,rule=label,year=int(year),**summarize(g)))
    result = dict(boundary='2024-12-31',source_manifest_sha256=digest(SOURCE/'MANIFEST.json'),
                  scope_stocks=len(meta),rules=reports,yearly=yearly,
                  caveats=['Current-universe retrospective cohort: only 947 stocks from earlier box study; not all mainboard.',
                           'Exploratory comparisons, not untouched blind validation; screenshots contain later examples.',
                           'Adjusted price paths, not executable account returns; no fees, limits, dividends or share accounting.',
                           'Signals use trailing valid bars; labels use next official session to D60; missing entry excluded.',
                           '10-session cooldown uses baseline first occurrence; variants filter those fixed events.'])
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(reports,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()
