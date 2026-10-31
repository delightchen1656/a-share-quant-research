"""Read-only localhost daily K-line viewer. No strategy imports or write APIs."""
from pathlib import Path
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
import argparse,hashlib,json,logging,threading
import numpy as np
import pandas as pd
from sse_data import history as sse_history

HERE=Path(__file__).resolve().parent
APP='hushen-basic-kline-viewer'
VERSION='1.6.0'
STATIC={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8'),'/gold':('gold.html','text/html; charset=utf-8'),'/gold.js':('gold.js','text/javascript; charset=utf-8')}
STATIC.update({'/sse':('sse.html','text/html; charset=utf-8'),'/sse.js':('sse.js','text/javascript; charset=utf-8'),'/sse.css':('sse.css','text/css; charset=utf-8')})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def scalar(v):
    if pd.isna(v):return None
    if isinstance(v,(np.integer,)):return int(v)
    if isinstance(v,(float,np.floating)):return float(v) if np.isfinite(v) else None
    return v

class Store:
    def __init__(self):
        self.data=HERE/'data';self.meta=json.loads((self.data/'MANIFEST.json').read_text(encoding='utf8'))
        assert self.meta['scope']=='SH_SZ_MAIN_BOARD_ONLY'
        path=self.data/self.meta.get('stocks_path','stocks.parquet');assert sha(path)==self.meta['stocks_sha256']
        u=pd.read_parquet(path);assert u.code.is_unique and u.code.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
        self.stocks=u.to_dict('records');self.names=u.set_index('code').to_dict('index')
        self.paths={x['code']:x for x in self.meta['files']};self.cache=OrderedDict();self.lock=threading.RLock()
        signalpath=self.data/self.meta.get('signals_path','signals.json')
        assert sha(signalpath)==self.meta['signals_sha256']
        self.signals=json.loads(signalpath.read_text(encoding='utf8'))
        assert self.signals['signal_cutoff']==self.meta['cutoff']
        assert self.signals['display_scope']=='historical_mainboard_full_history'
        assert {x['direction'] for x in self.signals['signals']}=={'d1'}
        assert all(x['code'] in self.names for x in self.signals['signals'])
    def stock(self,code):
        if code not in self.names:raise KeyError('股票不在沪深主板快照内')
        with self.lock:
            if code in self.cache:self.cache.move_to_end(code);return self.cache[code]
        item=self.paths[code];p=(self.data/item['path']).resolve()
        assert p.is_relative_to(self.data.resolve()) and sha(p)==item['sha256']
        z=pd.read_parquet(p);z['date']=pd.to_datetime(z.date)
        for c in ['open','high','low','close','volume','amount','tradestatus']:z[c]=pd.to_numeric(z[c],errors='coerce')
        assert not z.date.duplicated().any() and z.date.max()<=pd.Timestamp(self.meta['cutoff'])
        good=z.tradestatus.eq(1)&z.volume.gt(0)&z[['open','high','low','close']].gt(0).all(axis=1)&np.isfinite(z[['open','high','low','close']]).all(axis=1)
        bars=z.loc[good].sort_values('date').copy()
        if bars.empty:raise ValueError('这只股票没有可展示的成交日线')
        for n in [5,10,20,60]:bars[f'ma{n}']=bars.close.rolling(n,min_periods=n).mean()
        bars['change']=bars.close.pct_change();bars['volume_hands']=bars.volume/100
        fields=['open','high','low','close','volume_hands','amount','change','ma5','ma10','ma20','ma60']
        rows=[[r.date.strftime('%Y-%m-%d')]+[scalar(getattr(r,c)) for c in fields] for r in bars.itertuples()]
        result=dict(code=code,**self.names[code],bars=rows,fields=['date']+fields,price_basis='前复权',volume_unit='手',cutoff=self.meta['cutoff'],first=rows[0][0],last=rows[-1][0],omitted_sessions=int((~good).sum()))
        with self.lock:
            self.cache[code]=result
            while len(self.cache)>48:self.cache.popitem(last=False)
        return result

def gold_history():
    root=HERE.parent/'K线数据/黄金';pointer=root/'CURRENT.json'
    if not pointer.exists():raise ValueError('伦敦金数据尚未准备完成，请稍后刷新')
    current=json.loads(pointer.read_text(encoding='utf8'));manifest=(root/current['manifest']).resolve()
    assert manifest.is_relative_to(root.resolve()) and sha(manifest)==current['sha256']
    meta=json.loads(manifest.read_text(encoding='utf8'));path=(root/meta['data_path']).resolve()
    assert path.is_relative_to(root.resolve()) and sha(path)==meta['data_sha256']
    frame=pd.read_parquet(path);fields=['open','high','low','close']
    rows=[[r.date]+[scalar(getattr(r,c))for c in fields]+[None,None,scalar(r.change)]+[scalar(getattr(r,'ma'+str(n)))for n in [5,10,20,60]]+[getattr(r,'source','HistData BID')]for r in frame.itertuples()]
    return dict(code='XAUUSD',name='伦敦金现货',is_leader=False,bars=rows,fields=['date']+fields+['volume_unavailable','amount_unavailable','change','ma5','ma10','ma20','ma60','source'],first=meta['first'],last=meta['last'],cutoff=meta['last'],price_basis='现货 · USD/盎司',metadata=meta)

class Handler(BaseHTTPRequestHandler):
    store=None
    def send(self,status,body,ctype='application/json; charset=utf-8'):
        if isinstance(body,(dict,list)):body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf8')
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
    def do_GET(self):
        u=urlparse(self.path)
        try:
            if u.path in STATIC:
                file,ctype=STATIC[u.path];return self.send(200,(HERE/'web'/file).read_bytes(),ctype)
            if u.path=='/api/health':return self.send(200,dict(app=APP,version=VERSION,cutoff=self.store.meta['cutoff'],scope='SH_SZ_MAIN_BOARD_ONLY',markets=['SH_SZ_MAIN_BOARD','XAUUSD_SPOT','SSE_INDEX_REGIMES']))
            if u.path=='/api/stocks':return self.send(200,dict(stocks=self.store.stocks,cutoff=self.store.meta['cutoff'],price_basis='前复权',leader_note=self.store.meta['leader_note'],total=len(self.store.stocks),automatic_refresh=False))
            if u.path=='/api/history':return self.send(200,self.store.stock(parse_qs(u.query).get('code',[''])[0]))
            if u.path=='/api/signals':return self.send(200,{k:v for k,v in self.store.signals.items() if k!='sources'})
            if u.path=='/api/gold/history':return self.send(200,gold_history())
            if u.path=='/api/sse/history':return self.send(200,sse_history())
            return self.send(404,dict(error='基础看盘版没有此功能'))
        except KeyError as e:self.send(404,dict(error=str(e)))
        except ValueError as e:self.send(400,dict(error=str(e)))
        except Exception:logging.exception('Viewer read failed');self.send(500,dict(error='行情读取校验失败，请查看软件日志'))
    def log_message(self,fmt,*args):logging.info(fmt,*args)
def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8766);a=p.parse_args()
    (HERE/'runtime').mkdir(exist_ok=True)
    logging.basicConfig(filename=HERE/'runtime/viewer.log',level=logging.INFO,encoding='utf8',format='%(asctime)s %(message)s')
    Handler.store=Store();server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler)
    print('沪深基础看盘：http://127.0.0.1:'+str(a.port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
