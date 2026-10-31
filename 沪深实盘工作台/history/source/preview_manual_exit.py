"""Read-only local UI fixture. Synthetic account exists only in a temporary directory."""
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from service import Tracker
from test_manual_exit import SESSIONS
import app


def main():
    clock=datetime(2026,10,16,20,tzinfo=ZoneInfo('Asia/Shanghai'))
    with tempfile.TemporaryDirectory(prefix='hushen2_manual_exit_ui_') as folder:
        tracker=Tracker(folder)
        tracker.ledger.append('accept',dict(signal_id='preview_only',symbol='600000.SH',name='示例持仓（界面测试）',signal_date='2026-09-15',atr=.024,trigger=10.,quantity=1900))
        tracker.ledger.append('buy',dict(order_id='preview_only',date='2026-09-16',quantity=1900,price=10.,fee=5.7))
        tracker.ledger.append('protection',dict(symbol='600000.SH'))
        tracker.info=dict(status='ready',market_date='2026-10-16',message='只读界面测试，不是真实账户',signals=[])
        app.PORT=18763;app.tracker=tracker
        class ReadOnlyHandler(app.Handler):
            def do_POST(self):self.send(403,'{"error":"只读界面测试，禁止写入"}')
        with patch('service.now',return_value=clock),patch('store.now',return_value=clock),patch('service.market.calendar_extended',return_value=SESSIONS),patch('service.market.raw_marks',return_value={}):
            server=ThreadingHTTPServer(('127.0.0.1',18763),ReadOnlyHandler)
            print('Read-only synthetic UI preview http://127.0.0.1:18763/',flush=True)
            server.serve_forever()


if __name__=='__main__':main()
