"""Recover original exported numerical trees; no training and no production writes."""
import ast
import base64
import hashlib
import json
import subprocess
import sys
import zlib
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
from reconstruct import FEATURES,SOURCE

HERE=Path(__file__).resolve().parent
OUT=HERE/'original_numeric_v1'
OBJECT='1702b35e0cadf60a38f069b28e6ea9b3f5ffa84b'

def convert(model):
    trees=[]
    for ti,nodes in enumerate(model['t']):
        intern=[i for i,n in enumerate(nodes) if n[0]!='L']; leaves=[i for i,n in enumerate(nodes) if n[0]=='L']
        im={n:i for i,n in enumerate(intern)};lm={n:-i-1 for i,n in enumerate(leaves)}
        ref=lambda i:im[i] if i in im else lm[i]
        arrays={'split_feature':[nodes[i][0] for i in intern], 'split_gain':[0]*len(intern),
                'threshold':[nodes[i][1] for i in intern], 'decision_type':[8+2*int(nodes[i][2]) for i in intern],
                'left_child':[ref(nodes[i][3]) for i in intern], 'right_child':[ref(nodes[i][4]) for i in intern],
                'leaf_value':[nodes[i][1] for i in leaves], 'leaf_weight':[1]*len(leaves), 'leaf_count':[1]*len(leaves),
                'internal_value':[0]*len(intern),'internal_weight':[1]*len(intern),'internal_count':[1]*len(intern)}
        text=f'Tree={ti}\nnum_leaves={len(leaves)}\nnum_cat=0\n'
        text+=''.join(k+'='+' '.join(str(v) for v in a)+'\n' for k,a in arrays.items())
        text+='is_linear=0\nshrinkage=1\n\n\n'
        trees.append(text)
    header='tree\nversion=v4\nnum_class=1\nnum_tree_per_iteration=1\nlabel_index=0\nmax_feature_idx=13\nobjective=regression\nfeature_names='+' '.join(model['f'])+'\nfeature_infos='+' '.join(['none']*14)+'\ntree_sizes='+' '.join(str(len(t.encode())) for t in trees)+'\n\n'
    return header+''.join(trees)+'end of trees\n\nfeature_importances:\n\nparameters:\n[objective: regression]\nend of parameters\n\npandas_categorical:null\n'

def reference_predict(model,x):
    out=np.zeros(len(x))
    for nodes in model['t']:
        for row_index,row in enumerate(x):
            i=0
            while nodes[i][0]!='L':
                f,t,d,left,right=nodes[i];v=row[f]
                i=left if (bool(d) if not np.isfinite(v) else v<=t) else right
            out[row_index]+=nodes[i][1]
    return out

def main():
    OUT.mkdir(exist_ok=True)
    source=subprocess.check_output(['git','show',OBJECT])
    (OUT/'source_platform_script.txt').write_bytes(source)
    assignments={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(source).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['MODEL_FEATURES','MODEL_HASHES','_EMBEDDED_MODELS']}
    assert assignments['MODEL_FEATURES']==FEATURES
    report={'source_git_object':OBJECT,'source_sha256':hashlib.sha256(source).hexdigest(),
            'method':'Original embedded numeric trees converted losslessly to executable LightGBM text; NOT original text bytes; no retraining',
            'original_source_hashes':assignments['MODEL_HASHES'],'post2024_market_input_read':False,'production_changed':False,'models':{}}
    p=pd.read_parquet(SOURCE/'cache/model_panel_batch002_pre2025.parquet',columns=['date','symbol']+FEATURES)
    teacher=pd.read_parquet(SOURCE/'results/batch_004_pre2025_factor_tuning/base_component_panel_pre2025.parquet')
    p=teacher.merge(p,on=['date','symbol'],validate='one_to_one').sort_values(['date','symbol']).reset_index(drop=True)
    assert len(p)==len(teacher) and pd.to_datetime(p.date).max()<pd.Timestamp('2025-01-01')
    x=p[FEATURES].to_numpy();assert np.isfinite(x).all()
    recovered=p[teacher.columns].copy()
    for name,encoded in assignments['_EMBEDDED_MODELS'].items():
        raw=zlib.decompress(base64.b64decode(encoded));model=json.loads(raw);assert model['f']==FEATURES
        (OUT/f'{name}.trees.json').write_bytes(raw)
        path=OUT/f'{name}.txt';path.write_bytes(convert(model).encode())
        booster=lgb.Booster(model_file=str(path));assert booster.feature_name()==FEATURES
        # Independent original evaluator checks conversion, including missing-value routing.
        probe=np.concatenate([x[:100],np.full((1,14),np.nan),np.zeros((1,14))])
        delta=np.max(np.abs(booster.predict(probe,num_threads=4)-reference_predict(model,probe)))
        assert delta<1e-12,delta
        pred=booster.predict(x,num_threads=6)
        error=np.abs(pred-p[name].to_numpy())
        report['models'][name]={'trees':len(model['t']),'json_sha256':hashlib.sha256(raw).hexdigest(),
                              'executable_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                              'original_evaluator_probe_max_error':float(delta),'historical_rows':len(p),
                              'historical_max_abs_error':float(error.max()),'historical_rmse':float(np.sqrt(np.mean(error**2))),
                              'rows_above_1e12_tolerance':int((error>1e-12).sum())}
        recovered[name]=pred
        print(name,report['models'][name],flush=True)
    sys.path.insert(0,str(HERE.parent/'runtime'))
    from strategy import build_signals
    a=build_signals(p).reset_index(drop=True);b=build_signals(recovered).reset_index(drop=True)
    assert len(a)==len(b)
    same=a[['date','symbol']].equals(b[['date','symbol']])
    report['signals']={'rows':len(a),'date_symbol_order_identical':same,'max_abs_score_error':float((a.score-b.score).abs().max())}
    (OUT/'VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert same and all(m['historical_max_abs_error']<1e-12 for m in report['models'].values())
    print(json.dumps(report['signals']),flush=True)

if __name__=='__main__':main()
