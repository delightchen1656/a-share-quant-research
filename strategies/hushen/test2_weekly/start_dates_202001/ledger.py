import pandas as pd
import socket,time,json

def load(p,engine,ranks,dates,old):
    wanted=set(s for v in ranks.values() for s in v);panels=[];requests=set()
    for s in sorted(wanted):
        x=pd.read_parquet(p.DATA/'raw'/s[-2:]/(s+'.parquet'));x.date=pd.to_datetime(x.date);x=x[x.date<=pd.Timestamp('2026-09-30')].sort_values('date')
        for column in p.COLS[1:]:x[column]=pd.to_numeric(x[column],errors='raise')
        x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual;x['symbol']=s
        z=x[(x.date>='2020-01-01')&((x.adjust_ratio-1).abs()>1e-5)];requests.update((s,int(y)) for y in z.date.dt.year.unique());panels.append(x)
    cache={}
    for path in old.glob('actions_*.json'):cache.update(json.loads(path.read_text(encoding='utf-8')))
    if (p.HERE/'additional_actions.json').exists():cache.update(p.read('additional_actions.json'))
    for path in p.HERE.glob('action_part_*.json'):cache.update(json.loads(path.read_text(encoding='utf-8')))
    missing=[(s,y) for s,y in sorted(requests) if s+'/'+str(y) not in cache];extra={}
    if missing:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(fetch_batch,missing[i::4],i,str(p.HERE)) for i in range(4)]
            for future in as_completed(jobs):cache.update(future.result())
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
    return days,actions,outs


def fetch_batch(items,index,folder):
    from pathlib import Path
    import baostock as bs
    path=Path(folder)/('action_part_%d.json'%index)
    cache=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    socket.setdefaulttimeout(40)
    def save():
        payload=json.dumps(cache,ensure_ascii=False,indent=2)
        for attempt in range(5):
            try:
                temp=path.with_suffix('.tmp');temp.write_text(payload,encoding='utf-8');temp.replace(path);return
            except OSError:
                if attempt==4:raise
                time.sleep(.3)
    assert bs.login().error_code=='0'
    try:
        for i,(symbol,year) in enumerate(items):
            key=symbol+'/'+str(year)
            for attempt in range(5):
                try:
                    r=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=str(year),yearType='operate')
                    rows=[]
                    while r.error_code=='0' and r.next():rows.append(r.get_row_data())
                    if r.error_code!='0':raise RuntimeError(r.error_msg)
                    cache[key]=pd.DataFrame(rows,columns=r.fields).to_dict('records');break
                except Exception:
                    if attempt==4:raise
                    time.sleep(1);bs.login()
            if i%20==0:save();print('ACTIONS',index,i,'/',len(items),flush=True)
    finally:save();bs.logout()
    return cache
