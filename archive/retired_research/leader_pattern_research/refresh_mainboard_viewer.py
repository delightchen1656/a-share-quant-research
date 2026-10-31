"""19:00 read-only follow-up to the existing18:30 quote updater; atomic viewer publication."""
from pathlib import Path
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import argparse,datetime,json,hashlib,os,subprocess,sys,time,shutil
import pandas as pd
from collect_market_wide import freeze
from build_market_patterns import build
from leader_pool import load_pool,membership

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
AREA=HERE/'market_wide/holdout_restricted';CURRENT=AREA/'CURRENT.json';STATUS=AREA/'REFRESH_STATUS.json'
SCOPE=r'^(600|601|603|605|000|001|002|003)\d{3}$'
META=ROOT/'sh_sz_market_research/data_pipeline/data/metadata'
TZ=datetime.timezone(datetime.timedelta(hours=8))
RETRY_SECONDS=2*60*60
def now():return datetime.datetime.now(TZ)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp')
    t.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');t.replace(p)
def record(status,target,message,**extra):
    result=dict(status=status,target=target,message=message,checked_at=now().isoformat(),scope='SH_SZ_MAIN_BOARD_ONLY',**extra)
    dump(STATUS,result);return result

@contextmanager
def lock(name):
    AREA.mkdir(parents=True,exist_ok=True);f=(AREA/name).open('a+b');f.seek(0,2)
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise RuntimeError('Another viewer refresh is already running')
    try:yield
    finally:
        f.seek(0)
        if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()

def updating():
    command="@(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*daily_market_update.py*' }).Count"
    r=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if r.returncode:raise RuntimeError('Cannot verify whether protected market updater is active')
    return int(r.stdout.strip() or '0')>0

def trading_day(target):
    p=META/f'trade_calendar_{target.replace("-","")}.csv'
    if p.exists():
        c=pd.read_csv(p,dtype=str);row=c[c.calendar_date.eq(target)]
        if len(row):return row.is_trading_day.iloc[0]=='1'
    # Verified exchange calendar; never use a generic workday/holiday guess.
    year=target[:4];source=HERE/f'exchange_calendars/{year}.json'
    if not source.exists():return None
    j=json.loads(source.read_text(encoding='utf-8'));date=pd.Timestamp(target)
    return bool(date.weekday()<5 and target not in j['closed_dates'])

def once(target):
    with lock('REFRESH.lock'):
        if trading_day(target) is False:return record('non_trading_day',target,'正式交易日历为休市日，保留最近已验证行情。')
        audit=ROOT/'data_updates'/target.replace('-','')/'audit.json'
        if not audit.exists():return record('waiting_for_market_commit',target,'等待18:30行情任务成功提交。')
        a=json.loads(audit.read_text(encoding='utf-8'))
        if a.get('status')!='ok' or a.get('target')!=target:return record('waiting_for_market_commit',target,'当日日线审计尚未确认成功。')
        if updating():return record('waiting_for_market_commit',target,'行情更新仍在运行，等待完成后读取。')
        refresh=META/f'refresh_{target.replace("-","")}.json';calendar=META/f'trade_calendar_{target.replace("-","")}.csv'
        if not refresh.exists() or not calendar.exists():raise RuntimeError('Successful quote metadata/calendar is missing')
        assert json.loads(refresh.read_text(encoding='utf-8'))['status']=='ok'
        audit_hash=sha(audit)
        previous=json.loads(CURRENT.read_text(encoding='utf-8'))
        if previous['cutoff']==target:return record('already_current',target,'软件已使用当日校验完成的主板行情。',generation=previous['generation'])
        if previous['cutoff']>target:raise RuntimeError('Refusing to roll viewer data back')
        run=AREA/'mainboard_runs'/target.replace('-','');data=run/'inputs_daily';data.mkdir(parents=True,exist_ok=True)
        metadata=pd.read_csv(META/'historical_mainboard_universe.csv',dtype=str,keep_default_na=False)
        metadata['number']=metadata.code.str.split('.').str[-1]
        metadata=metadata[metadata.number.str.match(SCOPE)]
        current=metadata[metadata.status.eq('1')&((metadata.ipoDate=='')|(metadata.ipoDate<=target))]
        old=pd.read_parquet(previous['universe']).set_index('code')
        leader_frame,leader_manifest=load_pool()
        leader_lookup=leader_frame.set_index('code').to_dict('index')
        code_set=set(old.index)|set(current.number) # preserve history, append newly listed stocks
        lookup=metadata.set_index('number').to_dict('index');stocks=[];tasks=[]
        for code in sorted(code_set):
            info=lookup.get(code);name=info['code_name'] if info else old.loc[code,'name']
            stocks.append(dict(code=code,name=name,symbol=code+('.SH' if code.startswith('6') else '.SZ'),board='主板',**membership(code,leader_lookup)))
            for mode in ['raw','qfq']:
                p=ROOT/'sh_sz_market_research/data_pipeline/data'/mode/('SH' if code.startswith('6') else 'SZ')/(code+('.SH' if code.startswith('6') else '.SZ')+'.parquet')
                if not p.exists():raise RuntimeError(f'Protected main-board quote missing:{code}/{mode}')
                tasks.append((code,mode,p,'Protected_committed_mainboard_readonly',target))
        u=pd.DataFrame(stocks);assert u.code.str.match(SCOPE).all();u.to_parquet(run/'universe.parquet',index=False)
        c=pd.read_csv(calendar);dates=pd.to_datetime(c.loc[c.is_trading_day.astype(str).eq('1'),'calendar_date'])
        pd.DataFrame({'date':dates[dates.between('2018-01-01',target)]}).to_csv(run/'exchange_sessions.csv',index=False)
        record('refreshing',target,'正在冻结主板行情并重算结构。',stocks=len(u))
        # Reuse the validated snapshot routine with this run's destination, never touch quote originals.
        import collect_market_wide as collector
        collector.DATA=data
        for mode in ['raw','qfq']:(data/mode).mkdir(exist_ok=True)
        with ThreadPoolExecutor(max_workers=6) as pool:records=list(pool.map(freeze,tasks))
        assert sha(audit)==audit_hash and not updating(),'Market commit changed during snapshot preparation'
        dump(data/'manifest.json',dict(cutoff=target,scope='SH_SZ_MAIN_BOARD_ONLY',stocks=len(u),required_stocks=len(u),
            snapshots=len(records),files=records,all_protected_assets_readonly=True,protected_audit_sha256=audit_hash,universe_sha256=sha(run/'universe.parquet'),
            leader_pool_manifest=leader_manifest['path'],leader_pool_manifest_sha256=leader_manifest['sha256']))
        bundle=build(run,publish=True)
        return record('updated',target,'主板行情与箱体结构已完成校验，软件已切换至新版本。',generation=bundle['generation'],stocks=len(u))

