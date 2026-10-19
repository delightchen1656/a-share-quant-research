"""Forward-only paper ledger. No broker API, retraining, or historical signal backfill."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse, hashlib, inspect, json, os, sys, subprocess
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
STAR=HERE.parent
ROOT=STAR.parents[1]
DATA=ROOT/'evening_accumulation/data'
sys.path.insert(0,str(STAR/'backtest'))
import engine
import data_helpers as p
START='2026-10-17'
CASH=500000.

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,obj,immutable=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    if immutable and path.exists():
        if read(path)!=obj:raise ValueError('Immutable record differs: '+str(path))
        return
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
    os.replace(tmp,path)

def updater_idle():
    cmd="Get-CimInstance Win32_Process | Where-Object {$_.Name -match 'python' -and $_.CommandLine -match 'daily_market_update.py'} | Select-Object -ExpandProperty ProcessId"
    result=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,text=True,check=True)
    if result.stdout.strip():raise RuntimeError('行情更新进程仍在运行；不读取混合数据')

def calendar(asof):
    dest=HERE/'inputs'/('calendar_'+asof+'.json')
    if dest.exists():rows=read(dest)
    else:
        import baostock as bs
        sys.path.insert(0,str(ROOT/'tools'))
        from daily_market_update import install_baostock_socket_safety
        install_baostock_socket_safety()
        if bs.login().error_code!='0':raise RuntimeError('Calendar login failed')
        try:
            result=bs.query_trade_dates(start_date='2026-10-01',end_date=str((pd.Timestamp(asof)+pd.Timedelta(days=32)).date()))
            if result.error_code!='0':raise RuntimeError(result.error_msg)
            rows=result.get_data().to_dict('records')
        finally:bs.logout()
        if not rows:raise RuntimeError('Empty trading calendar')
        write(dest,rows,True)
    frame=pd.DataFrame(rows)
    assert not frame.calendar_date.duplicated().any()
    if asof not in set(frame.calendar_date):raise RuntimeError('Calendar has no current date')
    dates=pd.DatetimeIndex(pd.to_datetime(frame.loc[frame.is_trading_day.astype(str).eq('1'),'calendar_date']))
    if not len(dates[dates>asof]):raise RuntimeError('No verified next session')
    return dates

def verify_code():
    source=STAR/'supermind_kechuang_1.py'
    assert sha(source)==read(STAR/'research/provenance.json')['platform_sha256']
    hashes={str(f.relative_to(ROOT)):sha(f) for f in [source,STAR/'backtest/engine.py',STAR/'backtest/data_helpers.py',Path(__file__)]}
    cfg={'name':'科创基准1本地前向模拟','start':START,'cash':CASH,'timezone':'Asia/Shanghai','schedule':'18:30 daily',
         'source_hashes':hashes,'policy':'旧动态10%-20%，现金不足整笔跳过；先买后卖；旧退出分支',
         'execution':'次一交易日开盘日线近似，18:30收盘后结算，不是实时成交',
         'costs':'沿用冻结本地引擎：滑点单边0.2%，佣金万三最低5元，卖出印花税千一，分红税20%；非券商精确口径'}
    write(HERE/'config.json',cfg,True)
    return source,hashes

def load_panels(symbols,cutoff):
    frames={};fingerprints={}
    for symbol in symbols:
        path=DATA/'raw'/(symbol+'.parquet')
        fingerprints[str(path.relative_to(ROOT))]=sha(path)
        raw=pd.read_parquet(path).sort_values('date').set_index('date').loc[:cutoff]
        if raw.index.duplicated().any():raise RuntimeError('Duplicate raw '+symbol)
        raw['prev_actual']=raw.close.shift();raw['adjust_ratio']=raw.preclose/raw.prev_actual
        frames[symbol]=raw
    return frames,fingerprints

def signal(source,cutoff,entry,meta):
    dest=HERE/'signals'/(entry+'.json')
    if dest.exists():
        result=read(dest)
        if result['signal_date']!=cutoff:raise RuntimeError('Signal date conflict')
        return result
    ns=p.namespace(source.read_text(encoding='utf-8-sig'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    ns['g'].model=models[0]
    features=[];hashes={};excluded=[]
    for symbol in models[0]['universe']:
        if symbol not in meta.index:raise RuntimeError('Missing metadata '+symbol)
        out=pd.to_datetime(meta.loc[symbol,'outDate'],errors='coerce')
        ipo=pd.to_datetime(meta.loc[symbol,'ipoDate'],errors='coerce')
        if pd.notna(out) and out<=pd.Timestamp(cutoff):continue
        if pd.notna(ipo) and ipo>pd.Timestamp(cutoff):continue
        file=DATA/'qfq'/(symbol+'.parquet')
        hashes[str(file.relative_to(ROOT))]=sha(file)
        q=pd.read_parquet(file).sort_values('date').set_index('date').loc[:cutoff]
        if q.empty or q.index.max()!=pd.Timestamp(cutoff):raise RuntimeError('Missing latest quote '+symbol+'; verify suspension, do not silently exclude')
        if q.index.duplicated().any():raise RuntimeError('Duplicate qfq '+symbol)
        frame=q.tail(121).rename(columns={'turn':'turnover_rate','amount':'turnover','pctChg':'quote_rate','isST':'is_st'})
        frame['is_st']=frame.is_st.astype(str).eq('1')
        with np.errstate(invalid='ignore',divide='ignore'):v=ns['_last_features'](frame)
        if v is not None:features.append((symbol,v))
    scores=[]
    if features:
        x=np.asarray([v for _,v in features])
        up=ns['_batch_probabilities'](models[0],x);stop=ns['_batch_probabilities'](models[1],x)
        for (symbol,_),u,s in zip(features,up,stop):
            if u>=.63 and s<=.50:scores.append({'symbol':symbol,'p':float(u),'stop':float(s),'score':float(u-.22*s)})
    scores.sort(key=lambda r:(-r['score'],r['symbol']))
    result={'signal_date':cutoff,'entry_date':entry,'generated_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'source_sha256':sha(source),'candidates':scores[:8],'input_hashes':hashes,'feature_count':len(features)}
    for f,h in hashes.items():
        if sha(ROOT/f)!=h:raise RuntimeError('Input changed during prediction')
    # Caller commits only after the complete replay and consistency checks pass.
    return result

def main(asof):
    if asof<START:raise ValueError('Before authorized start')
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    if asof>now.date().isoformat():raise ValueError('Future session forbidden')
    source,hashes=verify_code()
    dates=calendar(asof)
    if pd.Timestamp(asof) in dates and asof==now.date().isoformat() and now.hour<18:raise RuntimeError('Wait for the evening committed update')
    cutoff=str(dates[dates<=asof][-1].date())
    entry=str(dates[dates>asof][0].date())
    first=str(dates[dates>START][0].date())
    updater_idle()
    audit_path=ROOT/'data_updates'/cutoff.replace('-','')/'audit.json'
    audit=read(audit_path)
    if audit.get('status')!='ok' or audit.get('target')!=cutoff or not audit.get('committed_files'):raise RuntimeError('Latest market transaction not committed')
    refresh=read(DATA/'metadata'/('refresh_'+cutoff.replace('-','')+'.json'))
    if refresh.get('status')!='ok' or refresh.get('target')!=cutoff:raise RuntimeError('Refresh mismatch')
    meta_path=DATA/'metadata/universe.csv';meta_hash=sha(meta_path)
    meta=pd.read_csv(meta_path).set_index('symbol')
    pending=signal(source,cutoff,entry,meta)
    signals={}
    for file in sorted((HERE/'signals').glob('*.json')):
        obj=read(file)
        if obj['source_sha256']!=sha(source):raise RuntimeError('Historical signal model changed')
        if obj['generated_at'][:10]>=obj['entry_date']:raise RuntimeError('Signal was not frozen before entry day')
        signals[obj['entry_date']]=obj
    session_days=dates[(dates>=first)&(dates<=cutoff)]
    for day in session_days:
        if str(day.date()) not in signals:raise RuntimeError('Missed forward signal; no retrospective backfill '+str(day.date()))
    curve=[];trades=[];positions=[];receivables=[]
    rawhashes={};new_sessions=[]
    if len(session_days):
        symbols=sorted({c['symbol'] for v in signals.values() for c in v['candidates']})
        panels,rawhashes=load_panels(symbols,cutoff)
        for day in session_days:
            for symbol in symbols:
                if day not in panels[symbol].index:
                    raise RuntimeError('Missing session row; verify suspension/delisting '+symbol+' '+str(day))
        # Fresh vendor responses cover every traded symbol/year, including pre-announced payments.
        action_dir=HERE/'inputs'/('actions_'+cutoff);action_dir.mkdir(parents=True,exist_ok=True)
        env=dict(engine.__dict__);env['OUT']=action_dir
        exec(inspect.getsource(engine.actions),env)
        actions=env['actions']({(s,y) for s in symbols for y in range(int(first[:4]),int(cutoff[:4])+1)})
        replay_dates=dates[(dates>=dates[dates<pd.Timestamp(first)][-1])&(dates<=cutoff)]
        candidates={dates[dates<pd.Timestamp(d)][-1]:[r['symbol'] for r in v['candidates']] for d,v in signals.items() if d<=cutoff}
        ns={'_exit_action':engine.old_exit}
        src=inspect.getsource(engine.run_starts)
        needle='return results[0],all_curves[0],pd.DataFrame(all_trades),reference_differences'
        assert needle in src
        src=src.replace(needle,needle+',holdings,receivables')
        src=src.replace('years=(END-start).days/365.25','years=max(1,(END-start).days)/365.25')
        env=dict(engine.__dict__);env.update(END=pd.Timestamp(cutoff),CASH=CASH,OUT=action_dir)
        exec(src,env)
        with np.errstate(invalid='ignore',divide='ignore'):
            result,c,tx,diffs,held,receivables=env['run_starts']((ns,[{'max_positions':14}],replay_dates,panels,candidates,meta,set()),actions,first)
        curve=json.loads(c.to_json(orient='records',date_format='iso'))
        trades=json.loads(tx.to_json(orient='records',date_format='iso'))
        positions=[dict(symbol=s,**v) for s,v in held.items()]
        for row in curve:
            day=row['date'][:10]
            obj={'date':day,'account':row,'trades':[t for t in trades if t['date'][:10]==day]}
            # Compare economic records, not expanding universe/hash inventories.
            obj=json.loads(json.dumps(obj,default=str,allow_nan=False))
            dest=HERE/'sessions'/(day+'.json')
            if dest.exists() and read(dest)!=obj:raise RuntimeError('Historical simulated fills/NAV changed; reconcile '+day)
            new_sessions.append((dest,obj))
        # Exact raw history fingerprint per already-recorded symbol; new symbols do not alter old checks.
        for f,h in rawhashes.items():
            if sha(ROOT/f)!=h:raise RuntimeError('Raw input changed while replaying')
    updater_idle()
    if sha(meta_path)!=meta_hash:raise RuntimeError('Metadata changed during run')
    for file,h in hashes.items():
        if sha(ROOT/file)!=h:raise RuntimeError('Code changed during run')
    # Append immutable events first; materialized tracker can be rebuilt after a crash.
    for dest,obj in new_sessions:write(dest,obj,True)
    write(HERE/'signals'/(entry+'.json'),pending,True)
    last=curve[-1] if curve else {'equity':CASH,'cash':CASH,'positions':0,'exposure':0.}
    state={'name':'科创基准1本地前向模拟','start_date':START,'as_of':asof,'market_cutoff':cutoff,
           'first_possible_fill':first,'next_entry_date':entry,'initial_cash':CASH,'nav':last['equity'],
           'cash':last['cash'],'total_return':last['equity']/CASH-1,'positions':positions,'receivables':receivables,
           'fills':len(trades),'pending_candidates':pending['candidates'],'status':'ready_next_session',
           'execution':'收盘后用已发生日线近似结算次日开盘，不是真实订单','audit':str(audit_path.relative_to(ROOT))}
    write(HERE/'tracker.json',state)
    write(HERE/'daily'/('run_'+asof+'.json'),{'tracker':state,'raw_input_hashes':rawhashes,'metadata_sha256':meta_hash,'source_hashes':hashes},True)
    print(json.dumps(state,ensure_ascii=False,default=str),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--date',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
    args=parser.parse_args()
    # Advisory OS lock is released by the OS even on crashes; no stale-file guessing.
    import msvcrt
    HERE.mkdir(exist_ok=True)
    with (HERE/'run.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try:main(args.date)
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
