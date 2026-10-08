"""Evaluate the already frozen R08 only. Never write weights or rank candidates."""
import pipeline as p
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
import math,socket,time,json

def main():
    frozen=p.read('frozen.json');entry=p.HERE/'supermind_mainboard_baseline_1_retrained_2022.py'
    assert p.sha(entry)==frozen['export_sha256'] and (p.HERE/'confirmation.json').exists()
    if (p.HERE/'evaluation.json').exists():raise RuntimeError('Evaluation already recorded; no feedback reruns')
    old=p.PARENT/'start_date_study';engine=p.mod(old/'study.py','execution')
    engine.load_model=lambda k:engine.module(entry,'new_export')
    model=engine.load_model('R08')
    # Check the cached causal features against all original raw source hashes.
    hashes=json.loads((old/'input_hashes.json').read_text(encoding='utf-8'))
    for path in sorted((p.DATA/'raw').glob('*/*.parquet')):assert hashes[path.stem]==p.sha(path),path
    market=pd.read_parquet(old/'benchmark.parquet').set_index('date').close;dates=market.index
    data=pq.read_table(old/'r08_features.parquet',filters=[('date','>=',pd.Timestamp('2022-12-01').to_pydatetime())]).to_pandas()
    ranks={str(d.date()):model.rank_candidates(x).symbol.tolist() for d,x in data.groupby('date')}
    wanted=set(s for v in ranks.values() for s in v);panels=[];requests=set()
    for s in sorted(wanted):
        x=pd.read_parquet(p.DATA/'raw'/s[-2:]/(s+'.parquet'));x.date=pd.to_datetime(x.date);x=x[x.date<=pd.Timestamp('2026-09-30')].sort_values('date')
        for column in p.COLS[1:]:x[column]=pd.to_numeric(x[column],errors='raise')
        x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual;x['symbol']=s
        z=x[(x.date>='2023-01-01')&((x.adjust_ratio-1).abs()>1e-5)];requests.update((s,int(y)) for y in z.date.dt.year.unique());panels.append(x)
    cache={}
    for path in old.glob('actions_*.json'):cache.update(json.loads(path.read_text(encoding='utf-8')))
    if (p.HERE/'additional_actions.json').exists():cache.update(p.read('additional_actions.json'))
    missing=[(s,y) for s,y in sorted(requests) if s+'/'+str(y) not in cache];extra={}
    if missing:
        import baostock as bs
        socket.setdefaulttimeout(40);assert bs.login().error_code=='0'
        try:
            for i,(s,y) in enumerate(missing):
                for attempt in range(4):
                    try:
                        r=bs.query_dividend_data(code=s[-2:].lower()+'.'+s[:6],year=str(y),yearType='operate')
                        rows=engine.bs_frame(r).to_dict('records');break
                    except Exception:
                        if attempt==3:raise
                        time.sleep(1);bs.login()
                cache[s+'/'+str(y)]=rows;extra[s+'/'+str(y)]=rows
                if i%10==0:p.dump('additional_actions.json',extra);print('ACTIONS',i,len(missing),flush=True)
        finally:p.dump('additional_actions.json',extra);bs.logout()
    actions={}
    def num(v):return float(v) if str(v).strip() else 0.
    for key,rows in cache.items():
        s=key.split('/')[0]
        if s not in wanted:continue
        for r in rows:
            if not r['dividOperateDate']:continue
            d=pd.Timestamp(r['dividOperateDate']);actions[s,d]=dict(cash=num(r['dividCashPsBeforeTax']),stock=num(r['dividStocksPs'])+num(r['dividReserveToStockPs']),
                taxable_stock=num(r['dividStocksPs']),pay=pd.Timestamp(r['dividPayDate'] or r['dividOperateDate']),release=pd.Timestamp(r['dividStockMarketDate'] or r['dividOperateDate']))
    days={d:{} for d in dates}
    for x in panels:
        for row in x.itertuples(index=False):
            if row.date in days:days[row.date][row.symbol]=row
    meta=pd.read_csv(p.DATA/'metadata/historical_mainboard_universe.csv');outs={r.symbol:pd.Timestamp(r.outDate) for r in meta.itertuples() if pd.notna(r.outDate)}
    results=[];curves=[];trades=[];issues={}
    for name,start,end in [('selection','2023-01-01','2023-12-31'),('confirmation','2024-01-01','2024-11-29'),('held_out_history','2025-01-01','2026-09-30')]:
        sessions=dates[(dates>=start)&(dates<=end)];a=engine.Account('R08',sessions[0],actions,days,outs)
        for date in sessions:
            i=dates.get_loc(date);a.step(date,i,dates[i-1],ranks)
        assert a.trades,('No fills: investigate data adapter',name)
        q=pd.DataFrame(a.curve);nav=q.equity.to_numpy();ret=np.diff(np.r_[100000.,nav])/np.r_[100000.,nav[:-1]]
        results.append(dict(period=name,start=str(sessions[0].date()),end=str(sessions[-1].date()),initial_cash=100000,final_equity=nav[-1],
            total_return=nav[-1]/100000-1,cagr=(nav[-1]/100000)**(365.25/((sessions[-1]-sessions[0]).days+1))-1,
            max_drawdown=float(-(nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]-1).min()),sharpe_zero_rf=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)),
            trades=len(a.trades),fees=a.fees,dividend_tax=a.tax,average_exposure=q.exposure.mean(),unresolved_actions=len(a.issues),capacity_rejections=a.capacity_hits))
        curves.extend(dict(v,period=name) for v in a.curve);trades.extend(dict(v,period=name) for v in a.trades);issues.update(a.issues)
        print('PERIOD',results[-1],flush=True)
    pd.DataFrame(curves).to_parquet(p.HERE/'daily_equity.parquet',index=False);pd.DataFrame(trades).to_parquet(p.HERE/'trades.parquet',index=False)
    p.dump('unresolved_actions.json',issues)
    p.dump('evaluation.json',dict(periods=results,frozen_sha256=p.sha(p.HERE/'frozen.json'),feature_cache_sha256=p.sha(old/'r08_features.parquet'),
        note='Frozen champion only; open-price daily approximation, not SuperMind execution reproduction. Held-out history was previously exposed.'))
if __name__=='__main__':main()
