"""Registered event study, not account P&L or certified executable fills."""
from pathlib import Path
import json, hashlib, datetime
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
OUT=BASE/'holdout_restricted/patterns_v1'
INPUT=OUT/'inputs_daily'
RESULT=OUT/'event_results_v1r2'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def dump(p,x):
    Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def first_mask(o,c,valid):
    neg=pd.Series(valid & (c<o));pos=pd.Series(valid & (c>o))
    mask=pos.copy()
    for shift in [1,2]:mask &= pos.shift(shift,fill_value=False)
    for shift in range(3,8):mask &= neg.shift(shift,fill_value=False)
    return mask.to_numpy()

def falling_overall(x):
    return bool(np.isfinite(x).all() and (x>0).all() and x[-1]<x[0] and
                np.dot(np.arange(len(x))-(len(x)-1)/2,x)<0)

def third_mask(o,c,v,valid,body_o=None,body_c=None):
    n=len(c); result=np.zeros(n,dtype=int)
    ma20=pd.Series(c).rolling(20,min_periods=20).mean().to_numpy()
    ma60=pd.Series(c).rolling(60,min_periods=60).mean().to_numpy()
    v20=pd.Series(np.where(valid,v,np.nan)).shift(1).rolling(20,min_periods=20).mean().to_numpy()
    prev=np.r_[np.nan,c[:-1]]
    neg=valid & (c<o) & (c<prev)
    release=valid & (c>o) & (c>prev) & (v>=1.5*v20)
    for t in np.flatnonzero(release):
        for length in [5,4,3]:
            start=t-length;pre=start-1
            if pre<59 or not neg[start:t].all():continue
            if not (c[pre]>ma20[pre]>ma60[pre]):continue
            bo=o if body_o is None else body_o
            bc=c if body_c is None else body_c
            body=(bo[start:t]-bc[start:t])/bo[start:t]
            if falling_overall(body) and falling_overall(v[start:t]):
                result[t]=length;break
    return result

def checks():
    o=np.full(12,10.);c=np.array([9.]*5+[11.]*3+[10.]*4)
    valid=np.ones(12,dtype=bool)
    assert np.flatnonzero(first_mask(o,c,valid)).tolist()==[7]
    for loc in [1,5]:
        broken=valid.copy();broken[loc]=False
        assert not first_mask(o,c,broken).any()
    doji=c.copy();doji[3]=o[3];assert not first_mask(o,doji,valid).any()
    # Build a real uptrend then a 3-session contracting pullback + volume release.
    c=np.r_[np.linspace(8,16,75),15.7,15.5,15.4,15.8,16.,16.2,16.3,16.4,16.5,16.6]
    o=c-.03;o[75:78]=[16.,15.7,15.5];o[78]=15.35
    v=np.full(len(c),100.);v[75:79]=[90,70,50,200]
    valid=np.ones(len(c),bool)
    mask=third_mask(o,c,v,valid)
    assert mask[78]==3 and (mask>0).sum()==1
    v_bad=v.copy();v_bad[78]=110;assert third_mask(o,c,v_bad,valid)[78]==0
    valid_bad=valid.copy();valid_bad[76]=False
    assert third_mask(o,c,v,valid_bad)[78]==0
    # Appending/mutating future observations must leave old signal masks intact.
    future=c.copy();future[79:]=1
    assert np.array_equal(third_mask(o,c,v,valid)[:79],third_mask(o,future,v,valid)[:79])
    assert falling_overall(np.array([4.,2.,3.,1.]))
    assert not falling_overall(np.array([1.,2.,3.]))
    # Future cash-dividend adjustment can translate old prices. Same raw body
    # input must keep the old signal invariant under a positive affine transform.
    assert np.array_equal(third_mask(o,c,v,valid,body_o=o,body_c=c),
                          third_mask(o*.8-1,c*.8-1,v,valid,body_o=o,body_c=c))
    return dict(exact_candles=True,doji_and_missing_break=True,
                trend_and_body_volume=True,release_volume_previous20_only=True,
                signal_not_using_future=True,D0_plus5_exit=True,
                returns_are_price_changes_not_account_returns=True)

def stats(g):
    a=g.dropna().astype(float)
    if not len(a):return dict(n=0,mean=None,median=None,win_rate=None,p10=None,p90=None,min=None,max=None)
    return dict(n=len(a),mean=float(a.mean()),median=float(a.median()),
        win_rate=float(a.gt(0).mean()),p10=float(a.quantile(.1)),p90=float(a.quantile(.9)),
        min=float(a.min()),max=float(a.max()))

