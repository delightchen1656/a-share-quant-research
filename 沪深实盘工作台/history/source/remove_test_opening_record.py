"""Explicit removal of one user-identified test opening-cash event, backed up."""
import argparse
import json
from datetime import timedelta
from pathlib import Path
from store import Ledger, now


def remove(folder, expected_cash):
    ledger=Ledger(Path(folder)/'ledger.sqlite3')
    backup=ledger.backup()
    with ledger.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        events=[dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
        target=next((e for e in events if e['id']==1),None)
        if not target or target['kind']!='cash_adjust' or target['voided'] or target['data'].get('source')!='account_reset_opening_cash' or target['data']['amount']!=-94320.04:
            raise ValueError('目标不是用户指定的测试记录，未删除')
        if any(e['kind']=='classify_cash' and e['data'].get('event_id')==1 for e in events):
            raise ValueError('目标已有分类依赖，停止并重新核对')
        before=ledger.state(events=events)
        if abs(before['cash']-expected_cash)>.005:raise ValueError('现金已变化，未删除')
        remaining=[e for e in events if e['id']!=1]
        after=ledger.state(events=remaining)
        assert after['cash']==round(before['cash']+94320.04,2)
        for key in ['positions','orders','all_orders','realized','deferred','occupied','free_slots']:
            assert before[key]==after[key],key
        cursor=db.execute("DELETE FROM events WHERE id=? AND kind='cash_adjust' AND payload=?",(1,target['payload']))
        assert cursor.rowcount==1
        clock=now();cycle=clock.date()
        if (clock.hour,clock.minute)<(9,30):cycle-=timedelta(days=1)
        # The former cash confirmation cannot authorize recommendations at the
        # new cash balance. Keep all previous-day records and equity snapshots.
        db.execute('DELETE FROM confirmations WHERE day=?',(cycle.isoformat(),))
    assert ledger.events()==remaining
    receipt=dict(status='removed',at=now().isoformat(),removed_event=target,backup=str(backup),
        cash_before=before['cash'],cash_after=after['cash'],other_events_unchanged=True,
        positions_and_orders_unchanged=True,realized_pnl_unchanged=True,
        cash_impact_explicitly_disclosed_and_user_confirmed=True,requires_cash_review=True,
        historical_observations_preserved=True)
    destination=Path(folder)/'backups'/f"remove_test_opening_{now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    destination.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(status='removed',cash_before=before['cash'],cash_after=after['cash'],backup=str(backup),receipt=str(destination)),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',required=True,action='store_true');parser.add_argument('--expected-cash',required=True,type=float)
    args=parser.parse_args();remove(Path(__file__).resolve().parent/'data',args.expected_cash)
