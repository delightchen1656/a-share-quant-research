"""Export frozen Hushen2 predictors and exact signal functions without LightGBM."""
import ast,base64,hashlib,json,textwrap,zlib
from pathlib import Path
import lightgbm as lgb

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'沪深2研究'
OUT=BASE/'supermind'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    selection=json.loads((BASE/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    manifest=json.loads((BASE/'model/manifest.json').read_text(encoding='utf-8'))
    models={}
    for name in ('utility','pen025'):
        path=BASE/'model'/f'{name}.txt';assert digest(path)==manifest[name]
        booster=lgb.Booster(model_str=path.read_text(encoding='utf-8'))
        dump=booster.dump_model();assert dump['objective']=='regression'
        trees=[]
        def flatten(node,arrays):
            i=len(arrays[0])
            for values,value in zip(arrays,[-1,0.,False,-1,-1,False,0.]):values.append(value)
            if 'leaf_value' in node:
                arrays[5][i]=True;arrays[6][i]=node['leaf_value']
            else:
                assert node['decision_type']=='<=' and node['missing_type'] in ('None','NaN')
                arrays[0][i]=node['split_feature'];arrays[1][i]=node['threshold'];arrays[2][i]=node['default_left']
                arrays[3][i]=flatten(node['left_child'],arrays);arrays[4][i]=flatten(node['right_child'],arrays)
            return i
        for tree in dump['tree_info']:
            arrays=[[] for _ in range(7)];flatten(tree['tree_structure'],arrays);trees.append(arrays)
        models[name]=dict(features=dump['feature_names'],trees=trees,source_sha256=manifest[name])
    market=(ROOT/'沪深实盘工作台/tracker/market.py').read_text(encoding='utf-8')
    tree=ast.parse(market);features=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='model_features')
    feature_source=ast.get_source_segment(market,features)
    frozen=(BASE/'runtime/frozen_builder.py').read_text(encoding='utf-8')
    functions=[ast.get_source_segment(frozen,n) for n in ast.parse(frozen).body if isinstance(n,ast.FunctionDef)]
    payload=base64.b64encode(zlib.compress(json.dumps(models,separators=(',',':')).encode(),9)).decode()
    header='''# -*- coding: utf-8 -*-
"""Frozen Hushen2 signal core; generated, no training/no historical-rank payload."""
from __future__ import annotations
import base64,json,zlib
import numpy as np
import pandas as pd
SIGNAL_START='2020-01-01'
TOP_K=3
SPEC=%r
_MODEL_DATA=(
%s
)

def load_models():
    models=json.loads(zlib.decompress(base64.b64decode(_MODEL_DATA)).decode('utf-8'))
    for model in models.values():
        model['trees']=[tuple(np.asarray(a,dtype=d) for a,d in zip(tree,
            [np.int16,float,bool,np.int16,np.int16,bool,float])) for tree in model['trees']]
    return models

def predict_trees(model,values):
    x=np.asarray(values,dtype=float);result=np.zeros(len(x),dtype=float)
    for feature,threshold,missing,left,right,leaf,value in model['trees']:
        nodes=np.zeros(len(x),dtype=np.int32)
        active=~leaf[nodes]
        while active.any():
            rows=np.flatnonzero(active);at=nodes[rows];v=x[rows,feature[at]]
            go_left=np.where(np.isnan(v),missing[at],v<=threshold[at])
            nodes[rows]=np.where(go_left,left[at],right[at]);active=~leaf[nodes]
        result+=value[nodes]
    return result

def score_panel(panel,models):
    p=panel.copy()
    for name in ('utility','pen025'):
        p[name]=predict_trees(models[name],p[models[name]['features']])
    p['pen100']=0.0 # its frozen weight is zero
    cap=p.f_log_amount-np.log(p.f_turn.clip(lower=1e-6))
    ranks=p.assign(_cap=cap).groupby('date')[['_cap','vol60','overnight20','intraday20','mom120','close_to_high60','mom20']].rank(pct=True,method='average')-.5
    p['h_size_neg']=-ranks['_cap'];p['h_vol60_neg']=-ranks.vol60
    p['h_overnight_pos']=ranks.overnight20;p['h_intraday_neg']=-ranks.intraday20
    p['t_mom120_pos']=ranks.mom120;p['t_high60_pos']=ranks.close_to_high60
    p['t_mom20_pos']=ranks.mom20;p['t_vol60_neg']=-ranks.vol60
    return p

def frozen_signals(panel,models):
    signals=build_signals(score_panel(panel,models),'C04_NEW',SPEC)
    return signals.loc[signals.atr_pct.ge(.025)].copy()

'''%(selection['selection']['factor_spec'],'\n'.join('    '+repr(s) for s in textwrap.wrap(payload,100)))
    OUT.mkdir(exist_ok=True)
    dest=OUT/'signal_core.py';dest.write_text(header+feature_source+'\n\n'+'\n\n'.join(functions)+'\n',encoding='utf-8')
    identity=dict(status='generated_not_platform_validated',selection_sha256=digest(BASE/'CURRENT_SELECTION.json'),
        model_hashes={n:manifest[n] for n in models},feature_source_sha256=hashlib.sha256(feature_source.encode()).hexdigest(),
        signal_core_sha256=digest(dest),models_retrained=False,embedded_future_signals=False)
    template=OUT/'native_template.py'
    if template.exists():
        standalone=BASE/'supermind_hushen_2.py'
        standalone.write_text(dest.read_text(encoding='utf-8')+'\n\n'+template.read_text(encoding='utf-8'),encoding='utf-8')
        identity['standalone_sha256']=digest(standalone)
    (OUT/'BUILD_MANIFEST.json').write_text(json.dumps(identity,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(identity,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
