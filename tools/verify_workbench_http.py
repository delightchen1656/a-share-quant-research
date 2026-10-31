"""Serve copies of both private ledgers; exercise GET APIs without updates."""
from pathlib import Path
import hashlib,json,shutil,sqlite3,sys,tempfile,threading,urllib.request,gc
from contextlib import closing
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'沪深实盘工作台/tracker'
OUT=ROOT/'project_memory/holdout_restricted/layout_20261031/validation'
sys.path.insert(0,str(BASE))
import app

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    originals=[BASE/'data/ledger.sqlite3',BASE/'hushen1_data/ledger.sqlite3']
    before={str(p):sha(p)for p in originals}
    with tempfile.TemporaryDirectory(prefix='quant-layout-http-')as tmp:
        root=Path(tmp)
        for name in ['data','hushen1_data']:
            src=BASE/name;dest=root/name;dest.mkdir()
            for p in src.glob('*.json'):shutil.copy2(p,dest/p.name)
            if (src/'signals').is_dir():shutil.copytree(src/'signals',dest/'signals')
            with closing(sqlite3.connect((src/'ledger.sqlite3').as_uri()+'?mode=ro',uri=True))as db,closing(sqlite3.connect(dest/'ledger.sqlite3'))as output:db.backup(output)
        app.tracker=app.Tracker(root/'data');app.hushen1=app.Hushen1Desk(root/'hushen1_data')
        server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler);app.PORT=server.server_address[1]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();checks={}
        try:
            for route in ['/','/hushen1','/api/state','/api/hushen1/state','/tracking.js','/hushen1_tracking.js','/daily_orders.js']:
                with urllib.request.urlopen(f'http://127.0.0.1:{app.PORT}'+route,timeout=45)as response:
                    payload=response.read();assert response.status==200 and payload;checks[route]=True
        finally:server.shutdown();server.server_close();thread.join()
        app.tracker=None;app.hushen1=None;gc.collect()
    assert all(sha(Path(p))==h for p,h in before.items())
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'workbench_http.json').write_text(json.dumps(dict(checks=checks,original_ledgers_unchanged=True,updates_invoked=False),indent=2),encoding='utf8')
    print('Workbench HTTP PASS',len(checks),'routes; original ledgers unchanged')

if __name__=='__main__':main()
