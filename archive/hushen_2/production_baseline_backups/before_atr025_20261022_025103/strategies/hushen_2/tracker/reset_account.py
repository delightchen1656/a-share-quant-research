"""Explicit, backed-up local account reset. Never touches a broker or market inputs."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
from store import Ledger,now

HERE=Path(__file__).resolve().parent


def event_digest(events):
    return hashlib.sha256(json.dumps(events,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def reset_account(folder,expected_cash):
    folder=Path(folder).resolve()
    ledger=Ledger(folder/'ledger.sqlite3')
    events=ledger.events();before=ledger.state(events=events)
    preserved=round(before['cash']+before['deferred'],2)
    if abs(preserved-expected_cash)>.005:raise ValueError('现金已变化，停止重置并重新核对')
    backup=ledger.backup()
    stamp=now().strftime('%Y%m%d_%H%M%S_%f')
    metadata=folder/'backups'/f'reset_{stamp}'
    metadata.mkdir(parents=True,exist_ok=False)
    with ledger.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=[dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
        if event_digest(current)!=event_digest(events):raise ValueError('记录已变化，停止重置')
        db.execute('DELETE FROM confirmations')
        db.execute('DELETE FROM events')
        if preserved!=100000.:
            payload=dict(amount=round(preserved-100000.,2),note='重置后保留的期初现金；非交易损益',
                         source='account_reset_opening_cash',date=now().date().isoformat(),opening_cash=preserved)
            db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',
                       (now().isoformat(),'cash_adjust',json.dumps(payload,ensure_ascii=False)))
    moved=[]
    for path in folder.glob('finished_*.json'):
        assert path.resolve().parent==folder
        path.replace(metadata/path.name);moved.append(path.name)
    after=ledger.state()
    assert round(after['cash']+after['deferred'],2)==preserved
    assert not after['orders'] and not after['positions'] and not after['decisions']
    assert after['occupied']==0 and after['free_slots']==5
    result=dict(status='reset_complete',at=now().isoformat(),preserved_cash=preserved,
        prior_event_count=len(events),prior_event_sha256=event_digest(events),
        backup=str(backup),prior_order_count=len(before['orders']),prior_position_count=len(before['positions']),
        new_event_count=len(ledger.events()),new_record_kind='opening cash only, no trades or decisions',
        current_orders=0,current_positions=0,free_slots=5,moved_completion_files=moved,
        reset_is_local_only=True,broker_orders_changed=False)
    (metadata/'RESET_RECEIPT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true',required=True)
    parser.add_argument('--expected-cash',type=float,required=True);args=parser.parse_args()
    try:
        with socket.create_connection(('127.0.0.1',18762),timeout=1):
            raise RuntimeError('请先关闭本机18762后台服务，避免重置期间并发记账')
    except (ConnectionRefusedError,TimeoutError,OSError):pass
    print(json.dumps(reset_account(HERE/'data',args.expected_cash),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
