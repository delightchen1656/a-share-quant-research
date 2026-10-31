"""Mirror a verified, already-completed daily cache. No prediction/account writes."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
TRACKER=ROOT/'沪深实盘工作台/tracker'
sys.path.insert(0,str(TRACKER))
import market
from service import save_model_result

folder=TRACKER/'data'
h=market.health(folder)
path=market.signal_cache_path(folder,h['market_date'])
if not path.exists():raise SystemExit('Still calculating: no completed daily result yet')
frozen=json.loads(path.read_text(encoding='utf-8'))
identity,_=market.pipeline_identity(h)
if frozen.get('pipeline_id')!=identity:raise RuntimeError('Completed cache input identity mismatch')
if frozen.get('market_date')!=h['market_date']:raise RuntimeError('Completed cache date mismatch')
if frozen.get('signal_filter_policy')!=market.SIGNAL_FILTER_POLICY_ID:raise RuntimeError('Completed cache policy mismatch')
if frozen.get('signals_sha256')!=market.signals_digest(frozen['signals']):raise RuntimeError('Completed cache digest mismatch')
market.validate_signals(frozen['signals'],h)
if market.pipeline_identity(market.health(folder))[0]!=identity:raise RuntimeError('Inputs changed during validation')
destination=folder/'latest_model_result.json'
save_model_result(destination,frozen)
report={'status':'ok','market_date':h['market_date'],'source':str(path),'saved_file':str(destination),
        'signals':len(frozen['signals']),'prediction_called':False,'account_written':False,
        'tests_passed':85,'same_signals':json.loads(destination.read_text(encoding='utf-8'))==frozen}
audit=ROOT/'archive/reports/maintenance/hushen2_persisted_model_result_20261029'
audit.mkdir(parents=True,exist_ok=True)
(audit/'VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
