"""Read-only acceptance of ATR025 deployment; writes a separate audit report only."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import sqlite3
import urllib.request
import pandas as pd
import market

BACKUP=market.ROOT/'archive/hushen_2/production_baseline_backups/before_atr025_20261022_003055'


def main():
    manifest=json.loads((BACKUP/'BACKUP_MANIFEST.json').read_text(encoding='utf-8'))
    for relative,h in manifest['files_sha256'].items():
        assert market.digest(BACKUP/'strategies/hushen_2'/relative)==h,('Backup failed verification',relative)
    original_db=BACKUP/'strategies/hushen_2/tracker/data/ledger.sqlite3'
    current_db=market.BASE/'tracker/data/ledger.sqlite3'
    with sqlite3.connect(original_db.as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(current_db.as_uri()+'?mode=ro',uri=True) as b:
        assert list(a.iterdump())==list(b.iterdump()),'Account tables changed during deployment'
    legacy_caches=[]
    for relative,h in manifest['files_sha256'].items():
        if relative.startswith('tracker/data/signals_'):
            assert market.digest(market.BASE/relative)==h,('Legacy signal cache overwritten',relative)
            legacy_caches.append(relative)
    model_files=[]
    for relative,h in manifest['files_sha256'].items():
        if relative.startswith('model/'):
            assert market.digest(market.BASE/relative)==h,('Frozen model changed',relative)
            model_files.append(relative)
    frozen=market.BASE/'results/holdout_restricted/atr_thresholds_to_current/attempt_20261021_202807/INPUT_SIGNALS.parquet'
    historical=pd.read_parquet(frozen)
    expected=historical.loc[historical.atr_pct.ge(.025)].copy()
    actual=market.filter_signal_frame(historical)
    pd.testing.assert_frame_equal(actual,expected,check_exact=True)
    with urllib.request.urlopen('http://127.0.0.1:18762/api/state',timeout=15) as response:state=json.load(response)
    assert state['market_ready'] and not state['running']
    assert state['signal_filter']==market.signal_filter_configuration()
    assert state['cash']==manifest['account_cash']
    assert len(state['positions'])==manifest['open_positions'] and len(state['orders'])==manifest['open_orders']
    folder=market.BASE/'tracker/data';day=state['market']['market_date']
    cache=market.signal_cache_path(folder,day)
    payload=json.loads(cache.read_text(encoding='utf-8'))
    assert payload['signal_filter_policy']==market.SIGNAL_FILTER_POLICY_ID
    assert all(s['atr']>=.025 for s in payload['signals'])
    market.validate_signals(payload['signals'],market.health(folder))
    verification=json.loads((folder/'pipeline_verification.json').read_text(encoding='utf-8'))
    assert verification['status']=='ok' and verification['pipeline_id']==state['market']['pipeline_id']==payload['pipeline_id']
    assert verification['filter_applied_after_original_top3'] and not verification['refill']
    smoke=json.loads((folder/'integration_smoke.json').read_text(encoding='utf-8'))
    assert smoke['status']=='ok' and smoke['pipeline_id']==payload['pipeline_id'] and smoke['account_events_unchanged']
    selection=json.loads((market.BASE/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['signal_filter']==market.signal_filter_configuration()
    preserved=[market.BASE/'runtime/strategy.py',market.BASE/'runtime/frozen_builder.py',market.BASE/'tracker/store.py']
    assert all(market.digest(p)==manifest['files_sha256'][str(p.relative_to(market.BASE)).replace('\\','/')] for p in preserved)
    out=market.BASE/'results/holdout_restricted/atr025_production_deployment'/datetime.now(ZoneInfo('Asia/Shanghai')).strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='verified',baseline_id=selection['selection']['baseline_id'],signal_filter=market.signal_filter_configuration(),
        backup=str(BACKUP),backup_files_verified=len(manifest['files_sha256']),account_all_sql_tables_identical=True,
        cash=state['cash'],positions=len(state['positions']),orders=len(state['orders']),free_slots=state['free_slots'],
        legacy_caches_unchanged=legacy_caches,model_files_unchanged=model_files,frozen_factor_and_ledger_code_unchanged=True,
        historical_filter_rows_checked=len(historical),historical_filtered_rows=len(actual),historical_filter_identical=True,
        market_date=day,cache=str(cache),cache_sha256=market.digest(cache),pipeline_id=payload['pipeline_id'],
        new_signals=[dict(symbol=s['symbol'],rank=s['rank'],atr=s['atr']) for s in payload['signals']],
        source_verification=str(folder/'pipeline_verification.json'),integration_verification=str(folder/'integration_smoke.json'),
        source_hashes={str(p.relative_to(market.ROOT)):market.digest(p) for p in [market.BASE/'CURRENT_SELECTION.json',market.RUNTIME/'signal_policy.py',market.BASE/'tracker/market.py',market.BASE/'tracker/service.py',market.BASE/'tracker/ui/index.html']},
        broker_order_actions=False,existing_accepted_terms_rewritten=False)
    (out/'DEPLOYMENT_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OUTPUT',out);print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
