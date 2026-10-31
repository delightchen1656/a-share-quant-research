"""Isolated UI fixture; no broker, no real ledger, no model predictions."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from tempfile import TemporaryDirectory
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'沪深实盘工作台/tracker'))
import app,service,store

clock=datetime(2026,10,26,20,tzinfo=ZoneInfo('Asia/Shanghai'))
sessions=['2026-10-22','2026-10-23','2026-10-26','2026-10-27','2026-11-20','2026-11-23','2026-11-24','2026-11-25','2026-11-26','2026-11-27']
service.now=lambda:clock
store.now=lambda:clock
service.market.calendar_extended=lambda folder:sessions
service.market.raw_marks=lambda symbols,day:{symbol:dict(date=day,price=4.5) for symbol in symbols}
service.tracking=lambda *args,**kwargs:dict(curve=[],daily=[],unknown_cash_adjustments=[],today='2026-10-26',asof='2026-10-26',calendar_sessions=sessions)

with TemporaryDirectory(prefix='hushen2_buy_workflow_qa_') as folder:
    tracker=service.Tracker(folder)
    for id,symbol,name,trigger,qty in [('test-a','600533.SH','隔离测试甲',2.05,700),('test-b','600405.SH','隔离测试乙',4.32,200)]:
        tracker.ledger.append('accept',dict(signal_id=id,symbol=symbol,name=name,signal_date='2026-10-23',atr=.03,trigger=trigger,quantity=qty))
    tracker.info=dict(status='ready',market_date='2026-10-26',signal_filter_policy=service.market.SIGNAL_FILTER_POLICY_ID,
        message='隔离测试账户，不是真实推荐',signals=[dict(id='test-next',symbol='600939.SH',name='隔离测试新推荐',rank=1,signal_date='2026-10-26',trigger=3.,atr=.03)])
    tracker.update=lambda background=True:None
    app.PORT=18764;app.tracker=tracker
    server=app.ThreadingHTTPServer(('127.0.0.1',app.PORT),app.Handler)
    print('ISOLATED_UI http://127.0.0.1:18764/ fixture only; NO production writes',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
