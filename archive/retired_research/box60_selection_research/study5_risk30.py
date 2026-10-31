"""Pre2025 nested time research: touch+5% AND avoid low below entry-30%."""
import datetime,json,math
import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import ExtraTreesClassifier
from study import HERE,INPUT,sha,dump,metrics,wilson
from study5_precision80 import table5,Bank5,catalog5
from improve40_v2 import ALL_FEATURES,mask_rule,time_slices,eligible,rank_reference

def risk_labels(data):
    d=data.copy();d['drop30']=d.min_gain60.lt(-.30-1e-10).astype(int)
    d['safe_y']=(d.y.eq(1)&d.drop30.eq(0)).astype(int)
    return d

def risk_order(data):
    manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'));lookup={(r['code'],r['mode']):r for r in manifest['files']}
    dates=pd.DatetimeIndex(pd.read_parquet(INPUT/'calendar.parquet').date);rows=[]
    for code,g in data.groupby('code'):
        rec=lookup[(code,'qfq')];p=(INPUT/rec['relative_path']).resolve();assert p.is_relative_to(INPUT.resolve()) and sha(p)==rec['sha256']
        q=pd.read_parquet(p).set_index('date').reindex(dates)
        for e in g.itertuples():
            t=dates.get_loc(pd.Timestamp(e.date));f=q.iloc[t+1:t+61];hits=np.flatnonzero(f.low.to_numpy(float)<float(f.open.iloc[0])*.7-1e-10)
            drop=int(hits[0]+1) if len(hits) else None;touch=e.first_touch_day if np.isfinite(e.first_touch_day) else None
            rows.append(dict(event_id=e.event_id,first_drop30_day=drop,
                drop_before5=bool(drop is not None and (touch is None or drop<touch)),
                drop_same_day5=bool(drop is not None and touch is not None and drop==touch),
                drop_after5=bool(drop is not None and touch is not None and drop>touch)))
    return data.merge(pd.DataFrame(rows),on='event_id',validate='one_to_one')

class RiskBank:
    def __init__(self):self.safe=Bank5();self.risk_cache={}
    def risk_pack(self,train):
        key=tuple(train.event_id)
        if key in self.risk_cache:return self.risk_cache[key]
        y=train.drop30.astype(int)
        if min(int(y.sum()),len(y)-int(y.sum()))<3:
            pack=dict(models=None,reference=np.array([float(y.mean())]),prior=float((y.sum()+.5)/(len(y)+1)))
        else:
            models={
                'lr':make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=.05,class_weight='balanced',max_iter=3000,random_state=61)),
                'extra':make_pipeline(SimpleImputer(strategy='median'),ExtraTreesClassifier(n_estimators=128,max_depth=3,min_samples_leaf=max(5,math.ceil(len(train)*.08)),max_features=.8,class_weight='balanced',random_state=61,n_jobs=2))}
            reference={}
            for name,m in models.items():m.fit(train[ALL_FEATURES],y);reference[name]=m.predict_proba(train[ALL_FEATURES])[:,1]
            mix=.5*rank_reference(reference['lr'],reference['lr'])+.5*rank_reference(reference['extra'],reference['extra'])
            pack=dict(models=models,reference=reference,mix_reference=mix)
        self.risk_cache[key]=pack;return pack
    def masks(self,train,test):
        safe_train=train.copy();safe_train['y']=safe_train.safe_y.astype(int)
        if not eligible(safe_train):
            masks={k:mask_rule(test,v) for k,v in catalog5().items()};specs={k:dict(conditions=v) for k,v in catalog5().items()}
        else:masks,specs=self.safe.masks(safe_train,test)
        caps={'atr25':[('atr14_pct','<=',.025)],'atr30':[('atr14_pct','<=',.03)],'atr35':[('atr14_pct','<=',.035)],
            'vol25':[('volatility20','<=',.025)],'decline20':[('decline_return','>=',-.20)],'prior120_25':[('pre_return120','>=',-.25)]}
        for key,conditions in caps.items():masks['riskrule_'+key]=mask_rule(test,conditions);specs['riskrule_'+key]=dict(conditions=conditions)
        for key,conditions in caps.items():
            c=conditions+[('base_up_volume_share','>=',.6)];masks['riskrule_'+key+'_bull60']=mask_rule(test,c);specs['riskrule_'+key+'_bull60']=dict(conditions=c)
        pack=self.risk_pack(train)
        if pack['models'] is not None:
            scores={k:m.predict_proba(test[ALL_FEATURES])[:,1] for k,m in pack['models'].items()}
            risk_score=.5*rank_reference(pack['reference']['lr'],scores['lr'])+.5*rank_reference(pack['reference']['extra'],scores['extra'])
            for q in [.6,.8]:
                threshold=float(np.quantile(pack['mix_reference'],q));risk_mask=risk_score<=threshold
                for name,mask in list(masks.items()):
                    if '__riskq' in name:continue
                    key=name+f'__riskq{q}';masks[key]=mask&risk_mask;specs[key]=dict(base=specs[name],risk_quantile=q,risk_threshold=threshold)
        return masks,specs

