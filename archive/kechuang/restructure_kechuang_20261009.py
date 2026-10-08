"""Mechanical extraction of frozen replay functions after the verified archive move."""
from pathlib import Path
import ast, json, shutil, hashlib
ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'archive/kechuang/20261009_before_unification'
NEW=ROOT/'strategies/kechuang'
def functions(path,names):
    text=path.read_text(encoding='utf-8-sig'); tree=ast.parse(text)
    found={n.name:ast.get_source_segment(text,n) for n in tree.body if isinstance(n,ast.FunctionDef)}
    return '\n\n'.join(found[n] for n in names)+'\n'
def write(path,text):
    if path.exists():raise RuntimeError('Refuse overwrite '+str(path))
    path.write_text(text,encoding='utf-8')
def main():
    pipeline=OLD/'baseline_3_2/retrain_2022/pipeline.py'
    helpers='''from pathlib import Path
from types import SimpleNamespace
import ast, base64, hashlib, json, zlib, importlib.util, math
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'evening_accumulation/data'
spec=importlib.util.spec_from_file_location('star_features',Path(__file__).resolve().parents[1]/'research/training_source/src/model.py')
feature=importlib.util.module_from_spec(spec);spec.loader.exec_module(feature)
F=feature.FEATURES
'''+functions(pipeline,['save','sha','dataset','namespace','fast'])
    write(NEW/'backtest/data_helpers.py',helpers)
    replay=OLD/'baseline_3_2/start_date_study.py'
    code=functions(replay,['dump','actions','run_starts'])
    code=code.replace('def run_starts(prep, action_map):','def run_starts(prep, action_map, requested_start):')
    code=code.replace("starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]",'starts=dates[dates>=pd.Timestamp(requested_start)][:1]')
    code=code[:code.index('    out=pd.DataFrame(results)')]+"    return results[0],all_curves[0],pd.DataFrame(all_trades),reference_differences\n"
    code=code.replace('                desired=int(equity(True)*.10/px)', '''                nav=equity(True)
                fraction=max(.10,float(r.open)*200*1.01/nav)
                if fraction>.20:continue
                reserve=nav*fraction*1.005
                if cash<reserve:continue
                desired=int(nav*fraction/px)''')
    code=code.replace('                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)','                signal=float(r.open)')
    header='''from pathlib import Path
import json
import numpy as np
import pandas as pd
END=pd.Timestamp('2026-09-30')
CASH=500000.
OUT=Path(__file__).resolve().parents[1]/'results/latest'
'''
    write(NEW/'backtest/engine.py',header+functions(OLD/'baseline_3_1_start_dates_100k_20261008/run.py',['old_exit'])+code)
    data=NEW/'backtest/data';data.mkdir()
    shutil.copytree(OLD/'baseline_3_2/retrain_2022/snapshots/2026-09-30',data/'snapshot_20260930')
    shutil.copy2(OLD/'execution_audit_20261009/cash_skip_halfyear/results/corporate_actions.json',data/'corporate_actions.json')
    rows=json.loads((OLD/'execution_audit_20261009/cash_skip_halfyear/results/summary.json').read_text(encoding='utf-8'))
    refs=[r for r in rows if r['variant']=='A']
    write(NEW/'research/reference_metrics.json',json.dumps(refs,indent=2))
    sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    write(NEW/'research/provenance.json',json.dumps(dict(name='科创基准1',source_attachment='f3b7e3dc-7fff-4d89-a1e4-c0209e7e52a6',
        platform_sha256=sha(NEW/'supermind_kechuang_1.py'),source_unchanged=True,retrained=False,
        archive=str(OLD.relative_to(ROOT)),extraction_sources={str(f.relative_to(ROOT)):sha(f) for f in [pipeline,replay,OLD/'baseline_3_1_start_dates_100k_20261008/run.py']}),ensure_ascii=False,indent=2))
    print('Mechanical extraction complete; no archive runtime dependency')
if __name__=='__main__':main()
