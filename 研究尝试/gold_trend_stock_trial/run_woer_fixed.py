"""Fixed user-specified gold trend rule on one stock. No optimization or production writes."""
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json, hashlib, shutil
import numpy as np
import pandas as pd

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
OUT=Path(__file__).resolve().parent/'holdout_restricted'/'woer_fixed_20261031'
CFG=dict(fast=20,slow=120,entry_buffer=.02,exit_buffer=.02,breakout=90,trailing_stop=.08,cooldown=5)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,z):p.write_text(json.dumps(z,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def targets(close,start=0):
    fast=close.rolling(20).mean();slow=close.rolling(120).mean()
    trend=fast>slow*1.02; br=(close>close.rolling(90).max().shift(1))&(close>slow)
    on=False;peak=0.;blocked=-1;rows=[]
    for i,price in enumerate(close):
        reason='';signal=''
        if i<start:
            rows.append(dict(target=0,signal='',reason='',peak=0.,ma20=fast.iloc[i],ma120=slow.iloc[i],breakout_high=close.iloc[max(0,i-90):i].max() if i>=90 else np.nan))
            continue
        if on:
            peak=max(peak,float(price))
            leave=[]
            if fast.iloc[i]<slow.iloc[i]*.98:leave.append('MA20<MA120*0.98')
            if price<peak*.92:leave.append('close_drawdown>8%')
            if leave:on=False;blocked=i+5;reason=';'.join(leave);signal='sell'
        elif i>=blocked and (trend.iloc[i] or br.iloc[i]):
            on=True;peak=float(price);reason='trend_or_breakout';signal='buy'
        rows.append(dict(target=int(on),signal=signal,reason=reason,peak=peak,ma20=fast.iloc[i],ma120=slow.iloc[i],breakout_high=close.iloc[max(0,i-90):i].max() if i>=90 else np.nan))
    return pd.DataFrame(rows,index=close.index)

def metrics(nav,dates,initial):
    a=np.r_[initial,np.asarray(nav)];dd=a/np.maximum.accumulate(a)-1
    days=(pd.Timestamp(dates.iloc[-1])-pd.Timestamp(dates.iloc[0])).days+1
    total=float(a[-1]/initial-1)
    return dict(total_return_pct=total*100,cagr_pct=((a[-1]/initial)**(365.2425/days)-1)*100,max_drawdown_pct=float(-dd.min()*100),ending_nav=float(a[-1]))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    # Freeze the supplied rule before computing outcomes; no search space.
    save(OUT/'RULE.json',dict(code='002130',name='沃尔核材',parameters=CFG,start='2020-01-01',end='2026-10-30',start_flat=True,initial_nav=1.,execution='signal close -> next quoted trading-day open',cooldown='exit signal index i; next entry check at close i+5, earliest reentry open i+6 (same as gold reference)',peak='maximum close since entry signal, including entry signal close',return_basis='fractional adjusted-price observation, not corporate-action cash ledger',fees_slippage_lot_rounding=False,no_parameter_search=True,not_blind=True))
    audit=ROOT/'K线数据/更新备份与审计/20261030/audit.json';a=json.loads(audit.read_text(encoding='utf8'));assert a['status']=='ok' and a['target']=='2026-10-30'
    commit=json.loads((audit.parent/'commit_manifest.json').read_text(encoding='utf8'))
    paths={}
    for kind in ['raw','qfq']:
        p=ROOT/f'K线数据/沪深/{kind}/SZ/002130.SZ.parquet'
        assert any(x['destination']==str(p.relative_to(ROOT)).replace('\\','/') for x in commit['files'])
        dest=OUT/f'{kind}.parquet';shutil.copyfile(p,dest);assert sha(p)==sha(dest)
        paths[kind]=dict(source=str(p),snapshot=str(dest),sha256=sha(dest))
    q=pd.read_parquet(OUT/'qfq.parquet');raw=pd.read_parquet(OUT/'raw.parquet')
    for z in [q,raw]:
        z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d')
        for c in ['open','high','low','close','preclose','volume','tradestatus','isST']:z[c]=pd.to_numeric(z[c],errors='raise')
        assert z.date.is_unique and z.date.is_monotonic_increasing and z.date.max()=='2026-10-30'
    assert q.date.tolist()==raw.date.tolist()
    good=q.tradestatus.eq(1)&q.volume.gt(0)&q[['open','high','low','close']].gt(0).all(axis=1)
    q=q[good].reset_index(drop=True);raw=raw[good].reset_index(drop=True)
    assert np.isfinite(q[['open','high','low','close']]).all().all() and raw.isST.eq(0).all()
    start=int(q.date.lt('2020-01-01').sum());s=targets(q.close,start)
    # Future-price changes cannot change any earlier signal.
    n=int(q.date.le('2024-12-31').sum());pd.testing.assert_frame_equal(s.iloc[:n],targets(q.close.iloc[:n],start))
    cash=1.;units=0.;entry=None;records=[];trades=[];limit_flags=[];pending=None
    for i,row in q.iterrows():
        if row.date<'2020-01-01':continue
        if pending:
            side=pending['signal'];r=raw.iloc[i]
            limit=lambda x:float(Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
            blocked=(side=='buy' and r.open>=limit(r.preclose*1.1)-1e-7)or(side=='sell' and r.open<=limit(r.preclose*.9)+1e-7)
            if blocked:limit_flags.append(dict(date=row.date,side=side,raw_open=float(r.open),preclose=float(r.preclose),note='opening at limit: ideal open fill is not guaranteed'))
            if side=='buy':
                assert units==0;units=cash/row.open;cash=0.
                entry=dict(signal_date=pending['date'],buy_date=row.date,buy_qfq=float(row.open),entry_nav=float(units*row.open),entry_index=i)
            else:
                assert units>0 and entry is not None
                cash=units*row.open;units=0.
                trades.append(dict(**{k:v for k,v in entry.items() if k!='entry_index'},sell_signal_date=pending['date'],sell_date=row.date,sell_qfq=float(row.open),return_pct=(row.open/entry['buy_qfq']-1)*100,holding_bars=i-entry['entry_index'],exit_reason=pending['reason'],signal_peak=pending['peak'],exit_below_signal_peak_pct=(1-row.open/pending['peak'])*100))
                entry=None
            pending=None
        nav=float(cash+units*row.close)
        # An independent flat start, using only earlier prices to warm indicators.
        if units>0:
            if s.iloc[i].signal=='sell':pending=dict(s.iloc[i],date=row.date)
        elif s.iloc[i].target==1:
            # Only the first evaluation day may inherit an earlier trend target.
            if not records or s.iloc[i].signal=='buy':pending=dict(s.iloc[i],date=row.date,signal='buy')
        records.append(dict(date=row.date,nav=nav,holding=int(units>0),close_qfq=float(row.close),signal=s.iloc[i].signal,signal_target=int(s.iloc[i].target)))
    d=pd.DataFrame(records);t=pd.DataFrame(trades)
    first=q[q.date.ge('2020-01-01')].iloc[0];d['buyhold_nav']=d.close_qfq/first.open
    annual=[];prev=1.;bp=1.
    for y,g in d.groupby(d.date.str[:4]):
        st=metrics(g.nav,g.date,prev);bh=metrics(g.buyhold_nav,g.date,bp)
        annual.append(dict(year=int(y),strategy_return_pct=st['total_return_pct'],strategy_mdd_pct=st['max_drawdown_pct'],buyhold_return_pct=bh['total_return_pct'],buyhold_mdd_pct=bh['max_drawdown_pct'],exposure_pct=g.holding.mean()*100))
        prev=float(g.nav.iloc[-1]);bp=float(g.buyhold_nav.iloc[-1])
    summary=dict(strategy=metrics(d.nav,d.date,1.),buyhold=metrics(d.buyhold_nav,d.date,1.),first=d.date.min(),last=d.date.max(),closed_trades=len(t),winning_trades=int(t.return_pct.gt(0).sum()),trade_win_rate_pct=float(t.return_pct.gt(0).mean()*100),mean_trade_return_pct=float(t.return_pct.mean()),median_trade_return_pct=float(t.return_pct.median()),exposure_pct=float(d.holding.mean()*100),limit_open_fills_flagged=limit_flags,open_position=entry,pending_last_close=pending,annual=annual,signal_prefix_invariance_passed=True,price_observation_only=True)
    for label,mask in [('2020_2024',d.date.le('2024-12-31')),('2025_latest',d.date.ge('2025-01-01'))]:
        g=d[mask];idx=g.index[0];base=1. if idx==0 else d.nav.iloc[idx-1]
        summary[label]=metrics(g.nav,g.date,base)
    d.to_csv(OUT/'daily_nav.csv',index=False,encoding='utf-8-sig');t.to_csv(OUT/'trades.csv',index=False,encoding='utf-8-sig');pd.DataFrame(annual).to_csv(OUT/'annual.csv',index=False,encoding='utf-8-sig')
    s.insert(0,'date',q.date);s.to_csv(OUT/'signals.csv',index=False,encoding='utf-8-sig')
    save(OUT/'RESULT.json',summary)
    save(OUT/'MANIFEST.json',dict(created_at=datetime.now(timezone.utc).isoformat(),inputs=paths,audit_sha256=sha(audit),script_sha256=sha(Path(__file__)),rule_sha256=sha(OUT/'RULE.json'),limitations=['Adjusted-price fractional theoretical returns; not net account returns or dividend cash accounting','No fees, slippage, integer shares or actual limit-order fills','Current leader designation is not a historical stock selection rule','Known full-period data; descriptive fixed-rule trial, not a fresh blind test'],outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.csv','.json'] and p.name!='MANIFEST.json'}))
    print(json.dumps(summary,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':main()