def candidate_metrics(g):
    m=metrics(g.y,g.pick);picked=g[g.pick];drop=int(picked.drop30.sum());safe=int(picked.safe_y.sum())
    m.update(drop30_n=drop,drop30_rate=drop/m['selected'] if m['selected'] else None,safe_hits=safe,
        safe_precision=safe/m['selected'] if m['selected'] else None,safe_wilson=wilson(safe,m['selected']),
        drop30_total=int(g.drop30.sum()),drop30_removed=int(g.loc[~g.pick,'drop30'].sum()))
    return m

def choose_risk(inner,policy):
    candidates=[];qualified=[]
    for key,g in inner.groupby('candidate'):
        m=candidate_metrics(g)
        if m['selected']<max(12,math.ceil(.25*m['n'])) or m['recall'] is None or m['recall']<.4:continue
        candidates.append((key,m))
        if policy=='joint80':good=m['safe_precision']>=.8-1e-12 and m['drop30_rate']<=.05+1e-12
        else:good=m['precision']>=.75-1e-12
        if good:qualified.append((key,m))
    if qualified:
        if policy=='joint80':best=max(qualified,key=lambda x:(x[1]['coverage'],x[1]['safe_wilson'],-x[1]['drop30_rate'],x[0]))
        else:best=max(qualified,key=lambda x:(-x[1]['drop30_rate'],x[1]['safe_wilson'],x[1]['coverage'],x[0]))
        target=True
    elif candidates:best=max(candidates,key=lambda x:(x[1]['safe_wilson']-x[1]['drop30_rate'],x[1]['coverage'],x[0]));target=False
    else:return dict(candidate='rule_all',inner_target_met=False,fallback=True)
    return dict(candidate=best[0],inner_target_met=target,inner_metrics=best[1],fallback=not target)

def inner_rows(data,outer,bank):
    available=data[data.label_end.lt(f'{outer}-01-01')];frames=[];checks=[]
    for year in range(2020,outer):
        train,test=time_slices(available,year)
        if not eligible(train) or test.empty:continue
        masks,_=bank.masks(train,test)
        for key,pick in masks.items():frames.append(pd.DataFrame(dict(candidate=key,year=year,event_id=test.event_id.to_numpy(),y=test.y.to_numpy(int),safe_y=test.safe_y.to_numpy(int),drop30=test.drop30.to_numpy(int),pick=pick)))
        checks.append(dict(year=year,train_label_max=train.label_end.max(),validation_label_max=test.label_end.max()))
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['candidate','year','event_id','y','safe_y','drop30','pick']),checks

