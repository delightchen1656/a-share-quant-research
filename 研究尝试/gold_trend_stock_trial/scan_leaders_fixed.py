"""Descriptive fixed-parameter scan of the current leader classification."""
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
import json,shutil,hashlib
import numpy as np
import pandas as pd
from run_woer_fixed import CFG,sha,save,metrics

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
OUT=Path(__file__).resolve().parent/'holdout_restricted'/'leaders_fixed_20261031'

def simulate(q,r,start_date='2020-01-01'):
    good=q.tradestatus.eq(1)&q.volume.gt(0)&q[['open','high','low','close']].gt(0).all(axis=1)
    q=q[good].reset_index(drop=True);r=r[good].reset_index(drop=True)
    c=q.close.to_numpy(float);o=q.open.to_numpy(float);dates=q.date.to_numpy()
    f=q.close.rolling(20).mean().to_numpy();slow=q.close.rolling(120).mean().to_numpy()
    h=q.close.rolling(90).max().shift(1).to_numpy()
    entries=(f>slow*1.02)|((c>h)&(c>slow));exits=f<slow*.98
    start=int((dates<start_date).sum())
    if len(q)<=start or len(q)<120:raise ValueError('insufficient_120_bar_history')
    on=False;peak=0.;blocked=-1;target=np.zeros(len(q),dtype=int);signals=[]
    for i in range(start,len(q)):
        if on:
            peak=max(peak,c[i])
            if exits[i] or c[i]<peak*.92:
                on=False;blocked=i+5;signals.append((i,'sell'))
        elif i>=blocked and entries[i]:
            on=True;peak=c[i];signals.append((i,'buy'))
        target[i]=int(on)
    weights=np.r_[0,target[:-1]];prev=np.r_[0,weights[:-1]]
    gap=np.r_[0,o[1:]/c[:-1]-1];intraday=c/o-1
    daily=(1+prev*gap)*(1+weights*intraday)
    nav=np.cumprod(daily[start:]);bh=c[start:]/o[start]
    d=pd.DataFrame(dict(date=dates[start:],nav=nav,buyhold_nav=bh,holding=weights[start:]))
    trades=[];opened=None;flags=[]
    for i,side in signals:
        if i+1>=len(q):continue
        j=i+1;row=r.iloc[j]
        limit=lambda v:float(Decimal(str(v)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        width=.05 if row.isST==1 else .1
        if (side=='buy' and row.open>=limit(row.preclose*(1+width))-1e-7)or(side=='sell' and row.open<=limit(row.preclose*(1-width))+1e-7):
            flags.append(dict(date=dates[j],side=side,raw_open=float(row.open),isST=int(row.isST)))
        if side=='buy':
            assert opened is None;opened=dict(buy_signal=dates[i],buy_date=dates[j],buy_qfq=o[j],index=j)
        else:
            assert opened is not None
            trades.append(dict(buy_signal=opened['buy_signal'],buy_date=opened['buy_date'],buy_qfq=opened['buy_qfq'],sell_signal=dates[i],sell_date=dates[j],sell_qfq=o[j],return_pct=(o[j]/opened['buy_qfq']-1)*100));opened=None
    product=np.prod([1+t['return_pct']/100 for t in trades])
    if opened:product*=c[-1]/opened['buy_qfq']
    assert np.isclose(product,nav[-1],rtol=1e-10)
    a=metrics(d.nav,d.date,1);b=metrics(d.buyhold_nav,d.date,1)
    comparable=dates[start]=='2020-01-02' and start>=120 and dates[-1]=='2026-10-30'
    result=dict(first=dates[start],last=dates[-1],warmup_bars=start,full_period_comparable=comparable,**a,buyhold_return_pct=b['total_return_pct'],buyhold_cagr_pct=b['cagr_pct'],buyhold_mdd_pct=b['max_drawdown_pct'],excess_return_pp=a['total_return_pct']-b['total_return_pct'],excess_cagr_pp=a['cagr_pct']-b['cagr_pct'],closed_trades=len(trades),win_rate_pct=float(np.mean([t['return_pct']>0 for t in trades])*100) if trades else None,exposure_pct=float(weights[start:].mean()*100),open_position=bool(weights[-1]),opening_limit_fills=len(flags),st_quoted_days=int(r.isST.sum()))
    return result,d,trades,flags

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'inputs').mkdir(exist_ok=True);(OUT/'details').mkdir(exist_ok=True)
    leader=ROOT/'研究尝试/方向1_超跌反弹/holdout_restricted/leader_classification/mainboard_leaders.parquet'
    shutil.copyfile(leader,OUT/'inputs/leaders.parquet');pool=pd.read_parquet(OUT/'inputs/leaders.parquet');assert pool.code.is_unique and len(pool)==510
    audit=ROOT/'K线数据/更新备份与审计/20261030/audit.json';a=json.loads(audit.read_text(encoding='utf8'));assert a['status']=='ok'
    save(OUT/'RULE.json',dict(parameters=CFG,start='2020-01-01',cutoff='2026-10-30',pool='510 current SH/SZ mainboard leaders; retrospective membership',excess='strategy cumulative return minus same-stock buy-and-hold cumulative return, percentage points',primary_ranking='same full period; 120 prestart quoted-bar warmup; last quoted day equals cutoff',fees=False,price_basis='qfq theoretical fractional gross returns; not dividend cash ledger',not_blind=True,parameter_search=False,execution='close signal; next quoted-day open, ideal fills even at limit (flagged)',cooldown='same as Woer fixed reference',leader_sha256=sha(leader)))
    rows=[];errors=[];unavailable=[];inputs=[];flags=[];annual=[]
    for k,stock in enumerate(pool.itertuples(),1):
        code=stock.code;ex='SH' if code.startswith('6') else 'SZ';suffix='SH' if ex=='SH' else 'SZ'
        try:
            frames=[]
            for kind in ['qfq','raw']:
                src=ROOT/f'K线数据/沪深/{kind}/{ex}/{code}.{suffix}.parquet';dest=OUT/'inputs'/f'{code}_{kind}.parquet'
                before=sha(src);shutil.copyfile(src,dest);assert before==sha(src)==sha(dest)
                inputs.append(dict(code=code,kind=kind,source=str(src),snapshot=str(dest),sha256=before))
                z=pd.read_parquet(dest);z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d')
                for col in ['open','high','low','close','preclose','volume','tradestatus','isST']:z[col]=pd.to_numeric(z[col],errors='raise')
                assert z.date.is_unique and z.date.is_monotonic_increasing and z.date.max()<='2026-10-30'
                frames.append(z)
            q,r=frames;assert q.date.tolist()==r.date.tolist()
            out,d,t,ff=simulate(q,r);out=dict(code=code,name=stock.name,**out);rows.append(out)
            d.to_csv(OUT/'details'/f'{code}_nav.csv',index=False,encoding='utf-8-sig');pd.DataFrame(t).to_csv(OUT/'details'/f'{code}_trades.csv',index=False,encoding='utf-8-sig')
            flags.extend([dict(code=code,**x) for x in ff])
            prev=1.;bh=1.
            for y,g in d.groupby(d.date.str[:4]):
                m=metrics(g.nav,g.date,prev);b=metrics(g.buyhold_nav,g.date,bh);annual.append(dict(code=code,name=stock.name,year=int(y),return_pct=m['total_return_pct'],mdd_pct=m['max_drawdown_pct'],buyhold_return_pct=b['total_return_pct']));prev=g.nav.iloc[-1];bh=g.buyhold_nav.iloc[-1]
        except Exception as e:
            item=dict(code=code,name=stock.name,error=repr(e))
            if str(e)=='insufficient_120_bar_history':unavailable.append(item)
            else:errors.append(item)
        if k%50==0:print(json.dumps(dict(processed=k,success=len(rows),errors=len(errors))),flush=True)
    df=pd.DataFrame(rows);rank=df[df.full_period_comparable].copy()
    absolute=rank.sort_values(['total_return_pct','code'],ascending=[False,True]).head(10)
    excess=rank.sort_values(['excess_return_pp','code'],ascending=[False,True]).head(10)
    df.to_csv(OUT/'all_results.csv',index=False,encoding='utf-8-sig');absolute.to_csv(OUT/'top10_absolute.csv',index=False,encoding='utf-8-sig');excess.to_csv(OUT/'top10_excess.csv',index=False,encoding='utf-8-sig');pd.DataFrame(annual).to_csv(OUT/'annual_all.csv',index=False,encoding='utf-8-sig');save(OUT/'ERRORS.json',errors);save(OUT/'OPEN_LIMIT_FLAGS.json',flags)
    # Regression against the already delivered identical Woer experiment.
    woer=df[df.code.eq('002130')].iloc[0];ref=json.loads((OUT.parent/'woer_fixed_20261031/RESULT.json').read_text(encoding='utf8'))
    assert np.isclose(woer.total_return_pct,ref['strategy']['total_return_pct']) and np.isclose(woer.max_drawdown_pct,ref['strategy']['max_drawdown_pct'])
    save(OUT/'INSUFFICIENT_HISTORY.json',unavailable)
    valid=dict(pool=len(pool),success=len(df),errors=len(errors),insufficient_120_bar_history=len(unavailable),full_period_ranked=len(rank),short_or_incomplete=len(df)-len(rank),strategy_positive=int(rank.total_return_pct.gt(0).sum()),positive_excess=int(rank.excess_return_pp.gt(0).sum()),woer_regression_passed=True,independent_trade_wealth_reconciliation_all=True,limit_fill_stocks=int(rank.opening_limit_fills.gt(0).sum()))
    save(OUT/'SUMMARY.json',dict(validation=valid,top10_absolute=absolute.to_dict('records'),top10_excess=excess.to_dict('records')))
    save(OUT/'MANIFEST.json',dict(created_at=datetime.now(timezone.utc).isoformat(),inputs=inputs,audit_sha256=sha(audit),leader_sha256=sha(leader),script_sha256=sha(Path(__file__)),rule_sha256=sha(OUT/'RULE.json'),outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.json','.csv'] and p.name!='MANIFEST.json'}))
    print(json.dumps(valid,ensure_ascii=False));print('ABSOLUTE');print(absolute[['code','name','total_return_pct','cagr_pct','max_drawdown_pct','buyhold_return_pct','excess_return_pp','opening_limit_fills']].to_string(index=False));print('EXCESS');print(excess[['code','name','total_return_pct','cagr_pct','max_drawdown_pct','buyhold_return_pct','excess_return_pp','opening_limit_fills']].to_string(index=False))

if __name__=='__main__':main()
