"""Describe full daily gaps inside already frozen 15-session bases, without selection changes."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
CURRENT=HERE/'market_wide/holdout_restricted/CURRENT.json'
GAP_VERSION='base_internal_full_gap_v1'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def report_dir(bundle):return HERE/'box_gaps/holdout_restricted'/bundle['generation']

def read_or_scan(bundle):
    out=report_dir(bundle);audit_file=out/'CACHE_AUDIT.json'
    if not audit_file.exists():return scan(bundle)
    audit=json.loads(audit_file.read_text(encoding='utf-8'))
    assert audit['version']==GAP_VERSION and audit['source_events_sha256']==bundle['events_sha256']
    assert audit['source_manifest_sha256']==bundle['manifest_sha256']
    assert sha(out/'events.json')==audit['events_json_sha256'],'Box gap observation cache failed verification'
    return json.loads((out/'events.json').read_text(encoding='utf-8'))

def seal_cache(out,bundle):
    audit=dict(version=GAP_VERSION,source_events_sha256=bundle['events_sha256'],
        source_manifest_sha256=bundle['manifest_sha256'],events_json_sha256=sha(out/'events.json'))
    (out/'CACHE_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')

def direction(high,low,previous_high,previous_low):
    # Suppress floating-point noise, not economically small gaps.
    if low>previous_high+1e-8:return 'up'
    if high<previous_low-1e-8:return 'down'
    return None

def describe(high,low,raw_high,raw_low,valid,dates,t):
    def gap_at(i,zone):
        if not (valid[i-1] and valid[i]):return None
        adjusted=direction(high[i],low[i],high[i-1],low[i-1])
        raw=direction(raw_high[i],raw_low[i],raw_high[i-1],raw_low[i-1])
        if not adjusted and not raw:return None
        item=dict(date=dates[i].strftime('%Y-%m-%d'),previous_date=dates[i-1].strftime('%Y-%m-%d'),zone=zone,
            direction=adjusted,raw_direction=raw,raw_confirmed=bool(adjusted and adjusted==raw))
        if not adjusted:
            item.update(raw_only=True,gap_pct=None);return item
        is_up=adjusted=='up'
        lower=float(high[i-1] if is_up else high[i]);upper=float(low[i] if is_up else low[i-1])
        base_end=t-1
        filled=None
        for j in range(i+1,t+1):
            if valid[j] and (low[j]<=lower+1e-8 if is_up else high[j]>=upper-1e-8):
                filled=j;break
        item.update(raw_only=False,gap_low=lower,gap_high=upper,gap_pct=upper/lower-1,
            filled_in_base=bool(filled is not None and filled<=base_end),
            filled_by_signal=filled is not None,fill_date=dates[filled].strftime('%Y-%m-%d') if filled is not None else None,
            fill_after_sessions=int(filled-i) if filled is not None else None)
        return item
    # Both bars belong to the base: D-14..D-1 against their previous base bars.
    internal=[item for i in range(t-14,t) if (item:=gap_at(i,'base_internal'))]
    confirmed=[g for g in internal if g['raw_confirmed']]
    adjusted=[g for g in internal if g['direction']]
    entry=gap_at(t-15,'base_entry');signal=gap_at(t,'signal')
    return dict(gap_version=GAP_VERSION,gap_count=len(confirmed),gap_up_count=sum(g['direction']=='up' for g in confirmed),
        gap_down_count=sum(g['direction']=='down' for g in confirmed),
        gap_unfilled_count=sum(not g['filled_by_signal'] for g in confirmed),
        gap_max_pct=max((g['gap_pct'] for g in confirmed),default=None),
        gap_details=confirmed,gap_adjusted_count=len(adjusted),
        gap_review_details=[g for g in internal if not g['raw_confirmed']],
        gap_entry=entry,gap_signal=signal)

def scan(bundle,progress=False):
    for key,hkey in [('manifest','manifest_sha256'),('events','events_sha256')]:assert sha(bundle[key])==bundle[hkey],key
    manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
    lookup={(r['code'],r['mode']):r for r in manifest['files']}
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(bundle['calendar']).date));dates=dates[dates<=bundle['cutoff']]
    events=pd.read_parquet(bundle['events']);rows=[]
    for n,(code,g) in enumerate(events.groupby('code'),1):
        frames={}
        for mode in ['raw','qfq']:
            r=lookup[(code,mode)];assert sha(r['path'])==r['snapshot_sha256']
            frames[mode]=pd.read_parquet(r['path']).set_index('date').reindex(dates)
        raw=frames['raw'];q=frames['qfq'];volume=raw.volume.to_numpy(float)
        valid=raw.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(volume)&(volume>0)
        for f in [raw,q]:
            for col in ['open','high','low','close']:
                a=f[col].to_numpy(float);valid &= np.isfinite(a)&(a>0)
        for e in g.itertuples():
            t=dates.get_loc(pd.Timestamp(e.signal_date));assert dates[t-15].strftime('%Y-%m-%d')==e.base_start
            features=describe(q.high.to_numpy(float),q.low.to_numpy(float),raw.high.to_numpy(float),raw.low.to_numpy(float),valid,dates,t)
            rows.append(dict(event_id=e.event_id,code=code,name=e.name,is_leader=bool(e.is_leader),
                leader_source=e.leader_source,signal_date=e.signal_date,base_start=e.base_start,base_end=e.base_end,**features))
        if progress and n%250==0:print('Scanned',n,'stocks',flush=True)
    assert len(rows)==len(events)
    return sorted(rows,key=lambda r:(r['signal_date'],r['code']),reverse=True)

def main():
    before=CURRENT.read_bytes();bundle=json.loads(before)
    out=report_dir(bundle)
    if out.exists():
        assert json.loads((out/'SPEC.json').read_text(encoding='utf-8'))['source_events_sha256']==bundle['events_sha256']
        if not (out/'CACHE_AUDIT.json').exists():
            assert scan(bundle)==json.loads((out/'events.json').read_text(encoding='utf-8'))
            seal_cache(out,bundle)
        else:read_or_scan(bundle)
        print((out/'SUMMARY.json').read_text(encoding='utf-8'));return
    out.mkdir(parents=True)
    spec=dict(version=GAP_VERSION,cutoff=bundle['cutoff'],source_generation=bundle['generation'],
        source_events_sha256=bundle['events_sha256'],source_manifest_sha256=bundle['manifest_sha256'],
        base='D-15..D-1; adjacent pairs both inside the base (14 pairs).',
        up='adjusted low[t]>adjusted high[t-1] AND raw low[t]>raw high[t-1]',
        down='adjusted high[t]<adjusted low[t-1] AND raw high[t]<raw low[t-1]',
        tolerance=1e-8,minimum_gap_pct=None,
        fill='Up: subsequent low touches previous high; down: subsequent high touches previous low. Checked through signal only.',
        raw_adjusted_disagreement='Kept separately for review, not labelled as confirmed gaps.',
        separate_base_entry_and_signal=True,no_future_outcome_selection=True,no_signal_rules_changed=True)
    (out/'SPEC.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=scan(bundle,progress=True);selected=[r for r in rows if r['gap_count']]
    all_gaps=[dict(event_id=r['event_id'],code=r['code'],name=r['name'],is_leader=r['is_leader'],signal_date=r['signal_date'],**g) for r in selected for g in r['gap_details']]
    summary=dict(cutoff=bundle['cutoff'],signals=len(rows),confirmed_signals=len(selected),confirmed_stocks=len({r['code'] for r in selected}),
        leader_signals=sum(r['is_leader'] for r in selected),leader_stocks=len({r['code'] for r in selected if r['is_leader']}),
        gap_occurrences=len(all_gaps),unique_stock_gap_dates=len({(g['code'],g['date']) for g in all_gaps}),
        up_only_signals=sum(r['gap_up_count']>0 and r['gap_down_count']==0 for r in selected),
        down_only_signals=sum(r['gap_down_count']>0 and r['gap_up_count']==0 for r in selected),
        both_signals=sum(r['gap_up_count']>0 and r['gap_down_count']>0 for r in selected),
        signals_with_unfilled_gap=sum(r['gap_unfilled_count']>0 for r in selected),
        adjusted_only_review_signals=sum(any(g['direction'] for g in r['gap_review_details']) for r in rows),
        raw_only_review_signals=sum(any(g.get('raw_only') for g in r['gap_review_details']) for r in rows),
        gap_size_signal_counts={str(threshold):sum(any(g['gap_pct']>=threshold for g in r['gap_details']) for r in selected) for threshold in [0,.005,.01,.02]},
        verified_source_unchanged=CURRENT.read_bytes()==before)
    assert summary['verified_source_unchanged']
    for name,data in [('events.json',rows),('selected.json',selected),('gap_details.json',all_gaps),('SUMMARY.json',summary)]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    text=['箱体内部跳空样本（同箱首信号；仅观察形态，不按未来涨跌筛选）',f"行情截至 {bundle['cutoff']}",
        '确认口径：前复权与原始行情均为相邻日完整价格区间不重叠。箱体内部仅D-14至D-1；箱体起始、信号日另列。',
        f"共{len(selected)}个箱体信号，{summary['confirmed_stocks']}只股票。",'']
    for r in selected:
        marks=('★' if r['is_leader'] else '')
        text.append(f"{marks}{r['name']} {r['code']}  信号 {r['signal_date']}  横盘 {r['base_start']}～{r['base_end']}  上跳{r['gap_up_count']} 下跳{r['gap_down_count']}")
        for g in r['gap_details']:
            fill='截至信号未回补' if not g['filled_by_signal'] else ('横盘内回补' if g['filled_in_base'] else '信号日回补')+' '+g['fill_date']
            text.append(f"  {g['date']} {'向上' if g['direction']=='up' else '向下'}缺口 {g['gap_pct']:.2%}  {fill}")
    (out/'箱体跳空样本.txt').write_text('\n'.join(text),encoding='utf-8')
    seal_cache(out,bundle)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
