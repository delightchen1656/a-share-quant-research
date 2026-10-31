"""Nested historical time validation of >40% box screens, two independently trained pools."""
import datetime,math,json
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import ExtraTreesClassifier,HistGradientBoostingClassifier
from study import HERE,INPUT,CORE,NAMES,sha,dump,build_table,metrics
from study40_two_pools import relabel

DERIVED=['bull_bear_max_ratio','bull_volume_excess','base_return_in_width','signal_volume_efficiency',
         'late_volume_compression','ma20_distance_atr','pre120_vol_scaled']
ALL_FEATURES=list(NAMES)+DERIVED
Q_LEVELS=[.6,.7,.8,.9]
GATES=[None,.55,.60]
MODEL_NAMES=['lr_core_005','lr_core_02','lr_all_005','lr_all_02','extra_trees','balanced_boost','rank_ensemble']
TITLES={'baseline':'原规则：箱内阳线量占比≥60%', 'nested_rule':'内层选择组合规则',
        'nested_model':'内层选择模型及阈值','nested_balanced':'内层综合选择（均衡）','nested_focused':'内层综合选择（集中）',
        'fixed_late':'固定：阳线量≥60%且后段量≥前段量','fixed_excess':'固定：阳线量≥60%且阳线量份额−阳线天数份额≥5%'}

def enrich(data):
    d=data.copy()
    d['bull_bear_max_ratio']=d.base_bull_max_to_signal/d.base_bear_max_to_signal
    d['bull_volume_excess']=d.base_up_volume_share-d.base_up_day_share
    d['base_return_in_width']=d.base_return/d.base_width
    d['signal_volume_efficiency']=d.signal_volume_ratio/d.signal_range_expansion
    d['late_volume_compression']=d.base_late_volume_ratio/d.base_range_compression
    d['ma20_distance_atr']=d.dist_ma20/d.atr14_pct
    d['pre120_vol_scaled']=d.pre_return120/(d.volatility20*np.sqrt(120))
    d[ALL_FEATURES]=d[ALL_FEATURES].replace([np.inf,-np.inf],np.nan)
    return d

def rule_catalog():
    second=[('base_late_volume_ratio','>=',1.),('base_late_volume_ratio','>=',1.2),
        ('base_volume_ratio','<=',1.5),('signal_volume_ratio','>=',1.5),('signal_volume_ratio','<=',3.),
        ('base_return','<=',.02),('base_width','>=',.08),('dist_ma20','<=',.05),('pre_return120','<=',-.15),
        ('atr14_pct','<=',.035),('base_bull_max_to_signal','>=',1.),('bull_volume_excess','>=',.05),
        ('base_return_in_width','<=',.25),('bull_bear_max_ratio','>=',1.2),('signal_volume_efficiency','>=',1.25)]
    catalog={}
    for anchor in [.55,.60,.65]:
        base=[('base_up_volume_share','>=',anchor)]
        catalog[f'rule_a{anchor}']=base
        for j,condition in enumerate(second):catalog[f'rule_a{anchor}_s{j}']=base+[condition]
    for i,(a,b) in enumerate([(0,3),(8,11),(6,7)]):catalog[f'rule_three_{i}']=[('base_up_volume_share','>=',.6),second[a],second[b]]
    return catalog

def mask_rule(data,conditions):
    mask=np.ones(len(data),bool)
    for key,op,value in conditions:mask &= (data[key].ge(value) if op=='>=' else data[key].le(value)).fillna(False).to_numpy()
    return mask

def eligible(train):return len(train)>=25 and train.y.sum()>=3 and train.y.nunique()==2

def time_slices(data,year):
    start=f'{year}-01-01';return data[data.label_end.lt(start)],data[data.year.eq(year)]

def rank_reference(reference,values):return np.searchsorted(np.sort(reference),values,side='right')/len(reference)

