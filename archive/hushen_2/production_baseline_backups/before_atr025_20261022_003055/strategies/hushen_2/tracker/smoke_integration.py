"""Exercise the live localhost app; no account confirmation or trading actions."""
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request
import market
from store import Ledger

FOLDER=Path(__file__).resolve().parent/'data'
BASE_URL='http://127.0.0.1:18762'

def state():
    with urllib.request.urlopen(BASE_URL+'/api/state',timeout=15) as r:return json.load(r)

def wait():
    deadline=time.monotonic()+600
    last=None
    while time.monotonic()<deadline:
        d=state();status=(d['running'],d['market']['status'])
        if status!=last:print('App',status,flush=True);last=status
        if not d['running']:
            if not d['market_ready']:raise AssertionError(d['market']['message'])
            return d
        time.sleep(5)
    raise TimeoutError('App pipeline did not finish within ten minutes')

def main():
    ledger=Ledger(FOLDER/'ledger.sqlite3');before=ledger.events()
    first=wait();day=first['market']['market_date']
    report=json.loads((FOLDER/'pipeline_verification.json').read_text(encoding='utf-8'))
    assert first['market']['pipeline_id']==report['pipeline_id']
    frozen=market.signal_cache_path(FOLDER,day);original=frozen.read_bytes()
    envelope=json.loads(original)
    assert envelope['signals_sha256']==market.signals_digest(envelope['signals'])
    market.validate_signals(envelope['signals'],market.health(FOLDER))
    reference=__import__('pandas').read_parquet(market.ROOT/report['reference_panel'])
    expected=market.build_signals(reference)
    expected=expected[expected.date.eq(__import__('pandas').Timestamp(day))]
    assert expected.symbol.tolist()==[s['symbol'] for s in envelope['signals']]
    assert expected.score.tolist()==[s['score'] for s in envelope['signals']]
    assert expected.atr_pct.tolist()==[s['atr'] for s in envelope['signals']]
    for s in envelope['signals']:
        raw=__import__('pandas').read_parquet(market.DATA/'raw'/s['symbol'][-2:]/f"{s['symbol']}.parquet")
        rows=raw[__import__('pandas').to_datetime(raw.date).eq(__import__('pandas').Timestamp(day))]
        assert float(rows.close.iloc[0])==s['trigger']
    if not first['confirmed']:assert not first['signals'],'Review gate bypassed'
    with urllib.request.urlopen(BASE_URL+'/',timeout=15) as r:html=r.read().decode('utf-8')
    token=re.search(r"const TOKEN='([^']+)'",html).group(1)
    request=urllib.request.Request(BASE_URL+'/api/update',data=b'{}',headers={'Content-Type':'application/json','X-Tracker-Token':token},method='POST')
    with urllib.request.urlopen(request,timeout=15) as r:assert json.load(r)['ok']
    second=wait()
    assert frozen.read_bytes()==original,'Frozen signals were overwritten during cache reuse'
    assert before==ledger.events(),'Account event log changed'
    result={'status':'ok','market_date':day,'valid_from':envelope['signals'][0]['valid_from'],
            'pipeline_id':envelope['pipeline_id'],'signal_count':len(envelope['signals']),
            'app_signals_match_reference':True,'triggers_match_unadjusted_close':True,'cache_reuse_byte_identical':True,
            'execution_atr_matches_reference':True,'execution_atr_policy':market.EXECUTION_ATR_POLICY,
            'account_events_unchanged':True,'review_gate_applicable':not first['confirmed'],
            'review_gate_preserved':None if first['confirmed'] else not first['signals'],
            'frozen_cache_sha256':hashlib.sha256(original).hexdigest(),
            'note':'Only localhost update endpoint exercised; no accept/reject/buy/sell or broker calls.'}
    destination=FOLDER/'integration_smoke.json'
    if destination.exists():
        old=json.loads(destination.read_text(encoding='utf-8'))
        retained=FOLDER/f"integration_smoke_{old['pipeline_id']}.json"
        if not retained.exists():retained.write_bytes(destination.read_bytes())
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
