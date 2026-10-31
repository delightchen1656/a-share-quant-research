"""Read committed quotes; all new artifacts stay inside this audit folder."""
import importlib.util
import json
import sys
import time
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
TRACKER=ROOT/'沪深2_星轨软件/tracker'
sys.path.insert(0,str(TRACKER))
import market
from service import Tracker

spec=importlib.util.spec_from_file_location('market_before_progress',HERE/'market_before.py')
before=importlib.util.module_from_spec(spec)
spec.loader.exec_module(before)
before.BASE=market.BASE
before.DATA=market.DATA
before.RUNTIME=market.RUNTIME
original_score=market.score_panel
evidence={'source_market_hash_before':'81861877a969bb0d32f5892d2058a48f2905035719519bbb85a7d3fa652b63e7',
          'account_written':False,'events':[]}
t=Tracker(HERE/'isolated_tracker')
t.running=True
t.update_clock=t.stage_clock=t.progress_clock=time.monotonic()

def progress(message):
    t.progress(message)
    c=t.calculation_state()
    evidence['events'].append({'elapsed':round(time.monotonic()-t.update_clock,2),
                               'message':message,'percent':c['progress_percent']})
    (HERE/'PROGRESS.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')

def score_and_compare(p,callback):
    result=original_score(p,callback)
    reference=before.score_panel(p)
    pd.testing.assert_frame_equal(result,reference,check_exact=True)
    evidence['full_history_scores_bitwise_identical']=True
    evidence['feature_rows']=len(p)
    return result

market.score_panel=score_and_compare
h=market.health(TRACKER/'data')
evidence['market_date']=h['market_date']
signals=market.predict(HERE/'isolated_tracker',h,progress=progress)
progress('保存并校验当日冻结信号')
market.validate_signals(signals,h)
progress('发布次日推荐')
t.running=False;t.info={'status':'ready'}
evidence.update(status='ok',seconds=round(time.monotonic()-t.update_clock,2),
                final_progress=t.calculation_state()['progress_percent'],signals=signals,
                monotonically_increasing=all(a['percent']<=b['percent'] for a,b in zip(evidence['events'],evidence['events'][1:])))
(HERE/'VERIFICATION.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k not in ('events','signals')},ensure_ascii=False),flush=True)
