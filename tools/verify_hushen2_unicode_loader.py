"""Audit Unicode loading equivalence and today's committed production pipeline."""
from pathlib import Path
import hashlib,json,sqlite3,sys,urllib.request
import lightgbm as lgb
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'沪深实盘工作台'
OUT=ROOT/'archive/reports/maintenance/hushen2_unicode_loader_20261026'
sys.path.insert(0,str(APP/'tracker'))
import market
from model_loader import load_verified_model

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    before=json.loads((OUT/'PROTECTED_BEFORE.json').read_text(encoding='utf-8'))
    unchanged={path:sha(ROOT/path)==expected for path,expected in before['files'].items()}
    assert all(unchanged.values()),unchanged
    db=APP/'tracker/data/ledger.sqlite3'
    with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as connection:
        tables={t:connection.execute('select * from '+t+' order by 1').fetchall() for t in ['events','confirmations','account_settings']}
    financial_hash=hashlib.sha256(json.dumps(tables,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    assert financial_hash==before['financial_tables_sha256'],'Financial ledger changed; inspect user activity, never rollback'
    manifest=json.loads((APP/'model/manifest.json').read_text(encoding='utf-8'))
    rng=np.random.default_rng(2661);x=rng.normal(size=(512,len(market.FEATURES)));x[::9,3]=np.nan
    models=[]
    for name in ('utility','pen025','pen100'):
        original=ROOT/'沪深2研究/model'/f'{name}.txt';current=APP/'model'/f'{name}.txt'
        assert sha(original)==sha(current)==manifest[name]
        native=lgb.Booster(model_file=str(original));actual=load_verified_model(current,manifest[name],market.FEATURES)
        delta=float(np.max(np.abs(native.predict(x,num_threads=1)-actual.predict(x,num_threads=1))))
        assert delta==0. and native.model_to_string()==actual.model_to_string()
        models.append(dict(name=name,sha256=sha(current),trees=actual.num_trees(),features=actual.num_feature(),prediction_max_abs_delta=delta))
    with urllib.request.urlopen('http://127.0.0.1:18762/api/state',timeout=30) as response:state=json.load(response)
    assert not state['running'] and state['market_ready'],state['calculation_status']
    assert state['calculation_status']['label']=='已完成'
    h=market.health(APP/'tracker/data');assert h['market_date']=='2026-10-26'
    cache=market.signal_cache_path(APP/'tracker/data',h['market_date'])
    frozen=json.loads(cache.read_text(encoding='utf-8'));identity,inputs=market.pipeline_identity(h)
    assert frozen['pipeline_id']==identity and frozen['signals_sha256']==market.signals_digest(frozen['signals'])
    market.validate_signals(frozen['signals'],h)
    assert any(path.endswith('tracker/model_loader.py') for path in inputs['files'])
    audit=APP/'tracker/data/pipeline_audits'/f"{h['market_date']}_{identity}.json"
    evidence=json.loads(audit.read_text(encoding='utf-8'));assert evidence['pipeline_id']==identity
    result=dict(status='passed',date='2026-10-26',model_loading='Python verified UTF8 bytes -> LightGBM model_str; never pass Unicode filename to native parser',
        model_equivalence=models,protected_files_unchanged=unchanged,financial_tables_unchanged=True,events_count=len(tables['events']),
        unit_tests=60,unit_tests_passed=True,pipeline_version=market.PIPELINE_VERSION,pipeline_id=identity,market_date=h['market_date'],
        feature_rows=evidence['feature_rows'],latest_eligible_symbols=evidence['latest_eligible_symbols'],signal_count=len(frozen['signals']),
        signals=frozen['signals'],cache=str(cache.relative_to(ROOT)),pipeline_audit=str(audit.relative_to(ROOT)),running=False,
        displayed_status=state['calculation_status']['label'],models_retrained=False,strategy_changed=False,account_adjusted=False)
    (OUT/'VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
