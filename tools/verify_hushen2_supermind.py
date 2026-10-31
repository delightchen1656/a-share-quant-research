"""Compare exported feature/ranking pipeline against the current frozen runtime."""
import ast,hashlib,importlib.util,json,sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'沪深2研究';APP=ROOT/'沪深实盘工作台'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    portable=load('exported_signal_core',BASE/'supermind/signal_core.py')
    original_builder=load('original_frozen_builder',BASE/'runtime/frozen_builder.py')
    sys.path.insert(0,str(APP/'tracker'))
    from model_loader import load_verified_model
    source=(APP/'tracker/market.py').read_text(encoding='utf-8');tree=ast.parse(source)
    ns=dict(pd=pd,np=np,json=json,BASE=APP,SIGNAL_START='2020-01-01',
        FEATURES=portable.load_models()['utility']['features'],load_verified_model=load_verified_model,
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest())
    for name in ('model_features','score_panel'):
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        exec(ast.get_source_segment(source,node),ns)
    paths=sorted((ROOT/'K线数据/沪深/qfq').glob('*/*.parquet'))[:40]
    panels=[];rows=0
    for path in paths:
        b=pd.read_parquet(path);b.date=pd.to_datetime(b.date)
        b=b.loc[b.date.between('2018-01-01','2024-12-31')].sort_values('date').reset_index(drop=True)
        for k in ['open','high','low','close','preclose','amount','turn','tradestatus','isST']:b[k]=pd.to_numeric(b[k],errors='coerce')
        if len(b)<120:continue
        p=portable.model_features(b);reference=ns['model_features'](b)
        pd.testing.assert_frame_equal(p,reference,check_exact=True)
        if len(p):panels.append(p)
    panel=pd.concat(panels,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    models=portable.load_models();expected=ns['score_panel'](panel);actual=portable.score_panel(panel,models)
    keys=['utility','pen025','h_size_neg','h_vol60_neg','h_overnight_pos','h_intraday_neg','t_mom120_pos','t_high60_pos','t_mom20_pos','t_vol60_neg']
    for k in keys:np.testing.assert_array_equal(expected[k],actual[k])
    signals=portable.frozen_signals(panel,models)
    reference=original_builder.build_signals(expected,'C04_NEW',portable.SPEC);reference=reference.loc[reference.atr_pct.ge(.025)]
    pd.testing.assert_frame_equal(signals,reference,check_exact=True)
    standalone=BASE/'supermind_hushen_2.py';ast.parse(standalone.read_text(encoding='utf-8'),feature_version=(3,8))
    build=json.loads((BASE/'supermind/BUILD_MANIFEST.json').read_text(encoding='utf-8'))
    assert build['selection_sha256']==hashlib.sha256((BASE/'CURRENT_SELECTION.json').read_bytes()).hexdigest()
    report=dict(status='local_verified_platform_login_required',quote_files=len(paths),feature_rows=len(panel),signal_rows=len(signals),
        feature_values_exact=True,model_predictions_exact=True,component_ranks_exact=True,top3_then_atr_exact=True,
        python38_syntax_passed=True,native_callback_tests=11,native_platform_run=False,models_retrained=False,
        baseline_selection_unchanged=True,standalone_sha256=hashlib.sha256(standalone.read_bytes()).hexdigest())
    (BASE/'supermind/VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
