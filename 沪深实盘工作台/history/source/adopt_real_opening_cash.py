"""Replace the discarded 100k test basis, keeping every remaining real event."""
import argparse
import json
from pathlib import Path
from store import Ledger, now


def adopt(folder):
    ledger=Ledger(Path(folder)/'ledger.sqlite3')
    backup=ledger.backup()
    before_events=ledger.events();before=ledger.state(events=before_events)
    first=next(e for e in before_events if e['id']==5)
    assert first['kind']=='cash_adjust' and first['data']['source']=='cash_window'
    assert first['data']['previous_cash']==5679.96 and first['data']['target_cash']==7150.25
    assert not any(e['id']==1 for e in before_events)
    assert before['cash']==99622.78, '账户已变化，停止自动修复'
    configuration=dict(initial_cash=5679.96,performance_min_revision=5,pnl_baseline_date='2026-10-20',
        opening_basis_note='用户澄清：100000为测试起点，后续现金覆盖与成交为真实记录；删除的测试差额不恢复')
    with ledger.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=[dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
        assert current==before_events
        for key,value in configuration.items():
            db.execute('INSERT OR REPLACE INTO account_settings(key,value) VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
        # Cash must be checked again; do not auto-attest a broker balance.
        clock=now();day=clock.date()
        if (clock.hour,clock.minute)<(9,30):
            from datetime import timedelta
            day-=timedelta(days=1)
        db.execute('DELETE FROM confirmations WHERE day=?',(day.isoformat(),))
    after=ledger.state()
    assert after['cash']==5302.74
    assert ledger.events()==before_events
    for key in ['positions','orders','all_orders','realized','deferred','occupied']:assert after[key]==before[key]
    report=dict(status='corrected_real_opening_basis',at=now().isoformat(),backup=str(backup),
        settings=configuration,cash_before=before['cash'],cash_after=after['cash'],
        deleted_test_event_stays_deleted=True,all_remaining_real_events_unchanged=True,
        research_backtest_100000_capital_unchanged=True,first_real_close_is_performance_baseline_not_profit=True)
    destination=Path(folder)/'backups'/f"real_opening_basis_{now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',required=True,action='store_true');parser.parse_args()
    adopt(Path(__file__).resolve().parent/'data')
