"""Local-only hindsight game. Read-only frozen inputs; no broker/production writes."""
from __future__ import annotations
import hashlib, importlib.util, json, math, secrets, sqlite3, sys, threading, uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent; ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file()); PORT=18763
SOURCE=HERE/'frozen_inputs/cases'
FROZEN_MARKET=HERE/'frozen_inputs/market'
FROZEN_RUNTIME=HERE/'runtime'
LABELS={'fail':'买入失败','take':'止盈','stop':'止损','expiry':'到期平仓'}
TOKEN=secrets.token_urlsafe(32)
def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,pd.Timestamp):return v.date().isoformat()
    if hasattr(v,'item'):return clean(v.item())
    if isinstance(v,float) and not math.isfinite(v):return None
    return v
def dumps(v):return json.dumps(clean(v),ensure_ascii=False,allow_nan=False)

class Game:
    def __init__(self,folder=HERE/'data'):
        self.folder=Path(folder);self.folder.mkdir(exist_ok=True);self.lock=threading.RLock();self.loaded=False
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY,mode TEXT NOT NULL,payload TEXT NOT NULL,answer TEXT,at TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY,card TEXT UNIQUE,at TEXT,choice TEXT,reason TEXT,ret REAL,nav REAL)')
    def db(self):
        db=sqlite3.connect(self.folder/'practice.sqlite3',timeout=30);db.row_factory=sqlite3.Row;return db
    def load(self):
        if self.loaded:return
        import pickle
        identity=json.loads((SOURCE/'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
        assert json.loads((SOURCE/'INDEPENDENT_VERIFICATION.json').read_text())['status']=='passed'
        market_manifest=FROZEN_MARKET/'DOWNLOAD_COMPLETE.json'
        assert hashlib.sha256(market_manifest.read_bytes()).hexdigest()==identity['data_manifest_sha256']
        p=SOURCE/'INPUT_SIGNALS.parquet'
        assert hashlib.sha256(p.read_bytes()).hexdigest()==identity['signals_sha256']
        with (SOURCE/'INPUT_PACK.pkl').open('rb') as f:self.pack=pickle.load(f)
        self.signals=pd.read_parquet(p).reset_index(drop=True)
        assert self.signals.atr_pct.ge(.025).all() and self.signals.groupby('date').size().le(3).all()
        self.data=FROZEN_MARKET;self.end=pd.Timestamp(identity['end'])
        sys.path.insert(0,str(FROZEN_RUNTIME))
        from baseline_fixed_ioc import fixed_ioc_engine
        old=FROZEN_RUNTIME/'run_batch.py'
        spec=importlib.util.spec_from_file_location('practice_frozen_core',old);core=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=core;spec.loader.exec_module(core)
        # Exactly the historical baseline's expiry-close, not software manual-open.
        self.engine=fixed_ioc_engine(core,manual_expiry_open=False,filled_slots=False)
        self.names=pd.read_csv(ROOT/'K线数据/沪深/metadata/historical_mainboard_universe.csv',dtype=str).set_index('symbol').code_name.to_dict()
        self.bar_cache={};self.loaded=True
    def case(self,index):
        row=self.signals.iloc[index];day=pd.Timestamp(row.date);symbol=row.symbol
        core=self.engine;core.EVAL_START=day;core.HARD_MAX_DATE=self.end;core.LAST_SIGNAL_DATE=day;core.YEARS=list(range(day.year,self.end.year+1))
        cal=[d for d in self.pack['calendar'] if day<=d<=self.end];gaps=set()
        result,trades=core.simulate(self.signals.iloc[[index]],{symbol:self.pack['bars'][symbol]},cal,
            'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,slots=5,
            actions=self.pack['actions'],known_action_keys=self.pack['known'],coverage_sink=gaps,delist_dates=self.pack['delists'])
        if gaps or result['open_positions_at_end'] or result['pending_orders_at_end'] or result['unpaid_receivables']:return None
        if trades.empty:
            if not result['pending_orders_created']:return None
            result_day=min(self.end,day+pd.Timedelta(days=8))
            if result['fixed_order_attempts']:result_day=pd.Timestamp(result['fixed_order_attempts'][-1]['date'])
            trade=None;reason='fail';ret=0.
        else:
            trade=clean(trades.iloc[0].to_dict());reason=trade['reason'];ret=trade['return'];result_day=pd.Timestamp(trade['exit_date'])
            if reason not in LABELS:return None
        return clean(dict(symbol=symbol,name=self.names.get(symbol,symbol),day=day,atr=row.atr_pct,trigger=row.close,
            score=row.score,reason=reason,ret=ret,trade=trade,result_day=result_day,
            failure_details={k:result[k] for k in ['expired_entry_orders','capacity_limited_orders','below_100_share_orders','cash_limited_orders']},
            attempts=result['fixed_order_attempts']))
    def candles(self,case,revealed=False):
        symbol=case['symbol'];day=pd.Timestamp(case['day'])
        nextday=next(d for d in self.pack['calendar'] if d>day)
        start=pd.Timestamp(case['trade']['entry_date']) if revealed and case['trade'] else nextday
        deadline=start+pd.Timedelta(days=30)
        # A take/stop ends the trade, NOT the chart's observation window.
        end=min(self.end,max(deadline,pd.Timestamp(case['result_day']))) if revealed else day
        if symbol not in self.bar_cache:
            paths={kind:self.data/'staging'/kind/symbol[-2:]/(symbol+'.parquet') for kind in ['raw','qfq']}
            q=pd.read_parquet(paths['qfq']);r=pd.read_parquet(paths['raw'])
            for frame in [q,r]:
                frame['date']=pd.to_datetime(frame.date)
                for c in ['open','high','low','close','volume','tradestatus']:frame[c]=pd.to_numeric(frame[c],errors='coerce')
            self.bar_cache[symbol]=(q,r)
        q,r=self.bar_cache[symbol];signal=q.loc[q.date.eq(day)].iloc[0];scale=case['trigger']/float(signal.close)
        q=q.loc[q.date.between(day-pd.DateOffset(years=1),end)&q.tradestatus.eq(1)].copy()
        q=q.merge(r[['date','volume']],on='date',suffixes=('','_raw'),validate='one_to_one')
        bars=[]
        for b in q.itertuples():
            values=[float(getattr(b,k))*scale for k in ['open','high','low','close']]
            if all(math.isfinite(x) and x>0 for x in values):bars.append(dict(time=b.date.date().isoformat(),open=values[0],high=values[1],low=values[2],close=values[3],volume=float(b.volume_raw) if pd.notna(b.volume_raw) else 0.))
        anchor=case['trigger']*1.002;deadline=nextday+pd.Timedelta(days=30);start=nextday;actual=False
        if revealed and case['trade']:
            t=case['trade'];start=pd.Timestamp(t['entry_date']);deadline=start+pd.Timedelta(days=30)
            q_all,r_all=self.bar_cache[symbol]
            factor=float(q_all.loc[q_all.date.eq(start),'close'].iloc[0])*scale/float(r_all.loc[r_all.date.eq(start),'close'].iloc[0])
            anchor=t['entry_price']*factor;actual=True
        # Only session DATES may reach beyond the question; no future OHLC/volume.
        axis_sessions=[d for d in self.pack['calendar'] if day-pd.DateOffset(years=1)<=d<=max(deadline,end)+pd.Timedelta(days=12)]
        return clean(dict(bars=bars,axis_sessions=axis_sessions,display_end=end,window_complete=deadline<=self.end,
            levels=dict(entry=anchor,take=anchor*(1+4*case['atr']),stop=anchor*(1-1.5*case['atr']),start=start,deadline=deadline,actual=actual)))
    def public(self,id,case,revealed=False):
        # Today's ST/renamed label can itself reveal a historical outcome.
        out=dict(id=id,symbol=case['symbol'],name=case['name'] if revealed else '历史信号',day=case['day'],atr=case['atr'],trigger=case['trigger'],revealed=revealed,**self.candles(case,revealed))
        if revealed:out.update(result=case)
        return out
    def next(self,mode):
        if mode not in ['guess','trade']:raise ValueError('未知练习模式')
        self.load()
        with self.db() as db:
            # Resume an unanswered round; refresh/duplicate clicks cannot change the question.
            old=db.execute('SELECT * FROM cards WHERE mode=? AND answer IS NULL ORDER BY rowid DESC LIMIT 1',(mode,)).fetchone()
            if old:return self.public(old['id'],json.loads(old['payload']))
            used={json.loads(r['payload'])['day']+'_'+json.loads(r['payload'])['symbol'] for r in db.execute('SELECT payload FROM cards WHERE mode=?',(mode,))}
        indices=[i for i,r in enumerate(self.signals.itertuples()) if str(r.date.date())+'_'+r.symbol not in used]
        secrets.SystemRandom().shuffle(indices)
        for index in indices:
            case=self.case(index)
            if case:
                id=uuid.uuid4().hex
                with self.db() as db:db.execute('INSERT INTO cards(id,mode,payload) VALUES(?,?,?)',(id,mode,dumps(case)))
                return self.public(id,case)
        raise ValueError('可结算题目已练完；未平仓、公司行动覆盖不全的案例不会作为题目')
    def answer(self,id,choice):
        with self.db() as db:
            row=db.execute('SELECT * FROM cards WHERE id=?',(id,)).fetchone()
            if not row:raise ValueError('题目不存在')
            if row['answer'] is not None:raise ValueError('本题已结算，请抽下一题')
            allowed=LABELS if row['mode']=='guess' else {'buy':'买入','skip':'跳过'}
            if choice not in allowed:raise ValueError('选择不合法')
            case=json.loads(row['payload']);stamp=datetime.now().isoformat()
            db.execute('UPDATE cards SET answer=?,at=? WHERE id=? AND answer IS NULL',(choice,stamp,id))
            if row['mode']=='trade':
                previous=db.execute('SELECT nav FROM journal ORDER BY id DESC LIMIT 1').fetchone()
                nav=float(previous['nav']) if previous else 1.;ret=case['ret'] if choice=='buy' else 0.
                db.execute('INSERT INTO journal(card,at,choice,reason,ret,nav) VALUES(?,?,?,?,?,?)',(id,stamp,choice,case['reason'],ret,nav*(1+ret)))
        out=self.public(id,case,True);out['correct']=choice==case['reason'] if row['mode']=='guess' else None
        return dict(case=out,stats=self.stats())
    def stats(self):
        with self.db() as db:
            rows=db.execute("SELECT payload,answer FROM cards WHERE mode='guess' AND answer IS NOT NULL").fetchall()
            journal=[dict(r) for r in db.execute('SELECT id,at,choice,reason,ret,nav FROM journal ORDER BY id')]
        counts={k:dict(total=0,correct=0) for k in LABELS}
        for r in rows:
            reason=json.loads(r['payload'])['reason'];counts[reason]['total']+=1;counts[reason]['correct']+=r['answer']==reason
        return dict(counts=counts,total=len(rows),correct=sum(x['correct'] for x in counts.values()),journal=journal,nav=journal[-1]['nav'] if journal else 1.)

GAME=Game()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,status,data,ctype='application/json; charset=utf-8'):
        body=(dumps(data) if not isinstance(data,(str,bytes)) else data);body=body.encode('utf-8') if isinstance(body,str) else body
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def valid_host(self):return self.headers.get('Host') in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']
    def do_GET(self):
        if not self.valid_host():return self.send(403,{'error':'仅允许本机访问'})
        if self.path=='/api/stats':return self.send(200,GAME.stats())
        if self.path=='/':return self.send(200,(HERE/'dist/index.html').read_text(encoding='utf-8').replace('__TOKEN__',TOKEN),'text/html; charset=utf-8')
        if self.path in ['/app.js','/style.css']:
            return self.send(200,(HERE/'dist'/self.path[1:]).read_bytes(),'text/javascript; charset=utf-8' if self.path.endswith('.js') else 'text/css; charset=utf-8')
        self.send(404,{'error':'不存在'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Practice-Token')!=TOKEN:return self.send(403,{'error':'请求校验失败，请刷新'})
        try:
            n=int(self.headers.get('Content-Length',0))
            if n>4096:raise ValueError('请求过大')
            d=json.loads(self.rfile.read(n))
            with GAME.lock:
                if self.path=='/api/next':out=GAME.next(d['mode'])
                elif self.path=='/api/answer':out=GAME.answer(d['id'],d['choice'])
                else:raise ValueError('接口不存在')
            self.send(200,out)
        except Exception as e:self.send(400,{'error':str(e)})
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path);parser.add_argument('--port',type=int,default=PORT);args=parser.parse_args()
    PORT=args.port
    if args.data_dir:GAME=Game(args.data_dir)
    print(f'沪深2 K线练习 http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