class ModelBank:
    def __init__(self):self.cache={};self.fit_audits=[]
    def fit(self,train):
        key=tuple(train.event_id)
        if key in self.cache:return self.cache[key]
        n=len(train);trained={};refs={}
        for name,cols,c in [('lr_core_005',CORE,.05),('lr_core_02',CORE,.2),('lr_all_005',ALL_FEATURES,.05),('lr_all_02',ALL_FEATURES,.2)]:
            model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=c,class_weight='balanced',max_iter=3000,random_state=37))
            model.fit(train[cols],train.y.astype(int));trained[name]=(model,cols);refs[name]=model.predict_proba(train[cols])[:,1]
        extra=make_pipeline(SimpleImputer(strategy='median'),ExtraTreesClassifier(n_estimators=128,max_depth=3,
            min_samples_leaf=max(5,math.ceil(n*.06)),max_features=.8,class_weight='balanced',random_state=37,n_jobs=2))
        extra.fit(train[ALL_FEATURES],train.y.astype(int));trained['extra_trees']=(extra,ALL_FEATURES);refs['extra_trees']=extra.predict_proba(train[ALL_FEATURES])[:,1]
        boost=make_pipeline(SimpleImputer(strategy='median'),HistGradientBoostingClassifier(max_iter=60,max_depth=2,max_leaf_nodes=4,
            min_samples_leaf=max(8,math.ceil(n*.05)),l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=37))
        counts=np.bincount(train.y.to_numpy(int));weights=np.array([len(train)/(2*counts[y]) for y in train.y.to_numpy(int)])
        boost.fit(train[ALL_FEATURES],train.y.astype(int),histgradientboostingclassifier__sample_weight=weights)
        trained['balanced_boost']=(boost,ALL_FEATURES);refs['balanced_boost']=boost.predict_proba(train[ALL_FEATURES])[:,1]
        refs['rank_ensemble']=.5*rank_reference(refs['lr_all_02'],refs['lr_all_02'])+.25*rank_reference(refs['extra_trees'],refs['extra_trees'])+.25*rank_reference(refs['balanced_boost'],refs['balanced_boost'])
        record=(trained,refs);self.cache[key]=record
        self.fit_audits.append(dict(train_n=n,train_positive=int(train.y.sum()),train_label_max=train.label_end.max(),train_event_ids=list(train.event_id)))
        return record
    def masks(self,train,test):
        trained,refs=self.fit(train);scores={name:model.predict_proba(test[cols])[:,1] for name,(model,cols) in trained.items()}
        scores['rank_ensemble']=.5*rank_reference(refs['lr_all_02'],scores['lr_all_02'])+.25*rank_reference(refs['extra_trees'],scores['extra_trees'])+.25*rank_reference(refs['balanced_boost'],scores['balanced_boost'])
        masks={};specs={}
        for name in MODEL_NAMES:
            for q in Q_LEVELS:
                for gate in GATES:
                    key=f'model_{name}_q{q}_gate{gate}'
                    threshold=float(np.quantile(refs[name],q));pick=scores[name]>=threshold
                    if gate is not None:pick &= test.base_up_volume_share.ge(gate).to_numpy()
                    masks[key]=pick;specs[key]=dict(model=name,training_quantile=q,actual_threshold=threshold,gate=gate)
        return masks,specs

def candidate_masks(bank,train,test):
    masks,specs=bank.masks(train,test)
    for name,conditions in rule_catalog().items():masks[name]=mask_rule(test,conditions);specs[name]=dict(conditions=conditions)
    return masks,specs

def objective(y,pick,focused=False):
    m=metrics(y,pick);minimum=max(8,math.ceil(len(y)*(.10 if focused else .15)))
    if m['selected']<minimum or m['coverage']>.65 or m['recall'] is None or m['recall']<(.25 if focused else .40):return None
    p=m['precision'];r=m['recall'];value=1.25*p*r/(.25*p+r) if p and r else 0.
    return value,m

