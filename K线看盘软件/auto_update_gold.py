"""One locked daily gold refresh, independent of all A-share jobs and models."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,subprocess,sys,os,msvcrt
import pandas as pd
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent/'K线数据/黄金'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');os.replace(tmp,p)
def verify():
    pointer=json.loads((ROOT/'CURRENT.json').read_text(encoding='utf8'));mp=(ROOT/pointer['manifest']).resolve();assert mp.is_relative_to(ROOT.resolve())and sha(mp)==pointer['sha256']
    meta=json.loads(mp.read_text(encoding='utf8'));p=(ROOT/meta['data_path']).resolve();assert p.is_relative_to(ROOT.resolve())and sha(p)==meta['data_sha256']
    z=pd.read_parquet(p);assert z.date.is_unique and z.date.is_monotonic_increasing and len(z)==meta['bars'] and z.date.max()==meta['last']
    assert np.isfinite(z[['open','high','low','close']]).all().all()and z[['open','high','low','close']].gt(0).all().all()
    assert(z.high>=z[['open','close','low']].max(axis=1)).all()and(z.low<=z[['open','close','high']].min(axis=1)).all()
    assert meta['timezone']=='Europe/London' and meta['current_day_excluded']is True
    assert z.date.max()<pd.Timestamp.now(tz='Europe/London').strftime('%Y-%m-%d')
    for n in [5,10,20,60]:assert abs(float(z['ma'+str(n)].iloc[-1])-float(z.close.tail(n).mean()))<1e-8
    return meta
def main():
    ROOT.mkdir(exist_ok=True);logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    today=pd.Timestamp.now(tz='Europe/London').strftime('%Y-%m-%d');started=datetime.now(timezone.utc).isoformat();log=logs/(today+'.log')
    with (ROOT/'refresh.lock').open('a+b')as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:print(json.dumps(dict(status='already_running',notification_needed=False)));return 0
        previous=(ROOT/'CURRENT.json').read_bytes();committed=None
        try:
            old=verify()
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(HERE/'refresh_gold_recent.py')],cwd=str(HERE.parent),capture_output=True,text=True,encoding='utf8',timeout=180)
            with log.open('a',encoding='utf8')as f:f.write('\n'+started+'\n'+result.stdout+'\n'+result.stderr+'\n')
            if result.returncode:raise RuntimeError('黄金更新未通过；详见当日日志：'+result.stderr.strip()[-1200:])
            committed=sha(ROOT/'CURRENT.json');meta=verify();lines=[s for s in result.stdout.splitlines()if s.startswith('{')];out=json.loads(lines[-1])if lines else {}
            if out.get('rejected_UTC_days'):raise RuntimeError('存在UTC日线与伦敦午夜不吻合的新日期，需要合法盘中数据源重聚合；已保留旧版。')
            state=dict(status='updated'if meta['last']>old['last']else'no_change',started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),london_date=today,timezone='Europe/London',last_complete_date=meta['last'],previous_last=old['last'],bars=meta['bars'],manifest=str((ROOT/json.loads((ROOT/'CURRENT.json').read_text())['manifest']).resolve()),log_path=str(log.resolve()),notification_needed=False,read_only_stocks_and_strategies=True)
            save(ROOT/'REFRESH_STATUS.json',state);print(json.dumps(state,ensure_ascii=False));return 0
        except Exception as ex:
            if committed and sha(ROOT/'CURRENT.json')==committed:
                temp=ROOT/'CURRENT.rollback.tmp';temp.write_bytes(previous);os.replace(temp,ROOT/'CURRENT.json')
            state=dict(status='failed',started_at=started,finished_at=datetime.now(timezone.utc).isoformat(),london_date=today,error=str(ex),previous_snapshot_retained=True,notification_needed=True,log_path=str(log.resolve()))
            save(ROOT/'REFRESH_STATUS.json',state)
            with log.open('a',encoding='utf8')as f:f.write(json.dumps(state,ensure_ascii=False)+'\n')
            print(json.dumps(state,ensure_ascii=False));return 1
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':raise SystemExit(main())
