"""Capture and verify a display-only daily curve change; never edit ledger rows."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,sqlite3,time,urllib.request
import pandas as pd

HERE=Path(__file__).resolve().parent


def read_tables():
    with sqlite3.connect((HERE/'data/ledger.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        return {table:[dict(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in ['events','confirmations','account_settings','account_observations']}


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['capture','verify']);p.add_argument('--snapshot',type=Path);a=p.parse_args()
    if a.mode=='capture':
        out=HERE/'data/backups'/datetime.now().strftime('daily_final_curve_%Y%m%d_%H%M%S');out.mkdir(exist_ok=False)
        with sqlite3.connect((HERE/'data/ledger.sqlite3').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(out/'ledger.sqlite3') as dst:
            src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        (out/'BEFORE.json').write_text(json.dumps(read_tables(),ensure_ascii=False,indent=2),encoding='utf-8')
        print(out);return
    before=json.loads((a.snapshot/'BEFORE.json').read_text(encoding='utf-8'));after=read_tables()
    for table in ['events','confirmations','account_settings']:assert after[table]==before[table],table
    current={row['id']:row for row in after['account_observations']}
    assert all(current.get(row['id'])==row for row in before['account_observations'])
    live=None
    for _ in range(30):
        live=json.load(urllib.request.urlopen('http://127.0.0.1:18762/api/state',timeout=15))
        if not live['running']:break
        time.sleep(1)
    assert not live['running'] and live['market_ready']
    settings={row['key']:json.loads(row['value']) for row in after['account_settings']}
    observations=[r for r in read_tables()['account_observations'] if r['revision']>=settings.get('performance_min_revision',0)]
    expected={}
    for r in observations:
        key=(pd.Timestamp(r['at']).value,r['id'])
        if r['day'] not in expected or key>expected[r['day']][0]:expected[r['day']]=(key,r)
    curve=live['account_curve'];assert len(curve)==len({r['day'] for r in curve})==len(expected)
    assert curve==live['performance']['curve']
    for r in curve:
        chosen=expected[r['day']][1]
        for k in ['id','day','at','equity','cash','revision']:assert r[k]==chosen[k]
    report=dict(status='passed',original_observation_rows_preserved=len(before['account_observations']),
        displayed_daily_points=len(curve),days=[r['day'] for r in curve],one_final_point_per_day=True,
        account_events_cash_settings_confirmations_unchanged=True,backend_ready=live['market_ready'],
        backend_running=live['running'],signal_statuses=[dict(symbol=s['symbol'],status=s['status']) for s in live['signals']],
        market_date=live['market']['market_date'],snapshot=str(a.snapshot))
    (HERE/'data/daily_final_curve_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