def choose(inner_rows,family='all',focused=False):
    ranked=[]
    reference=inner_rows[inner_rows.candidate.eq('rule_a0.6')]
    reference_precision=metrics(reference.y,reference.pick)['precision'] if len(reference) else None
    for name,g in inner_rows.groupby('candidate'):
        if family=='rule' and not name.startswith('rule_'):continue
        if family=='model' and not name.startswith('model_'):continue
        value=objective(g.y,g.pick,focused)
        if value is not None:
            score,m=value
            if reference_precision is not None and m['precision']<reference_precision-1e-12:continue
            ranked.append((score,m['hits'],-m['selected'],name,m))
    if not ranked:return dict(candidate='rule_a0.6',fallback=True,reason='no candidate met inner recall/coverage constraints')
    best=max(ranked,key=lambda x:(x[0],x[1],x[2],x[3]))
    return dict(candidate=best[3],inner_f05=best[0],inner_metrics=best[4],fallback=False)

def inner_predictions(data,outer_year,bank):
    available=data[data.label_end.lt(f'{outer_year}-01-01')];rows=[];audit=[]
    for year in range(2020,outer_year):
        train,test=time_slices(available,year)
        if not eligible(train) or test.empty:continue
        assert train.label_end.max()<f'{year}-01-01' and test.label_end.max()<f'{outer_year}-01-01'
        masks,_=candidate_masks(bank,train,test)
        for name,mask in masks.items():
            rows+= [dict(candidate=name,fold=year,event_id=event,y=int(y),pick=bool(p)) for event,y,p in zip(test.event_id,test.y,mask)]
        audit.append(dict(year=year,train_n=len(train),test_n=len(test),train_label_max=train.label_end.max(),test_label_max=test.label_end.max()))
    return pd.DataFrame(rows,columns=['candidate','fold','event_id','y','pick']),audit

def run_pool(data,out):
    out.mkdir();bank=ModelBank();outer_rows=[];audits={};all_inner=[]
    for year in [2021,2022,2023,2024]:
        train,test=time_slices(data,year)
        assert eligible(train) and not test.empty
        inner,audit=inner_predictions(data,year,bank)
        inner['outer_year']=year;all_inner.append(inner)
        decisions={
            'nested_rule':choose(inner,'rule'), 'nested_model':choose(inner,'model'),
            'nested_balanced':choose(inner), 'nested_focused':choose(inner,focused=True)}
        masks,specs=candidate_masks(bank,train,test)
        choices={k:v['candidate'] for k,v in decisions.items()}
        choices.update(baseline='rule_a0.6',fixed_late='rule_a0.6_s0',fixed_excess='rule_a0.6_s11')
        for method,candidate in choices.items():
            for index,pick in zip(test.index,masks[candidate]):
                row=data.loc[index];outer_rows.append(dict(method=method,year=year,event_id=row.event_id,code=row.code,name=row['name'],date=row.date,
                    y=int(row.y),peak_gain60=float(row.peak_gain60),selected=bool(pick),candidate=candidate))
        audits[str(year)]=dict(train_n=len(train),train_positive=int(train.y.sum()),train_label_max=train.label_end.max(),test_n=len(test),
            inner_time_audit=audit,decisions=decisions,selected_specs={k:specs[v] for k,v in choices.items()})
        print(out.name,'outer',year,'selected',choices,flush=True)
    predictions=pd.DataFrame(outer_rows);predictions.to_parquet(out/'outer_predictions.parquet',index=False)
    pd.concat(all_inner,ignore_index=True).to_parquet(out/'inner_candidate_predictions.parquet',index=False)
    result=dict(available=len(data),positive=int(data.y.sum()),folds=audits,
        pooled={method:metrics(g.y,g.selected) for method,g in predictions.groupby('method')},
        yearly={method:{str(y):metrics(g.y,g.selected) for y,g in group.groupby('year')} for method,group in predictions.groupby('method')})
    dump(out/'RESULTS.json',result);dump(out/'MODEL_FIT_AUDIT.json',bank.fit_audits)
    return result