def finite(x):return float(x) if np.isfinite(x) else None

def main():
    assert not RESULT.exists(),'Preserve first registered outcome; use explicit new version for repairs'
    tests=checks()
    rule_path=OUT/'SHAPE_RULES_v1.json';rules=json.loads(rule_path.read_text(encoding='utf-8'))
    rules['output_basis']='User confirmed: per-signal returns, win rate and price path; no account aggregation.'
    rules['status']='confirmed_shapes_and_event_output;second_waiting_for_minute_inputs'
    rules['third']['numeric_default_origin']='3-5 pullback candles and1.5volume multiplier are operational defaults announced before outcomes, not numbers supplied verbatim by user.'
    rules['third']['body_price_basis']='Contemporaneous raw OHLC for (O-C)/O; adjusted close for cross-session trend/comparison. Avoid future cash-dividend affine translation changing historical body ratios.'
    rules['correctness_repair']='r2:raw body ratio after identifying additive adjustment; retain earlier result version. No parameter search or threshold changes.'
    dump(rule_path,rules)
    RESULT.mkdir()
    dump(RESULT/'MINIMUM_CHECKS.json',tests)
    manifest=json.loads((INPUT/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['snapshots']==370 and len(manifest['files'])==370
    for record in manifest['files']:
        p=INPUT/record['mode']/f"{record['code']}.parquet"
        assert sha(p)==record['snapshot_sha256']
    cal_src=ROOT/'sh_sz_market_research/data_pipeline/data/metadata/trade_calendar_20261026.csv'
    calendar=pd.read_csv(cal_src)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>='2018-01-01')&(dates<='2026-10-26')]
    pd.DataFrame({'date':dates}).to_csv(RESULT/'exchange_sessions.csv',index=False)
    pool=pd.read_parquet(OUT/'frozen_pool_185.parquet')
    events=[];paths=[];quality=[];sequence=0
    for stock in pool.itertuples():
        code=stock.code
        raw=pd.read_parquet(INPUT/'raw'/f'{code}.parquet').set_index('date').reindex(dates)
        adj=pd.read_parquet(INPUT/'qfq'/f'{code}.parquet').set_index('date').reindex(dates)
        assert raw.index.equals(adj.index)
        r={k:pd.to_numeric(raw[k],errors='coerce').to_numpy(float) for k in ['open','high','low','close','volume']}
        a={k:pd.to_numeric(adj[k],errors='coerce').to_numpy(float) for k in ['open','high','low','close']}
        valid=np.logical_and.reduce([np.isfinite(r[k]) & (r[k]>0) for k in r])
        valid &= raw.tradestatus.astype(str).eq('1').to_numpy()
        valid &= np.logical_and.reduce([np.isfinite(a[k]) & (a[k]>0) for k in a])
        # Some vendors adjust cash dividends additively. The within-day transform
        # may therefore be affine rather than strictly proportional.
        factors=np.vstack([a[k]/r[k] for k in ['open','high','low','close']])
        delta=np.nanmax(factors,axis=0)/np.nanmin(factors,axis=0)-1
        span=r['high']-r['low']
        slope=np.divide(a['high']-a['low'],span,out=np.ones(len(dates)),where=span>0)
        intercept=a['low']-slope*r['low']
        residual=np.nanmax(np.vstack([np.abs(a[k]-(slope*r[k]+intercept)) for k in a]),axis=0)
        tolerance=np.maximum(.003,np.abs(a['close'])*.0005)
        bad_geometry=valid & ((residual>tolerance) | (slope<=0) | ((r['close']>r['open'])!=(a['close']>a['open'])))
        assert not bad_geometry.any(),(code,'adjusted affine candle geometry mismatch',int(bad_geometry.sum()))
        # This is only a discrepancy flag, not a verified corporate-action table.
        raw_return=r['close'][1:]/r['close'][:-1]-1
        adj_return=a['close'][1:]/a['close'][:-1]-1
        changes=np.r_[False,np.abs(raw_return-adj_return)>.005]
        # Prevent missing/suspended sessions from being silently skipped in indicators.
        c=np.where(valid,a['close'],np.nan);o=np.where(valid,a['open'],np.nan)
        pattern1=first_mask(r['open'],r['close'],valid)
        pattern3=third_mask(o,c,r['volume'],valid,body_o=r['open'],body_c=r['close'])
        quality.append(dict(code=code,valid_sessions=int(valid.sum()),missing_or_inactive=int((~valid).sum()),
                            max_daily_geometry_relative_difference=finite(np.nanmax(delta)),
                            raw_adjusted_return_discrepancy_days=int(changes.sum()),
                            max_affine_residual=finite(np.nanmax(residual))))
        last_kept=-10000
        for rule,mask,horizon in [('first',pattern1,40),('third',pattern3>0,5)]:
            for t in np.flatnonzero(mask & (dates>='2019-01-01')):
                sequence+=1;event_id=f'{rule}_{code}_{dates[t]:%Y%m%d}'
                entry=t if rule=='first' else t+1
                end=entry+horizon
                entry_known=entry<len(dates) and valid[entry]
                price=(a['close'][entry] if rule=='first' else a['open'][entry]) if entry_known else np.nan
                raw_price=(r['close'][entry] if rule=='first' else r['open'][entry]) if entry_known else np.nan
                not_mature=end>=len(dates)
                exit_valid=end<len(dates) and valid[end]
                ret=a['close'][end]/price-1 if entry_known and exit_valid else np.nan
                rawret=r['close'][end]/raw_price-1 if entry_known and exit_valid else np.nan
                nonoverlap=True
                if rule=='first':
                    nonoverlap=t>last_kept
                    if nonoverlap:last_kept=t+40
                stop=min(end,len(dates)-1)
                complete=entry_known and end<len(dates) and valid[entry:end+1].all()
                entry_one=entry_known and abs(r['high'][entry]-r['low'][entry])<.000001
                exit_one=exit_valid and abs(r['high'][end]-r['low'][end])<.000001
                n_changes=int(changes[entry+1:stop+1].sum()) if entry<len(dates) else 0
                row=dict(event_id=event_id,rule=rule,code=code,name=stock.name,year=int(dates[t].year),
                    signal_date=dates[t].strftime('%Y-%m-%d'),
                    entry_date=dates[entry].strftime('%Y-%m-%d') if entry<len(dates) else None,
                    expected_exit_date=dates[end].strftime('%Y-%m-%d') if end<len(dates) else None,
                    adjusted_reference_price=finite(price),raw_reference_price=finite(raw_price),
                    adjusted_price_change=finite(ret),raw_per_share_price_change_diagnostic_only=finite(rawret),
                    future_censored=not_mature,entry_quote_available=bool(entry_known),exit_quote_available=bool(exit_valid),
                    complete_path=bool(complete),nonoverlap40=bool(nonoverlap),
                    entry_one_price_day=bool(entry_one),exit_one_price_day=bool(exit_one),
                    raw_adjusted_return_discrepancy_days_in_path=n_changes,
                    pullback_length=int(pattern3[t]) if rule=='third' else None,
                    observation_only=(rule=='first'),execution_certified=False)
                if entry_known:
                    highs=a['high'][entry:stop+1].copy();lows=a['low'][entry:stop+1].copy()
                    if rule=='first':highs=highs[1:];lows=lows[1:]
                    row['max_high_change']=finite(np.nanmax(highs)/price-1) if len(highs) and np.isfinite(highs).any() else None
                    row['min_low_change']=finite(np.nanmin(lows)/price-1) if len(lows) and np.isfinite(lows).any() else None
                    for d in range(horizon+1):
                        q=entry+d
                        if q>=len(dates):break
                        paths.append(dict(event_id=event_id,rule=rule,code=code,name=stock.name,
                            signal_date=row['signal_date'],day=d,date=dates[q].strftime('%Y-%m-%d'),
                            adjusted_price_reference=price,
                            adjusted_close=finite(a['close'][q]) if valid[q] else None,
                            raw_close=finite(r['close'][q]) if valid[q] else None,
                            close_change=finite(a['close'][q]/price-1) if valid[q] else None,
                            high_change=finite(a['high'][q]/price-1) if valid[q] else None,
                            low_change=finite(a['low'][q]/price-1) if valid[q] else None,
                            valid_quote=bool(valid[q]),nonoverlap40=bool(nonoverlap)))
                else:row['max_high_change']=None;row['min_low_change']=None
                events.append(row)
    e=pd.DataFrame(events);p=pd.DataFrame(paths)
    for name,df in [('events',e),('daily_paths',p),('data_quality',pd.DataFrame(quality))]:
        df.to_parquet(RESULT/f'{name}.parquet',index=False)
        df.to_csv(RESULT/f'{name}.csv',index=False,encoding='utf-8-sig')
    # A path point denominator is explicit; balanced means use horizon-complete paths only.
    full_ids=set(e.loc[e.complete_path,'event_id'])
    pathstats=[]
    for (rule,day),g in p.groupby(['rule','day']):
        for cohort,sub in [('available_at_day',g),('complete_path_only',g[g.event_id.isin(full_ids)])]:
            pathstats.append(dict(rule=rule,day=int(day),cohort=cohort,**stats(sub.close_change)))
    ps=pd.DataFrame(pathstats);ps.to_csv(RESULT/'path_summary.csv',index=False,encoding='utf-8-sig')
    ps.to_parquet(RESULT/'path_summary.parquet',index=False)
    yearrows=[];summaries={}
    for rule,g in e.groupby('rule'):
        horizon=40 if rule=='first' else 5
        summaries[rule]=dict(signals=len(g),stocks=int(g.code.nunique()),censored=int(g.future_censored.sum()),
            missing_entry_quote=int((~g.entry_quote_available).sum()),
            mature_missing_exit=int((~g.future_censored & ~g.exit_quote_available).sum()),
            complete_paths=int(g.complete_path.sum()),price_change=stats(g.adjusted_price_change),
            complete_path_price_change=stats(g.loc[g.complete_path,'adjusted_price_change']),
            one_price_entry_days=int(g.entry_one_price_day.sum()),one_price_exit_days=int(g.exit_one_price_day.sum()),
            events_with_raw_adjusted_discrepancy=int(g.raw_adjusted_return_discrepancy_days_in_path.gt(0).sum()))
        if rule=='first':summaries[rule]['nonoverlap40']=stats(g.loc[g.nonoverlap40,'adjusted_price_change'])
        for year,sub in g.groupby('year'):
            yearrows.append(dict(rule=rule,year=int(year),signals=len(sub),censored=int(sub.future_censored.sum()),
                                 **stats(sub.adjusted_price_change)))
    yearly=pd.DataFrame(yearrows);yearly.to_csv(RESULT/'yearly_summary.csv',index=False,encoding='utf-8-sig')
    yearly.to_parquet(RESULT/'yearly_summary.parquet',index=False)
    # First rule 1/5/10/20/40-session endpoints; all events retained in source tables.
    horizonrows=[]
    for day in [1,5,10,20,40]:
        sub=p[(p.rule=='first')&(p.day==day)]
        horizonrows.append(dict(day=day,**stats(sub.close_change)))
    pd.DataFrame(horizonrows).to_csv(RESULT/'first_horizons.csv',index=False,encoding='utf-8-sig')
    dump(RESULT/'SUMMARY.json',dict(start='2019-01-01',cutoff='2026-10-26',pool=185,
        price_basis='vendor forward-adjusted price change; not reconciled shareholder economic P&L; no fees or account compounding',
        first_reference='third positive close for observation; not an executable same-close order',
        third_reference='following-session open to D+5 close; ideal quote return with execution flags, not certified fills',
        pool_bias='Current stock pool selected using2025-2026relations; retrospective study, not a blind test.',
        calendar_source=str(cal_src),calendar_sha256=sha(cal_src),rules_sha256=sha(rule_path),
        summaries=summaries,second=dict(status='pending_minute_data',results_computed=False),
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    # Calendar offset and no invalid quote silently used in endpoint outputs.
    assert not e.loc[~e.entry_quote_available,'adjusted_price_change'].notna().any()
    assert not e.loc[~e.exit_quote_available,'adjusted_price_change'].notna().any()
    dmap={d.strftime('%Y-%m-%d'):i for i,d in enumerate(dates)}
    for row in e.loc[(e.rule=='third')&e.expected_exit_date.notna()].itertuples():
        assert dmap[row.entry_date]-dmap[row.signal_date]==1
        assert dmap[row.expected_exit_date]-dmap[row.entry_date]==5
    tests.update(input_hashes_verified=370,calendar_offsets_verified=True,
                 unavailable_endpoints_not_filled=True,pool_hash=sha(OUT/'frozen_pool_185.parquet'))
    dump(RESULT/'MINIMUM_CHECKS.json',tests)
    print(json.dumps(summaries,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
