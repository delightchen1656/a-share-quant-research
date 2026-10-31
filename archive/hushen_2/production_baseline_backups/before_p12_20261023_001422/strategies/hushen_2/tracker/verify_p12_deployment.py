"""Actual local inference plus frozen P12 parity; no account confirmation/trades."""
from pathlib import Path
from datetime import datetime
import argparse,json,sqlite3,sys,urllib.request
import numpy as np
import pandas as pd
import market


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--backup',type=Path,required=True);args=parser.parse_args()
    backup=args.backup.resolve();base=market.BASE
    def account():
        with sqlite3.connect((base/'tracker/data/ledger.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
            return {table:[list(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in ['events','confirmations','account_settings']}
    before=json.loads((backup/'ACCOUNT_BEFORE.json').read_text(encoding='utf-8'))
    assert account()==before,'Account changed since backup; inspect before claiming preservation'
    source=base/'results/holdout_restricted/pair_top5_post2024/attempt_20261022_185820/INPUT_SIGNALS_FEATURES.parquet'
    frozen=pd.read_parquet(source)
    expected=frozen.loc[frozen.atr_pct.ge(.025)&frozen.size_proxy.ge(16.901055936487055)&frozen.vol60.ge(.018471572551217057)]
    actual=market.filter_signal_frame(frozen)
    pd.testing.assert_frame_equal(actual,expected,check_exact=True)
    # Historical current-entry adapter must use the very same frozen P12 mask.
    sys.path.insert(0,str(base/'backtest'))
    from replay_selected_price_atr import registered_filter
    replay=registered_filter(frozen.drop(columns=['size_proxy','vol60']))
    assert list(zip(replay.date,replay.symbol))==list(zip(expected.date,expected.symbol))
    print('Frozen historical P12 parity',len(frozen),len(actual),flush=True)
    folder=base/'tracker/data'/datetime.now().strftime('p12_deployment_validation_%Y%m%d_%H%M%S')
    folder.mkdir(exist_ok=False)
    h=market.health(base/'tracker/data');inventory=market.input_inventory()
    print('Actual local model pipeline',h['market_date'],flush=True)
    signals=market.predict(folder,h)
    market.validate_signals(signals,h)
    audit=json.loads(next((folder/'pipeline_audits').glob('*.json')).read_text(encoding='utf-8'))
    originals=audit['original_top3'];independent=[s for s in originals if .025<=s['atr']<=.05 and s['size_proxy']>=16.901055936487055 and s['vol60']>=.018471572551217057]
    assert signals==independent
    feature_checks=[]
    for s in originals:
        b=pd.read_parquet(market.DATA/'qfq'/s['symbol'][-2:]/(s['symbol']+'.parquet'))
        b=b.loc[pd.to_datetime(b.date).between('2018-01-01',h['market_date'])].sort_values('date')
        for key in ['close','amount','turn']:b[key]=pd.to_numeric(b[key],errors='raise')
        cap=float(np.log1p(b.amount.iloc[-1])-np.log(max(float(b.turn.iloc[-1]),1e-6)))
        vol=float(b.close.pct_change(fill_method=None).rolling(60,min_periods=60).std(ddof=0).iloc[-1])
        assert abs(cap-s['size_proxy'])<1e-12 and abs(vol-s['vol60'])<1e-12
        feature_checks.append(dict(symbol=s['symbol'],size_proxy=cap,vol60=vol))
    live=json.load(urllib.request.urlopen('http://127.0.0.1:18762/api/state',timeout=20))
    assert live['signal_filter']==market.signal_filter_configuration()
    if not live['confirmed']:assert not live['signals'] and not live['market_ready']
    assert account()==before
    assert market.input_inventory()==inventory
    unchanged={name:market.digest(base/'model'/name)==market.digest(backup/'strategies/hushen_2/model'/name) for name in ['utility.txt','pen025.txt','pen100.txt','manifest.json']}
    assert all(unchanged.values())
    old_caches=list((backup/'strategies/hushen_2/tracker/data').glob('signals_*.json'))
    for old in old_caches:assert market.digest(old)==market.digest(base/'tracker/data'/old.name)
    report=dict(status='verified',baseline='P12',market_date=h['market_date'],next_session=next(d for d in h['sessions'] if d>h['market_date']),
        policy=market.signal_filter_configuration(),historical_input_rows=len(frozen),historical_P12_rows=len(actual),
        historical_filter_identical=True,backtest_filter_identical=True,frozen_input_sha256=market.digest(source),
        actual_pipeline_audit=str(next((folder/'pipeline_audits').glob('*.json'))),pipeline_id=audit['pipeline_id'],
        original_top3=originals,isolated_verified_recommendations=signals,live_recommendations_published=False,
        feature_checks=feature_checks,live_backend_P12_loaded=True,cash_review_required=not live['confirmed'],
        account_events_cash_settings_confirmations_unchanged=True,models_unchanged=unchanged,old_signal_caches_preserved=len(old_caches),market_files_unchanged=True,
        cash=live['cash'],equity=live['equity'],backup=str(backup),broker_orders_submitted=False)
    (base/'tracker/data/p12_deployment_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