def watch(target):
    with lock(f'WATCH_{target}.lock'):
        # Restarting a waiting worker preserves its next due time.
        if STATUS.exists():
            previous=json.loads(STATUS.read_text(encoding='utf-8'))
            if previous.get('target')==target and previous.get('status') in ['waiting_for_market_commit','failed']:
                due=datetime.datetime.fromisoformat(previous['checked_at'])+datetime.timedelta(seconds=RETRY_SECONDS)
                remaining=(due-now()).total_seconds()
                if remaining>0:
                    previous.update(retry_interval_hours=2,next_check_at=due.isoformat())
                    dump(STATUS,previous)
                    time.sleep(remaining)
        while True:
            # A newer validated publication also covers an older pending target.
            current=json.loads(CURRENT.read_text(encoding='utf-8'))
            if current.get('status')=='ok' and current['cutoff']>=target:
                return record('already_current',target,'软件已使用该日或更新的已验证主板行情。',generation=current['generation'])
            try:result=once(target)
            except Exception as exc:
                result=record('failed',target,str(exc))
            if result['status'] in ['updated','already_current','non_trading_day']:
                print(json.dumps(result,ensure_ascii=False),flush=True);return result
            due=now()+datetime.timedelta(seconds=RETRY_SECONDS)
            result.update(retry_interval_hours=2,next_check_at=due.isoformat())
            dump(STATUS,result);print(json.dumps(result,ensure_ascii=False),flush=True)
            time.sleep(RETRY_SECONDS) # background worker; no overnight cutoff

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--date',default=now().date().isoformat());parser.add_argument('--watch',action='store_true');parser.add_argument('--launch-watch',action='store_true');args=parser.parse_args()
    pd.Timestamp(args.date)
    if args.launch_watch:
        if now().hour<19:raise RuntimeError('Scheduled viewer detection starts at19:00Asia/Shanghai')
        log=AREA/'refresh_worker.log';AREA.mkdir(parents=True,exist_ok=True)
        with log.open('ab') as out:
            p=subprocess.Popen([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--date',args.date,'--watch'],
                cwd=str(ROOT),stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,close_fds=True)
        print(json.dumps(dict(status='watcher_launched',pid=p.pid,target=args.date),ensure_ascii=False));return
    try:
        result=watch(args.date) if args.watch else once(args.date)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    except Exception as exc:
        if isinstance(exc,RuntimeError) and str(exc)=='Another viewer refresh is already running':
            print(json.dumps(dict(status='already_running',target=args.date),ensure_ascii=False));return
        record('failed',args.date,str(exc));raise

if __name__=='__main__':main()
