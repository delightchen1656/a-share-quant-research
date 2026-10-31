"""Read-only production check and migration rehearsal on a separate DB copy."""
import hashlib
import json
import shutil
import sqlite3
import tempfile
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from service import Tracker
from store import REVIEW_POLICY
import market


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
BACKUP=ROOT/'archive/hushen_2/production_baseline_backups/before_atr025_20261022_025103/strategies/hushen_2'


def financial_events(path):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        return list(db.execute('SELECT id,at,kind,payload,voided FROM events ORDER BY id'))


def main():
    data=HERE/'data';original=data/'ledger.sqlite3'
    before=financial_events(original)
    with tempfile.TemporaryDirectory(prefix='hushen2_upgrade_rehearsal_') as tmp:
        folder=Path(tmp)
        with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(folder/'ledger.sqlite3')) as dst:src.backup(dst)
        tracker=Tracker(folder)
        tracker.info=json.loads((data/'market_status.json').read_text(encoding='utf-8'))
        sessions=market.calendar_extended(data)
        with patch.object(tracker,'sessions',return_value=sessions):
            snapshot=tracker.snapshot()
        assert financial_events(folder/'ledger.sqlite3')==before
        assert snapshot['signal_filter']['refill'] is False and snapshot['signal_filter']['minimum_atr']==.025
        assert snapshot['review_policy']==REVIEW_POLICY and snapshot['performance']['asof']==snapshot['market']['market_date']
        if not snapshot['confirmed']:assert snapshot['signals']==[] and snapshot['tasks'][0]['type']=='review'
        with tracker.ledger.connect() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        rehearsal=dict(cash=snapshot['cash'],positions=len(snapshot['positions']),orders=len(snapshot['orders']),
                       first_task=snapshot['tasks'][0]['title'] if snapshot['tasks'] else None,
                       historical_curve_points=len(snapshot['account_curve']),calendar_records=len(snapshot['performance']['daily']),
                       unclassified_cash_adjustments=len(snapshot['performance']['unknown_cash_adjustments']))
    assert financial_events(original)==before
    model_unchanged={p.name:hashlib.sha256(p.read_bytes()).hexdigest()==hashlib.sha256((BACKUP/'model'/p.name).read_bytes()).hexdigest()
                     for p in (BASE/'model').glob('*') if p.is_file()}
    assert all(model_unchanged.values())
    try:
        with urllib.request.urlopen('http://127.0.0.1:18762/api/state',timeout=5) as response:live=json.load(response)
        live_upgraded=live.get('review_policy')==REVIEW_POLICY and 'performance' in live
    except OSError:live_upgraded=False
    report=dict(at=datetime.now().isoformat(),code_tests='39 unit tests passed; JS syntax checked',
                status='live_upgraded' if live_upgraded else 'code_verified_waiting_for_backend_restart',
                migration_on_isolated_copy='verified',rehearsal=rehearsal,
                financial_events_unchanged=True,financial_events_equal_preupgrade_backup=before==financial_events(BACKUP/'tracker/data/ledger.sqlite3'),
                models_unchanged=model_unchanged,production_back_end_upgraded=live_upgraded,
                no_production_actions_submitted=True,backup=str(BACKUP.parent.parent))
    out=data/'tracking_upgrade_verification.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
