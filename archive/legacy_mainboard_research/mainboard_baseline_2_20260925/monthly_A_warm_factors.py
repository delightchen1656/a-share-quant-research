"""Recompute daily causal factors with supplemental pre-2018 history."""
import json
import numpy as np
import pandas as pd
import group_research as g
OUT=g.HERE/'monthly_A_alignment_20260924'
WARM=OUT/'warmup'
SPLICES=[]

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def merged(symbol,kind):
    path=g.bt.raw_path(symbol) if kind=='raw' else g.bt.qfq_path(symbol)
    old=pd.read_parquet(path);old['date']=pd.to_datetime(old.date)
    warm=WARM/kind/(symbol+'.parquet')
    if not warm.exists():return old
    extra=pd.read_parquet(warm)
    if extra.empty:return old
    extra['date']=pd.to_datetime(extra.date)
    assert extra.date.is_unique,('Duplicate warmup dates',symbol,kind)
    assert set(extra.code)=={symbol[-2:].lower()+'.'+symbol[:6]},('Wrong source symbol',symbol,kind)
    assert extra.date.between('2015-01-01','2018-01-10').all()
    both=extra.merge(old[['date','close']],on='date',suffixes=('_warm','_old'))
    if kind=='qfq':
        valid=both[(both.close_warm>0)&(both.close_old>0)]
        if valid.empty:raise ValueError('No qfq scaling overlap: '+symbol)
        scale=float((valid.close_old/valid.close_warm).median())
        err=float((valid.close_warm*scale/valid.close_old-1).abs().max())
        for c in ('open','high','low','close'):extra[c]=extra[c]*scale
    else:
        scale=1.
        err=float((both.close_warm-both.close_old).abs().max()) if len(both) else 0.
    before=extra[extra.date<old.date.min()]
    SPLICES.append(dict(symbol=symbol,kind=kind,added=len(before),scale=scale,overlap_error=err))
    return pd.concat([before,old],ignore_index=True).sort_values('date')

def main():
    manifest=json.loads((WARM/'manifest.json').read_text(encoding='utf-8'))
    assert all('error' not in r for r in manifest['results'])
    idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    cal=pd.DatetimeIndex(pd.to_datetime(idx.date).sort_values().unique())
    days=cal[(cal>=g.bt.START)&(cal<=g.bt.END)]
    f=build_features([(d,cal[cal.get_loc(d)-1]) for d in days])
    print('WARM FACTORS DONE',len(f),flush=True)

def build_features(pairs):
    cache=OUT/'exact_date_factors.parquet'
    if cache.exists():return pd.read_parquet(cache)
    execution=pd.DatetimeIndex([d for d,s in pairs])
    signals=pd.DatetimeIndex([s for d,s in pairs])
    pieces=[];fallbacks=0
    for number,symbol in enumerate(g.bt.load_universe(),1):
        rp,qp=g.bt.raw_path(symbol),g.bt.qfq_path(symbol)
        if not rp.exists() or not qp.exists():continue
        raw=merged(symbol, 'raw');adj=merged(symbol, 'qfq')
        for z in (raw,adj):
            z['date']=pd.to_datetime(z.date)
            z.sort_values('date',inplace=True)
            z.drop_duplicates('date',inplace=True)
        raw=raw.set_index('date');adj=adj.set_index('date')
        r=raw[raw.tradestatus.astype(str)=='1']
        q=adj[adj.tradestatus.astype(str)=='1']
        if len(q)<250:continue
        c=q.close.astype(float);ret=c.pct_change(fill_method=None)
        x=pd.DataFrame(index=q.index)
        x['amount20']=q.amount.astype(float).rolling(20,min_periods=1).mean()
        x['vol20']=ret.rolling(20).std()
        x['near_high']=c/c.rolling(120).max()
        x['below_high']=1-x.near_high
        x['below_ma60']=(1-c/c.rolling(60).mean()).clip(lower=0)
        x['downside']=ret.clip(upper=0).pow(2).rolling(20).mean().pow(.5).clip(lower=.002)
        x['eligible']=(np.arange(len(q))>=249)&c.rolling(121).count().eq(121)&q.isST.astype(str).ne('1')&x.vol20.between(.004,.08)&x.amount20.ge(50000000.)
        if q.index.equals(r.index):
            factor=c/r.close.astype(float)
            changes=factor.pct_change(fill_method=None).abs()
            events=changes.where((changes>.0005)&(changes<.12),0.)
            y0=events.rolling(250,min_periods=1).sum()
            y1=y0.shift(250).fillna(0)
            y2=y0.shift(500).fillna(0)
            x['dividend']=.7*(y0.gt(0).astype(int)+y1.gt(0).astype(int)+y2.gt(0).astype(int))/3+.3*(y0/.05).clip(upper=1)
        else:
            # Exact original reference for mismatched raw/qfq trading histories.
            x['dividend']=np.nan
            fallbacks+=1
        positions=q.index.searchsorted(signals,side='right')-1
        valid=positions>=0
        z=x.iloc[np.maximum(positions,0)].reset_index(drop=True)
        z['execute_date']=execution;z['signal_date']=signals;z['symbol']=symbol
        z=z[valid & z.eligible].copy()
        if not q.index.equals(r.index):
            z['dividend']=[g.bt.dividend_quality(q.loc[:s].tail(751),r.loc[:s].tail(751)) for s in z.signal_date]
        turn=raw.turn.astype(float)
        extra=pd.DataFrame(dict(turn20=turn.rolling(20).mean(),
            float_cap_proxy=raw.volume.astype(float)/turn.where(turn>0)*100*raw.close.astype(float)))
        e=extra.reindex(pd.DatetimeIndex(z.signal_date))
        z['turn20']=e.turn20.to_numpy();z['float_cap_proxy']=e.float_cap_proxy.to_numpy()
        pieces.append(z.drop(columns=['eligible','vol20']))
        if number%250==0:print('FACTORS',number,flush=True)
    f=pd.concat(pieces,ignore_index=True)
    f['float_cap_proxy_group']=np.floor(f.groupby('execute_date').float_cap_proxy.rank(pct=True)*3).clip(upper=2).fillna(-1).astype(int)
    old=g.features()
    common=f.merge(old,on=['execute_date','symbol'],suffixes=('_new','_old'))
    later=common[common.execute_date>='2022-01-01']
    errors={c:float((later[c+'_new']-later[c+'_old']).abs().max()) for c in ['amount20','near_high','downside','dividend']}
    save('factor_warmup_audit.json',dict(splices=SPLICES,later_errors=errors,rows=len(f),fallback_symbols=fallbacks))
    f.to_parquet(cache,index=False)
    return f

if __name__=='__main__':main()