def run_pool(data,out):
    out.mkdir();bank=RiskBank();predictions=[];folds={}
    for year in [2021,2022,2023,2024]:
        train,test=time_slices(data,year);inner,checks=inner_rows(data,year,bank)
        choices={p:choose_risk(inner,p) for p in ['joint80','risk_first']};masks,specs=bank.masks(train,test)
        methods=dict(baseline='rule_all',old_two='rule_pair_0_5',**{p:c['candidate'] for p,c in choices.items()})
        for method,key in methods.items():
            f=test[['event_id','code','name','date','year','y','safe_y','drop30','drop_before5','drop_after5','drop_same_day5','min_gain60','close_return60']].copy()
            f['method']=method;f['candidate']=key;f['pick']=masks[key];predictions.append(f)
        folds[str(year)]=dict(train_n=len(train),train_label_max=train.label_end.max(),inner_checks=checks,choices=choices,specs={p:specs[k] for p,k in methods.items()})
        print(out.name,year,{p:c['candidate'] for p,c in choices.items()},flush=True)
    pred=pd.concat(predictions,ignore_index=True);pred.to_parquet(out/'outer_predictions.parquet',index=False)
    def summary(g):
        m=candidate_metrics(g);s=g[g.pick]
        m.update(before5_n=int(s.drop_before5.sum()),after5_n=int(s.drop_after5.sum()),same_day_n=int(s.drop_same_day5.sum()),
            mean_min_gain=float(s.min_gain60.mean()) if len(s) else None,mean_close60=float(s.close_return60.mean()) if len(s) else None)
        return m
    result=dict(n=len(data),hits5=int(data.y.sum()),drop30=int(data.drop30.sum()),safe5=int(data.safe_y.sum()),
        pooled={k:summary(g) for k,g in pred.groupby('method')},yearly={k:{str(y):summary(g) for y,g in f.groupby('year')} for k,f in pred.groupby('method')},folds=folds)
    inner,checks=inner_rows(data,2025,bank);final={p:choose_risk(inner,p) for p in ['joint80','risk_first']};masks,specs=bank.masks(data,data.iloc[:1])
    safe_train=data.copy();safe_train['y']=safe_train.safe_y
    trained,refs=bank.safe.fit(safe_train);risk=bank.risk_pack(data)
    frozen=dict(boundary='2024-12-31',policies={p:dict(choice=c,spec=specs[c['candidate']]) for p,c in final.items()},selection_checks=checks,
        target='touch5 AND min gain60 >= -30%; no future risk fields in features',features=ALL_FEATURES,not_new_blind=True)
    dump(out/'FROZEN_CANDIDATES.json',frozen);joblib.dump(dict(safe_models=trained,safe_refs=refs,risk=risk,policies=frozen['policies']),out/'frozen_models_pre2025.joblib')
    dump(out/'RESULTS.json',result)
    return result

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('target5_risk30_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'REGISTERED_SPEC.json',dict(boundary='2024-12-31',touch5='D1..D60 qfq HIGH >= D1 OPEN*1.05',
        drop30='D1..D60 qfq LOW < D1 OPEN*0.70; entry-relative, not peak-to-trough drawdown',
        joint='touch5 AND NOT drop30',joint_policy='inner joint precision>=80%, drop30<=5%; maximize coverage',
        risk_first_policy='inner hit5 precision>=75%; minimize drop30, tie joint Wilson and coverage',
        support='inner count>=max(12,25%N), hit5 recall>=40%; no qualifying->report fallback',
        models='safe5 head: existing7 fixed models; risk30 head LR .05 + ExtraTrees128 depth3 leaf8%; risk train-rank q60/q80 caps',
        validation='nested chronological2021..2024; inner only matured labels before outer start; no random split',
        input_manifest_sha256=sha(INPUT/'MANIFEST.json'),source5_sha256=sha(HERE/'study5_precision80.py'),
        code_sha256=sha(__file__),no_after2024_reads=True,no_posterior_feedback=True,not_fresh_blind=True))
    table=table5();data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    data=risk_order(risk_labels(data));data.to_parquet(out/'features_and_labels.parquet',index=False)
    results={}
    for pool,subset in [('all',data),('leaders',data[data.is_leader])]:results[pool]=run_pool(subset,out/pool)
    dump(out/'SUMMARY.json',{pool:r['pooled'] for pool,r in results.items()})
    def pct(x):return '—' if x is None else f'{100*x:.2f}%'
    lines=['5%触及与跌超30%双目标筛选研究','只用截至2024年底的白名单；此前历史已经看过，是探索性历史时间复验，不是新盲测。',
        '跌超30%=D1买入开盘至D60最低价<买价70%，不是高点回撤。全窗跌超30%即计风险，即使它先涨5%后再跌。',
        '另列先跌后涨/先涨后跌顺序。仅同日高低价无法判断顺序的情况单列。','']
    for pool,r in results.items():
        lines+=['全量池' if pool=='all' else '龙头池','方法 | 保留 | 命中5% | 命中率 | 跌超30% | 风险率 | 同时命中且避险率 | 删除风险数/全部风险 | 误删5% | 先跌30% | 先涨5%再跌30%']
        for key,m in r['pooled'].items():lines.append(f'{key} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {m["drop30_n"]} | {pct(m["drop30_rate"])} | {pct(m["safe_precision"])} | {m["drop30_removed"]}/{m["drop30_total"]} | {m["missed"]} | {m["before5_n"]} | {m["after5_n"]}')
        lines+=['分年结果']
        for key,years in r['yearly'].items():lines.append(key+': '+'；'.join(f'{y} 5%命中{m["hits"]}/{m["selected"]}，跌30% {m["drop30_n"]}/{m["selected"]}' for y,m in years.items()))
        lines+=['']
    (out/'触及5%并规避30%下跌研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    dump(HERE/'holdout_restricted/LATEST_TARGET5_RISK30.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),summary={p:r['pooled'] for p,r in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