def report(results,out):
    def pct(x):return '—' if x is None else f'{100*x:.2f}%'
    lines=['40%目标继续优化：全量池与龙头池，嵌套时间验证v2',
        '目标：信号次日开盘至后60个交易日最高前复权价涨幅>40%；不是交易收益/胜率。',
        '只读inputs_pre2025白名单。两池独立训练；不新增保留标签过滤，不删100%以上极端涨幅。',
        '由于此前已查看2019—2024结果，本轮属于历史探索复验，不是新的盲测；没有使用2025以后数据。',
        '外层2021—2024逐年验证；每个外层年初，仅用已成熟标签的更早数据。内层逐年验证选择规则/模型/训练阈值，外层结果不参与选择。',
        '均衡选择要求内层抓取率>=40%、覆盖率>=15%；集中选择抓取率>=25%、覆盖率>=10%；均至少8个。候选内层命中率不得低于原规则。',
        '实际约束：均衡选中数>=max(8,ceil(15%*内层样本))；集中>=max(8,ceil(10%*内层样本))；均限制覆盖<=65%。',
        '满足约束后最大化内层F0.5（优先命中率，兼顾抓取率），不满足则退回原60%阳线量规则。','']
    for pool,r in results.items():
        lines+=['全量池' if pool=='all' else '龙头池','方法 | 选出 | 命中 | 命中率 | 抓取率 | 漏掉 | 相对不筛选倍数']
        for key in TITLES:
            m=r['pooled'][key];lines.append(f'{TITLES[key]} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {pct(m["recall"])} | {m["missed"]} | {m["lift"]:.2f}')
        lines+=['','均衡与集中分年（本年不筛选基准同时列出）']
        for key in ['baseline','nested_rule','nested_model','nested_balanced','nested_focused']:
            lines.append(TITLES[key]+': '+'；'.join(f'{y} {m["hits"]}/{m["selected"]}={pct(m["precision"])}，抓取{pct(m["recall"])}，基准{pct(m["base_rate"])}' for y,m in r['yearly'][key].items()))
        lines+=['','每年在内层确定的选择']
        for year,f in r['folds'].items():
            lines.append(year+' '+json.dumps(f['selected_specs'],ensure_ascii=False))
        lines+=['','']
    (out/'优化研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('improve40_nested_v2_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'REGISTERED_SPEC.json',dict(target=.40,boundary='2024-12-31',pools=['all','leaders'],code_sha256=sha(__file__),
        source_feature_code_sha256=sha(HERE/'study.py'),input_manifest_sha256=sha(INPUT/'MANIFEST.json'),
        rules=rule_catalog(),model_names=MODEL_NAMES,feature_names=ALL_FEATURES,quantiles=Q_LEVELS,gates=GATES,
        model_setup='LR balanced C=.05/.2 core/all; ExtraTrees128 depth3 minleaf6%; balanced HGB60 depth2 leaves4 minleaf5%; fixed rank ensemble .5LR/.25ET/.25GB',
        selection='Inner chronological predictions only. Precision >= original60%volume-rule inner precision. Max F0.5 subject to balanced recall>=.4 count>=max(8,15%N), focused recall>=.25 count>=max(8,10%N), coverage<=65%. No qualifying candidate->old60%volume rule.',
        outer_years=[2021,2022,2023,2024],inner_years='2020..outer_year-1, only labels matured before outer start',
        repeated_historical_validation=True,not_new_blind=True,no_future_feedback_into_fold_selection=True,no_after2024_data=True,
        price_shape_target_not_cash_account=True,no_extreme_pruning=True))
    table=enrich(relabel(build_table()));table.to_parquet(out/'features_and_labels.parquet',index=False)
    data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    results={}
    for pool,subset in [('all',data),('leaders',data[data.is_leader])]:results[pool]=run_pool(subset,out/pool)
    dump(out/'SUMMARY.json',{pool:r['pooled'] for pool,r in results.items()});report(results,out)
    dump(HERE/'holdout_restricted/LATEST_IMPROVE40.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),summary={pool:r['pooled'] for pool,r in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
