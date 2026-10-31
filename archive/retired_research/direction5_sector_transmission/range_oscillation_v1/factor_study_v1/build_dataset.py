"""Quarter-end as-of predictors and fixed-box morphology labels, pre-2024 only."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys
import json
import datetime
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from run_scan import sha, dump, longest_run, describe, traversals, structural_dates

ROOT = HERE.parent.parent
SPEC = json.loads((HERE/'spec.json').read_text(encoding='utf-8'))
FEATURES = [x['name'] for x in SPEC['features_order']]


def past_features(numbers, valid, end, desc):
    """Only slices ending at signal close; no forward labels reachable here."""
    r = np.full(len(valid),np.nan)
    r[valid] = np.log1p(numbers[valid,6]/100)
    def recent(a,n):
        x = a[max(0,end-n+1):end+1]
        return x[np.isfinite(x)] if np.isfinite(x).sum() >= .9*n else np.array([])
    a60 = recent(r,60)
    a252 = recent(r,252)
    box = np.log(desc['upper']/desc['lower'])
    sd60 = float(np.std(a60,ddof=1)) if len(a60)>1 else np.nan
    sd252 = float(np.std(a252,ddof=1)) if len(a252)>1 else np.nan
    seq = r[end-251:end+1]
    consecutive = np.isfinite(seq[1:]) & np.isfinite(seq[:-1])
    rho = float(np.corrcoef(seq[1:][consecutive],seq[:-1][consecutive])[0,1]) if consecutive.sum() >= 200 and sd252 > 0 else np.nan
    windows = np.lib.stride_tricks.sliding_window_view(seq,5)
    sums = windows[np.isfinite(windows).all(axis=1)].sum(axis=1)
    vr = float(np.var(sums,ddof=1)/(5*sd252**2)) if len(sums)>=200 and sd252>0 else np.nan
    amount = np.where(valid,numbers[:,5],np.nan)
    amounts = recent(amount,60)
    with np.errstate(divide='ignore',invalid='ignore'):
        intra = np.where(valid,(numbers[:,1]-numbers[:,2])/numbers[:,7],np.nan)
    intraday = recent(intra,60)
    median20 = np.nanmedian(amount[end-19:end+1])
    return dict(edge_distance=float(min(desc['box_position'],1-desc['box_position'])),
                vol60_box=sd60/box,vol_ratio60_252=sd60/sd252 if sd252>0 else np.nan,
                recent_trend60=float(abs(a60.sum())/box) if len(a60) else np.nan,
                autocorr1=rho,variance_ratio5=vr,
                efficiency60=float(abs(a60.sum())/np.abs(a60).sum()) if len(a60) and np.abs(a60).sum()>0 else np.nan,
                log_liquidity=float(np.log(median20)),
                amount_cv60=float(np.std(amounts,ddof=1)/amounts.mean()) if len(amounts)>1 else np.nan,
                intraday_range60_box=float(np.median(intraday)/box) if len(intraday) else np.nan)


def main():
    registration = json.loads((HERE/'registration.json').read_text(encoding='utf-8'))
    for source in registration['sources']:
        assert sha(source['path']) == source['sha256'],source['path']
    calendar_path = ROOT/'inputs_pre2025/trading_calendar_v1/calendar.parquet'
    calendar = pd.read_parquet(calendar_path)
    days = calendar.loc[calendar.is_trading_day.eq(1)&calendar.calendar_date.le(SPEC['data_cutoff']),'calendar_date'].to_numpy(dtype='datetime64[ns]')
    index = pd.DatetimeIndex(days)
    ends = pd.Series(np.arange(len(days)),index=index).loc['2020':].groupby(index[index.year>=2020].to_period('Q')).last().tolist()
    assert len(ends)==16 and min(ends)>=503
    manifest_path = ROOT/'inputs_pre2025/kline_v1/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    ledger_path = ROOT/'datasets/corporate_actions_reconciled_v3/dividend_event_ledger_provisional.parquet'
    ref_path = ROOT/'datasets/corporate_actions_reconciled_v3/reference_window_reconciliation.parquet'
    rights_path = ROOT/'datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet'
    structures = structural_dates(pd.read_parquet(ledger_path),pd.read_parquet(ref_path),pd.read_parquet(rights_path))
    def structural_count(symbol,start,end):
        d = structures.get(symbol,np.array([],dtype='datetime64[ns]'))
        return int(((d>=start)&(d<=end)).sum())

    def worker(item):
        path = manifest_path.parent/item['snapshot_file']
        assert sha(path)==item['snapshot_sha256'],path
        df = pd.read_parquet(path,filters=[('date','<=',pd.Timestamp(SPEC['data_cutoff']))])
        if df.empty:
            return [],dict(symbol=item['symbol'],rows_used=0,maximum_date=None,hash_verified=True)
        dates = pd.to_datetime(df.date).to_numpy()
        assert np.all(dates[1:]>dates[:-1])
        positions = np.searchsorted(days,dates)
        assert np.array_equal(days[positions],dates)
        values = df[['open','high','low','close','volume','amount','pctChg','preclose']].apply(pd.to_numeric,errors='coerce').to_numpy(float)
        active = df.tradestatus.astype(str).eq('1').to_numpy() & np.isfinite(values[:,:7]).all(axis=1) & (values[:,:6]>0).all(axis=1) & (values[:,6]>-100)
        nums = np.full((len(days),8),np.nan)
        nums[positions]=values
        valid = np.zeros(len(days),dtype=bool)
        valid[positions]=active
        st = np.ones(len(days),dtype=bool)
        st[positions]=df.isST.astype(str).ne('0')
        chain = np.cumsum(np.log1p(np.where(valid,nums[:,6]/100,0.)))
        symbol = item['symbol']
        rows=[]
        for end in ends:
            start=end-503
            v=valid[start:end+1]
            # Quality criteria use only trailing window and signal close.
            quality = bool(min(v.mean(),v[:252].mean(),v[252:].mean())>=.95 and longest_run(~v)<=5 and valid[end] and not st[end])
            if not quality:
                continue
            amount20 = nums[end-19:end+1,5][valid[end-19:end+1]]
            if not len(amount20) or np.median(amount20)<1e7 or structural_count(symbol,days[start],days[end]):
                continue
            desc=describe(nums[start:end+1,3],v,chain[start:end+1])
            if not desc:
                continue
            broad=bool(.1<=desc['box_width']<=.4 and desc['close_extreme_range']<=.6 and desc['lower']<=nums[end,3]<=desc['upper']
                       and desc['traversals']>=2 and min(desc['first_half_traversals'],desc['second_half_traversals'])>=1)
            if not broad:
                continue
            row=dict(symbol=symbol,asof=str(index[end].date()),year=int(index[end].year),quarter=str(index[end].to_period('Q')),
                     window_start=str(index[start].date()),strict_v1=bool(desc['shape_pass'] and desc['confirmation_pass']),
                     active_coverage=float(v.mean()),last20_median_amount=float(np.median(amount20)))
            row.update(desc)
            row.update(past_features(nums,valid,end,desc))
            row.update(label_status='immature',label_end=None,y=np.nan,y_persistence=np.nan,
                       future_quote_coverage=np.nan,future_inside_fraction=np.nan,future_traversals=np.nan,
                       future_max_outside_run=np.nan,future_structural_dates=np.nan)
            horizon=126
            if end+horizon<len(days):
                fv=valid[end+1:end+horizon+1]
                fc=nums[end+1:end+horizon+1,3]
                fchain=chain[end+1:end+horizon+1]
                inside=float(np.mean((fc[fv]>=desc['lower'])&(fc[fv]<=desc['upper']))) if fv.any() else np.nan
                breach=fv&((fc<.99*desc['lower'])|(fc>1.01*desc['upper']))
                events=structural_count(symbol,days[end+1],days[end+horizon])
                traversed=traversals(fc,fv,fchain,desc['lower'],desc['upper'])
                row.update(label_end=str(index[end+horizon].date()),future_quote_coverage=float(fv.mean()),
                           future_inside_fraction=inside,future_traversals=traversed,
                           future_max_outside_run=longest_run(breach),future_structural_dates=events)
                if events:
                    row['label_status']='unknown_structural_event'
                elif fv.mean()<.95:
                    row['label_status']='unknown_quote_coverage'
                else:
                    persists=bool(inside>=.8 and longest_run(breach)<10)
                    row.update(label_status='known',y_persistence=int(persists),y=int(persists and traversed>=2))
            rows.append(row)
        return rows,dict(symbol=symbol,rows_used=len(df),maximum_date=str(pd.Timestamp(dates.max()).date()),hash_verified=True)

    rows=[]
    audits=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,(part,audit) in enumerate(pool.map(worker,manifest['files']),1):
            rows.extend(part)
            audits.append(audit)
            if i%500==0:
                print(f'factor input verified {i}/{len(manifest["files"])}',flush=True)
    data=pd.DataFrame(rows).sort_values(['asof','symbol']).reset_index(drop=True)
    assert np.isfinite(data[FEATURES].replace([np.inf,-np.inf],np.nan).dropna().to_numpy()).all()
    data[FEATURES]=data[FEATURES].replace([np.inf,-np.inf],np.nan)
    out=HERE/'results'
    out.mkdir(exist_ok=True)
    data.to_parquet(out/'factor_dataset.parquet',index=False)
    pd.DataFrame(audits).to_parquet(out/'input_audit.parquet',index=False)
    sources=[calendar_path,manifest_path,ledger_path,ref_path,rights_path]
    audit=dict(spec_sha256=sha(HERE/'spec.json'),code_sha256=sha(__file__),completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               dates=[str(index[e].date()) for e in ends],files_verified=len(audits),rows_loaded=sum(a['rows_used'] for a in audits),
               maximum_price_date=max(a['maximum_date'] for a in audits if a['maximum_date']),post_2023_price_rows_loaded=0,
               candidate_observations=len(data),unique_stocks=data.symbol.nunique(),
               label_counts={str(k):int(v) for k,v in data.label_status.value_counts().items()},
               inputs=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in sources],
               original_protocol_sha256=sha(ROOT/'research_protocol_v1.json'),
               original_gates_sha256=sha(ROOT/'research_stage_gates_v2.json'))
    dump(out/'dataset_audit.json',audit)
    print(data.groupby('asof').agg(n=('symbol','size'),strict=('strict_v1','sum'),known=('y','count'),positives=('y','sum'),persistence=('y_persistence','sum')).to_string(),flush=True)
    print(json.dumps(audit['label_counts'],ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
