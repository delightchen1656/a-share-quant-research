"""Past-only style price baskets: signals, never claimed as realizable account returns."""
import hashlib
import numpy as np
import pandas as pd
import research as r
from round04 import adjustment_features
from round08_long_momentum import long_features
from round13_liquidity_universe import rank as universe_rank
from prepare_lower_liquidity import PATH as LIVE_FEATURES

WARM=r.HERE/'features_style_warmup_2019.parquet'
RANKS=r.HERE/'style_rank_history.parquet'
INDICES=r.HERE/'style_price_indices.parquet'
STYLES={'defensive_small':('defensive@5','small'),'carry_mid':('carry_long@50','mid'),
        'barbell_mid':('barbell@50','mid'),'liquidity_small':('liquidity@5','small')}

def build_warmup():
    if WARM.exists():return pd.read_parquet(WARM)
    end=r.END;r.END=pd.Timestamp('2019-12-31');r.FEATURE_START='2019-01-01'
    r.FEATURES=r.HERE/'features_style_warmup_base_2019.parquet';r.MIN_AMOUNT20=5e6;r.MIN_SIGNAL_VOL=.001
    try:f=r.build_features()
    finally:r.END=end
    market=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
    parts=[]
    for i,(s,rows) in enumerate(f.groupby('symbol')):
        raw=pd.read_parquet(r.e.raw_path(s),columns=['date','close','preclose']).sort_values('date').set_index('date')
        q=pd.read_parquet(r.e.qfq_path(s),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        z=adjustment_features(raw).join(long_features(q,market)).reindex(pd.DatetimeIndex(rows.signal_date));z.index=rows.index;parts.append(z)
        if i%500==0:print('WARMUP_SIGNALS',i,flush=True)
    f=f.join(pd.concat(parts));f.to_parquet(WARM,index=False)
    return f

def basket_index(returns,selections,calendar):
    """Old weights earn today's return; close-time reconstitution affects tomorrow."""
    weights={};nav=1.;rows=[]
    for date in calendar:
        ret={s:float(returns.at[date,s]) if pd.notna(returns.at[date,s]) else 0. for s in weights}
        if ret:assert min(ret.values())>=-1-1e-10
        change=sum(weights[s]*ret[s] for s in weights)
        nav*=1+change
        if weights:
            weights={s:w*(1+ret[s])/(1+change) for s,w in weights.items()} if change>-1 else {}
        rows.append((date,nav,change))
        if date in selections:
            symbols=selections[date];weights={s:1/len(symbols) for s in symbols}
    return pd.DataFrame(rows,columns=['date','index_value','index_return'])

def main():
    assert not INDICES.exists(),'Preserve completed style signals'
    r.save(r.HERE/'style_history_protocol.json',dict(styles=STYLES,constituents=12,
        construction='Monthly close reconstitution using prior-day features;existing constituents earn current-day return BEFORE replacement;weights drift between months;no future filling;delisting terminal loss100%',
        usage='Price baskets only,not executable account performance;no fees/lots. Opening account decisions MUST use prior-day index and real execution ledger.',
        implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest()))
    if RANKS.exists():ranked=pd.read_parquet(RANKS)
    else:
        warm=build_warmup();f=pd.concat([warm,pd.read_parquet(LIVE_FEATURES)],ignore_index=True)
        assert not f.duplicated(['execute_date','symbol']).any()
        rows=[]
        for name,(family,size) in STYLES.items():
            for date,q in f.groupby('execute_date'):
                z=universe_rank(q,dict(family=family,size=size,buffer=60))
                assert len(z)>=12
                rows.append(z.assign(execute_date=date,style=name))
            print('STYLE_RANK',name,flush=True)
        ranked=pd.concat(rows,ignore_index=True);ranked.to_parquet(RANKS,index=False)
    cal=pd.DatetimeIndex(pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').date).sort_values()
    cal=cal[(cal>=ranked.execute_date.min())&(cal<=r.END)]
    due=set(pd.Series(cal,index=cal).groupby(cal.to_period('M')).first())
    selections={name:{d:q.head(12).symbol.tolist() for d,q in z.groupby('execute_date') if d in due} for name,z in ranked.groupby('style')}
    symbols=sorted({s for seq in selections.values() for ss in seq.values() for s in ss})
    universe=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    exits={x['symbol']:pd.Timestamp(x['outDate']) for x in universe.to_dict('records') if pd.notna(x['outDate'])}
    parts=[]
    for s in symbols:
        close=pd.read_parquet(r.e.qfq_path(s),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        ret=close.reindex(cal).ffill().pct_change(fill_method=None).fillna(0.)
        if s in exits and exits[s]<=cal[-1]:
            p=cal.searchsorted(exits[s])
            if p<len(cal):ret.iloc[p]=-1.
        parts.append(ret.rename(s))
    returns=pd.concat(parts,axis=1)
    curves=[basket_index(returns,sel,cal).assign(style=name) for name,sel in selections.items()]
    result=pd.concat(curves,ignore_index=True);result.to_parquet(INDICES,index=False)
    r.save(r.HERE/'style_history_manifest.json',dict(rows=len(result),rank_rows=len(ranked),start=str(cal[0]),end=str(cal[-1]),symbols=len(symbols),styles=STYLES,
        warning='Signal construction only,no account backtest or goal achievement yet. Index must be lagged1day before opening decisions.'))
    print('STYLE_HISTORY_DONE',len(result),len(ranked),flush=True)

if __name__=='__main__':main()
