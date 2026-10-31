"""Direction2 membership from frozen as-of screens, never from future target outcomes."""
from pathlib import Path
import hashlib,json,threading
import joblib
import numpy as np
import pandas as pd
from direction_features import features,enrich,ALL_FEATURES

HERE=Path(__file__).resolve().parent
REGISTRY=HERE/'directions/holdout_restricted/CURRENT.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class DirectionError(ValueError):pass

def score_mask(pack,data,spec):
    if spec.get('abstain'):return np.zeros(len(data),bool)
    if 'conditions' in spec:
        result=np.ones(len(data),bool)
        for key,op,value in spec['conditions']:result &= (data[key].ge(value) if op=='>=' else data[key].le(value)).fillna(False).to_numpy()
        return result
    def score(name):
        model,cols=pack['models'][name];return model.predict_proba(data[cols])[:,1]
    def rank(name,values):return np.searchsorted(np.sort(pack['references'][name]),values,side='right')/len(pack['references'][name])
    name=spec['model']
    if name=='rank_ensemble':values=.5*rank('lr_all_02',score('lr_all_02'))+.25*rank('extra_trees',score('extra_trees'))+.25*rank('balanced_boost',score('balanced_boost'))
    else:values=score(name)
    mask=values>=spec['threshold']
    if spec['up_volume_gate'] is not None:mask &= data.base_up_volume_share.ge(spec['up_volume_gate']).to_numpy()
    return mask

class DirectionService:
    def __init__(self,registry=REGISTRY):self.registry=Path(registry);self.lock=threading.RLock();self.cached_key=None;self.cached=None
    def package(self):
        pointer=json.loads(self.registry.read_text(encoding='utf-8'));root=Path(pointer['path']);manifest=root/'MANIFEST.json'
        if sha(manifest)!=pointer['manifest_sha256']:raise DirectionError('方向2清单校验失败')
        m=json.loads(manifest.read_text(encoding='utf-8'))
        if sha(HERE/'direction_features.py')!=m['feature_code_sha256']:raise DirectionError('方向2特征代码校验失败')
        for name,expected in m['files'].items():
            p=(root/name).resolve()
            if not p.is_relative_to(root.resolve()) or sha(p)!=expected:raise DirectionError('方向2模型或历史清单校验失败')
        if m['trained_through']!='2024-12-31':raise DirectionError('方向2模型训练边界异常')
        return root,m,pointer['manifest_sha256']
    def annotate(self,store,rows):
        with self.lock:
            root,m,package_hash=self.package();key=(store.generation,package_hash)
            if key==self.cached_key:return self.cached
            historical={r['event_id']:r for r in json.loads((root/'historical_selected.json').read_text(encoding='utf-8'))}
            selected={};pending=[];feature_checks=[]
            for row in rows:
                if row['date']<='2024-12-31':
                    if row['id'] in historical:feature_checks.append(row)
                else:
                    pools=[p for p,c in m['pools'].items() if (p!='leaders' or row['is_leader']) and not c['spec'].get('abstain')]
                    if pools:pending.append((row,pools))
            all_needed={r['code'] for r in feature_checks}|{r['code'] for r,_ in pending};feature_rows={};mismatched=0
            for code in sorted(all_needed):
                fs={}
                for mode in ['qfq','raw']:
                    path=store.paths[(code,mode)]
                    if sha(path)!=store.hashes[(code,mode)]:raise DirectionError('方向2行情快照校验失败')
                    fs[mode]=pd.read_parquet(path).set_index('date').reindex(store.dates)
                    for col in ['open','high','low','close','preclose','volume','amount']:
                        if col in fs[mode]:fs[mode][col]=pd.to_numeric(fs[mode][col],errors='coerce')
                needed=[r for r in feature_checks if r['code']==code]+[r for r,_ in pending if r['code']==code]
                for r in needed:
                    t=store.dates.get_loc(pd.Timestamp(r['date']))
                    f=enrich(pd.DataFrame([features(fs['qfq'],fs['raw'],t)]));feature_rows[r['id']]=f.iloc[0]
            for r in feature_checks:
                h=historical[r['id']];current=feature_rows[r['id']]
                a=current[ALL_FEATURES].to_numpy(float);b=np.array([np.nan if h['features'][k] is None else h['features'][k] for k in ALL_FEATURES])
                if h['code']!=r['code'] or h['date']!=r['date'] or not np.allclose(a,b,rtol=1e-5,atol=1e-7,equal_nan=True):mismatched+=1;continue
                selected[r['id']]=dict(basis='历史时间外筛选',pools=h['pools'])
            for pool,config in m['pools'].items():
                candidates=[r for r,pools in pending if pool in pools]
                if not candidates:continue
                pack=joblib.load(root/config['model']);matrix=pd.DataFrame([feature_rows[r['id']] for r in candidates])
                flags=score_mask(pack,matrix,config['spec'])
                for row,flag in zip(candidates,flags):
                    if flag:
                        s=selected.setdefault(row['id'],dict(basis='冻结模型筛选',pools=[]));s['pools'].append(pool)
            info=dict(version=m['version'],trained_through=m['trained_through'],selected=len(selected),historical_mismatch=mismatched,
                description='方向2：以60日触及+5%为目标的冻结筛选；90%为研究目标，历史时间外验证为16/19，尚未稳定达到90%。',
                pool_note='全量池暂无合格90%方案；全范围展示两池筛选并集，目前入选来自龙头池。')
            self.cached_key=key;self.cached=(selected,info);return self.cached
