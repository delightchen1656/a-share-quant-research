"""Isolated UI QA on port 18763. Synthetic data; never opens production DB."""
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from http.server import ThreadingHTTPServer
import pandas as pd
import app
import market
from service import Tracker


def main():
    with tempfile.TemporaryDirectory(prefix='hushen2_tracking_qa_') as tmp:
        root=Path(tmp);(root/'raw/SH').mkdir(parents=True)
        pd.DataFrame(dict(date=pd.to_datetime(['2026-10-19','2026-10-20','2026-10-21']),close=[10.3,10.1,10])).to_parquet(root/'raw/SH/600000.SH.parquet')
        tracker=Tracker(root)
        def append(day,kind,data,equity):
            at=datetime.fromisoformat(day+'T20:00:00').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            with patch('store.now',return_value=at):
                tracker.ledger.append(kind,data)
                tracker.ledger.observe(day+kind,day,kind,equity,equity)
        append('2026-10-19','cash_adjust',dict(amount=-90000,date='2026-10-19',flow_type='external',note='仅测试：取款'),10000)
        tracker.ledger.append('accept',dict(signal_id='test-order',symbol='600000.SH',name='界面测试股票',signal_date='2026-10-16',atr=.03,trigger=10.,quantity=100))
        append('2026-10-19','buy',dict(order_id='test-order',date='2026-10-19',quantity=100,price=10,fee=5),10025)
        append('2026-10-20','sell',dict(symbol='600000.SH',date='2026-10-20',quantity=100,price=10.1,fee=5),10000)
        append('2026-10-21','cash_adjust',dict(amount=-10,date='2026-10-21',flow_type='reconciliation',note='仅测试：费用差额'),9990)
        tracker.info=dict(status='awaiting_review',market_date='2026-10-21',signals=[],prepared=True,
                          message='隔离界面测试：不连接真实账户',signal_filter_policy=market.SIGNAL_FILTER_POLICY_ID)
        app.PORT=18763;app.tracker=tracker
        def update(background=True):
            tracker.info.update(status='ready',signals=[dict(id='test-signal',symbol='600000.SH',name='仅测试 · 示例',rank=1,
                signal_date='2026-10-21',valid_from='2026-10-22',trigger=10,atr=.03,score=.5)])
        tracker.update=update
        with patch('service.market.DATA',root),patch('service.market.calendar_extended',return_value=['2026-10-16','2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-11-18']),patch('service.market.raw_marks',return_value={}):
            print('ISOLATED TEST ONLY http://127.0.0.1:18763/',flush=True)
            with ThreadingHTTPServer(('127.0.0.1',18763),app.Handler) as server:
                try:server.serve_forever()
                except KeyboardInterrupt:pass


if __name__=='__main__':main()
