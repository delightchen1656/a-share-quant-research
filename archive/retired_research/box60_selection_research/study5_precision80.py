"""New user target: D1..D60 adjusted high touches +5%, high-precision screens, pre2025 only."""
import datetime,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
import joblib
from study import HERE,INPUT,CORE,NAMES,sha,dump,features,label,metrics,wilson
from improve40_v2 import ModelBank,enrich,ALL_FEATURES,MODEL_NAMES,rank_reference,mask_rule,eligible,time_slices

TARGET=.05
QUANTILES=[.2,.4,.6,.8]
GATES=[None,.55,.60]
PROFILES={'precision80':dict(target=.80,coverage=.30,recall=.50,minimum=12),
          'precision85':dict(target=.85,coverage=.20,recall=.30,minimum=8)}

def relabel5(q,r,t):
    result=label(q,r,t)
    if result['label_status']!='complete':return result
    future=q.iloc[t+1:t+61];entry=float(future.open.iloc[0]);threshold=entry*(1+TARGET)
    touch=future.high.ge(threshold-1e-10).to_numpy();sellable=touch.copy();sellable[0]=False
    result.update(y=int(touch.any()),sellable_y=int(sellable.any()),d1_only_hit=bool(touch[0] and not sellable.any()),
        first_touch_day=int(np.flatnonzero(touch)[0]+1) if touch.any() else None,
        min_gain60=float(future.low.min()/entry-1),close_return60=float(future.close.iloc[-1]/entry-1))
    return result

def table5():
    manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['boundary']=='2024-12-31'
    for name,key in [('events.parquet','events_sha256'),('calendar.parquet','calendar_sha256')]:assert sha(INPUT/name)==manifest[key]
    events=pd.read_parquet(INPUT/'events.parquet');dates=pd.DatetimeIndex(pd.read_parquet(INPUT/'calendar.parquet').date)
    assert dates.max()<=pd.Timestamp('2024-12-31') and events.signal_date.le('2024-12-31').all()
    lookup={(rec['code'],rec['mode']):rec for rec in manifest['files']};rows=[]
    for code,group in events.groupby('code'):
        fs={}
        for mode in ['qfq','raw']:
            rec=lookup[(code,mode)];p=(INPUT/rec['relative_path']).resolve()
            assert p.is_relative_to(INPUT.resolve()) and sha(p)==rec['sha256']
            f=pd.read_parquet(p);assert pd.to_datetime(f.date).max()<=dates.max()
            fs[mode]=f.set_index('date').reindex(dates)
            for col in ['open','high','low','close','preclose','volume','amount']:
                if col in fs[mode]:fs[mode][col]=pd.to_numeric(fs[mode][col],errors='coerce')
        for e in group.to_dict('records'):
            t=dates.get_loc(pd.Timestamp(e['signal_date']))
            rows.append(dict(event_id=e['event_id'],code=code,name=e['name'],date=e['signal_date'],year=int(e['year']),
                is_leader=bool(e['is_leader']),**features(fs['qfq'],fs['raw'],t),**relabel5(fs['qfq'],fs['raw'],t)))
    return enrich(pd.DataFrame(rows).sort_values(['date','code']).reset_index(drop=True))

def catalog5():
    singles=[('signal_volume_ratio','>=',x) for x in [1.5,2.,3.]]+[
        ('signal_volume_ratio','<=',3.),('base_up_volume_share','>=',.55),('base_up_volume_share','>=',.60),('base_up_volume_share','>=',.65),
        ('base_width','>=',.08),('base_width','>=',.10),('base_width','<=',.10),
        ('atr14_pct','>=',.02),('atr14_pct','>=',.025),('atr14_pct','>=',.03),
        ('volatility20','>=',.02),('signal_return','>=',.025),('signal_return','>=',.04),('signal_return','<=',.05),
        ('base_late_volume_ratio','>=',1.),('base_late_volume_ratio','>=',1.2),
        ('base_return','<=',.02),('base_return','>=',0.),('dist_ma20','<=',.05),('dist_ma60','<=',0.),
        ('pre_return120','<=',-.15),('bull_volume_excess','>=',.05),('signal_volume_efficiency','>=',1.25),
        ('base_bull_max_to_signal','>=',1.),('base_bull_max_to_signal','<=',1.2)]
    catalog={'rule_all':[]}
    for i,condition in enumerate(singles):catalog[f'rule_single_{i}']=[condition]
    # Small, predeclared shape/liquidity combinations, not chosen from validation outcomes.
    for i,j in [(0,5),(0,10),(0,17),(5,10),(5,17),(5,24),(7,10),(10,17),(10,19),(11,21),(8,5),(15,19),(12,6),(14,26),(20,17)]:
        catalog[f'rule_pair_{i}_{j}']=[singles[i],singles[j]]
    return catalog

class Bank5(ModelBank):
    def masks(self,train,test):
        trained,refs=self.fit(train)
        scores={name:model.predict_proba(test[cols])[:,1] for name,(model,cols) in trained.items()}
        scores['rank_ensemble']=.5*rank_reference(refs['lr_all_02'],scores['lr_all_02'])+.25*rank_reference(refs['extra_trees'],scores['extra_trees'])+.25*rank_reference(refs['balanced_boost'],scores['balanced_boost'])
        masks={};specs={}
        for name in MODEL_NAMES:
            for q in QUANTILES:
                for gate in GATES:
                    key=f'model_{name}_q{q}_gate{gate}';threshold=float(np.quantile(refs[name],q));pick=scores[name]>=threshold
                    if gate is not None:pick &= test.base_up_volume_share.ge(gate).to_numpy()
                    masks[key]=pick;specs[key]=dict(model=name,quantile=q,threshold=threshold,up_volume_gate=gate)
        for key,conditions in catalog5().items():masks[key]=mask_rule(test,conditions);specs[key]=dict(conditions=conditions)
        return masks,specs

def choose5(inner,profile):
    config=PROFILES[profile];qualified=[];fallback=[]
    for key,g in inner.groupby('candidate'):
        m=metrics(g.y,g.pick)
        if m['selected']<max(config['minimum'],math.ceil(config['coverage']*m['n'])) or m['recall'] is None or m['recall']<config['recall']:continue
        lower=wilson(m['hits'],m['selected']);record=(m['coverage'],lower,m['precision'],key,m)
        fallback.append(record)
        if m['precision']>=config['target']-1e-12:qualified.append(record)
    if qualified:
        best=max(qualified,key=lambda x:(x[0],x[1],x[2],x[3]));met=True
    elif fallback:
        best=max(fallback,key=lambda x:(x[1],x[2],x[0],x[3]));met=False
    else:return dict(candidate='rule_all',inner_target_met=False,fallback=True,reason='insufficient inner temporal validation')
    return dict(candidate=best[3],inner_target_met=met,inner_metrics=best[4],inner_wilson95_lower=best[1],fallback=not met)

def inner_predictions(data,outer_year,bank):
    available=data[data.label_end.lt(f'{outer_year}-01-01')];rows=[];audit=[]
    for year in range(2020,outer_year):
        train,test=time_slices(available,year)
        if not eligible(train) or test.empty:continue
        assert train.label_end.max()<f'{year}-01-01' and test.label_end.max()<f'{outer_year}-01-01'
        masks,_=bank.masks(train,test)
        for name,mask in masks.items():rows.extend(dict(candidate=name,inner_year=year,y=int(y),pick=bool(p),event_id=e) for y,p,e in zip(test.y,mask,test.event_id))
        audit.append(dict(year=year,train_n=len(train),test_n=len(test),train_label_max=train.label_end.max(),test_label_max=test.label_end.max()))
    return pd.DataFrame(rows,columns=['candidate','inner_year','y','pick','event_id']),audit

def detailed_metrics(g):
    m=metrics(g.y,g.selected);picked=g[g.selected];negative=g[g.y.eq(0)];removed=g[~g.selected]
    m.update(negative_removed=int((~negative.selected).sum()),negative_total=len(negative),
        negative_removal_rate=float((~negative.selected).mean()) if len(negative) else None,
        nonpositive_peak_removed=int((removed.peak_gain60<=1e-10).sum()),
        selected_d1_only_hits=int(picked.d1_only_hit.sum()),
        sellable_touch_rate=float(picked.sellable_y.mean()) if len(picked) else None,
        mean_close_return60=float(picked.close_return60.mean()) if len(picked) else None,
        mean_min_gain60=float(picked.min_gain60.mean()) if len(picked) else None,
        wilson95_lower=wilson(m['hits'],m['selected']),
        target80_point_met=bool(m['precision'] is not None and m['precision']>=.8-1e-12))
    return m

def run_pool(data,out):
    out.mkdir();bank=Bank5();outer_rows=[];audits={};inner_all=[]
    for year in [2021,2022,2023,2024]:
        train,test=time_slices(data,year);assert eligible(train)
        inner,checks=inner_predictions(data,year,bank);inner['outer_year']=year;inner_all.append(inner)
        decisions={key:choose5(inner,key) for key in PROFILES}
        masks,specs=bank.masks(train,test)
        choices=dict(baseline='rule_all',old_volume60='rule_single_5',old_volume60_signal15='rule_pair_0_5',**{key:value['candidate'] for key,value in decisions.items()})
        for method,candidate in choices.items():
            for i,pick in zip(test.index,masks[candidate]):
                e=data.loc[i]
                outer_rows.append(dict(method=method,candidate=candidate,year=year,event_id=e.event_id,code=e.code,name=e['name'],date=e.date,
                    y=int(e.y),selected=bool(pick),peak_gain60=float(e.peak_gain60),sellable_y=int(e.sellable_y),d1_only_hit=bool(e.d1_only_hit),
                    close_return60=float(e.close_return60),min_gain60=float(e.min_gain60)))
        audits[str(year)]=dict(train_n=len(train),train_positive=int(train.y.sum()),train_label_max=train.label_end.max(),
            inner_checks=checks,decisions=decisions,selected_specs={key:specs[value] for key,value in choices.items()})
        print(out.name,year,'choices',choices,flush=True)
    pred=pd.DataFrame(outer_rows);pred.to_parquet(out/'outer_predictions.parquet',index=False)
    pd.concat(inner_all,ignore_index=True).to_parquet(out/'inner_candidates.parquet',index=False)
    result=dict(n=len(data),positives=int(data.y.sum()),base_rate=float(data.y.mean()),
        by_year={str(y):dict(n=len(g),positive=int(g.y.sum()),rate=float(g.y.mean())) for y,g in data.groupby('year')},
        nonpositive_peak=int(data.peak_gain60.le(1e-10).sum()),below5_positive_peak=int((data.peak_gain60.gt(0)&data.y.eq(0)).sum()),
        pooled={method:detailed_metrics(g) for method,g in pred.groupby('method')},
        yearly={method:{str(y):detailed_metrics(g) for y,g in group.groupby('year')} for method,group in pred.groupby('method')},folds=audits)
    # Final candidates use ONLY matured pre2025 observations, no posterior quote reads.
    inner,checks=inner_predictions(data,2025,bank)
    final={key:choose5(inner,key) for key in PROFILES};masks,specs=bank.masks(data,data.iloc[:1])
    trained,refs=bank.fit(data)
    freeze=dict(boundary='2024-12-31',target='D1..D60 adjusted HIGH >= D1 adjusted OPEN*1.05',
        not_new_blind=True,selection_checks=checks,profiles={key:dict(selection=value,spec=specs[value['candidate']]) for key,value in final.items()},
        features=ALL_FEATURES,model_code_sha256=sha(HERE/'improve40_v2.py'),code_sha256=sha(__file__))
    joblib.dump(dict(models=trained,references=refs,profiles=freeze['profiles'],features=ALL_FEATURES),out/'frozen_models_pre2025.joblib')
    dump(out/'FROZEN_CANDIDATES.json',freeze);dump(out/'RESULTS.json',result)
    for method in ['precision80','precision85']:
        selected=pred[pred.method.eq(method)&pred.selected].sort_values(['date','code'])
        lines=['历史外层时间验证选出名单；不代表今日选股。','信号日 | 代码 | 名称 | 是否触及5% | 60日最高涨幅 | D60收盘涨幅 | 当时内层选定条件']
        for e in selected.itertuples():lines.append(f'{e.date} | {e.code} | {e.name} | {e.y} | {e.peak_gain60*100:.2f}% | {e.close_return60*100:.2f}% | {e.candidate}')
        (out/(method+'_选出信号.txt')).write_text('\n'.join(lines),encoding='utf-8')
    return result,freeze

def report(results,freezes,out):
    def pct(x):return '—' if x is None else f'{100*x:.2f}%'
    lines=['箱体信号60日触及+5%：80%正确率筛选研究',
        '正确率=留下的信号中，D1..D60最高前复权价至少达到D1开盘1.05倍的比例；不是分类总体准确率，也不是期末或账户收益率。',
        '全量池=沪深主板全部箱体；龙头池=当前★龙头子集。两池不加保留标签过滤，独立拟合；只读inputs_pre2025。',
        '外层2021—2024逐年验证；内层只用外层年初前已成熟的更早标签，选择80%/85%目标条件，再应用到下一年。',
        '80%目标优先保留最多信号，同时内层至少保留30%、抓到50%正样本；85%目标至少保留20%、抓到30%。没有达标候选时报告降级，不假称达到目标。',
        '此前历史结果已经看过，本轮是新标签的历史探索复验，不是干净盲测。2025以后数据没有读取、没有参与调参。',
        '5%以内的小涨也归为未达标，不能把所有未触及5%的信号都称为完全不上涨。先跌很多后再涨5%也可能命中。',
        '另列D2以后可卖出触及率，排除仅D1触及而T+1无法卖出的情况。D60收盘收益与最低相对买价是风险诊断，不是模型特征。','']
    for pool,r in results.items():
        lines+=['全量池' if pool=='all' else '龙头池',f'完整样本{r["n"]}，触及5% {r["positives"]}，基础比例{pct(r["base_rate"])}；最高价从未高于买价{r["nonpositive_peak"]}次，涨过但不足5% {r["below5_positive_peak"]}次。',
            '方法 | 保留 | 命中 | 正确率 | 保留比例 | 抓取正样本 | 删除未达5% | 误删达5% | D2后可卖触及率 | D60收盘均值 | 最低价相对买价均值 | 95%Wilson下界']
        for method,m in r['pooled'].items():lines.append(f'{method} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {pct(m["coverage"])} | {pct(m["recall"])} | {m["negative_removed"]}/{m["negative_total"]} | {m["missed"]} | {pct(m["sellable_touch_rate"])} | {pct(m["mean_close_return60"])} | {pct(m["mean_min_gain60"])} | {pct(m["wilson95_lower"])}')
        lines+=['','分年（命中/留下数，括号内正确率）']
        for method in ['baseline','precision80','precision85']:
            lines.append(method+': '+'；'.join(f'{year} {m["hits"]}/{m["selected"]} ({pct(m["precision"])})' for year,m in r['yearly'][method].items()))
        lines+=['','仅用截至2024年数据冻结的下一步候选（不等同于上表逐年不同条件）',json.dumps(freezes[pool]['profiles'],ensure_ascii=False,indent=2),'','']
    (out/'5%触及率筛选研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('target5_precision80_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'REGISTERED_SPEC.json',dict(target=TARGET,inclusive=True,horizon=60,reference='D1 adjusted OPEN',target_accuracy=.80,
        profiles=PROFILES,rules=catalog5(),models=MODEL_NAMES,training_quantiles=QUANTILES,gates=GATES,
        source_input_sha256=sha(INPUT/'MANIFEST.json'),source_feature_sha256=sha(HERE/'study.py'),model_sha256=sha(HERE/'improve40_v2.py'),code_sha256=sha(__file__),
        boundary='2024-12-31',no_after2024_reads=True,validation='nested chronological annual2021..2024; mature label purge; no random split',
        selection='Among inner precision>=target and support/recall constraints: maximize coverage; tie Wilson lower. If none, maximize Wilson lower with constraints; no eligible->unfiltered baseline.',
        not_fresh_blind=True,current_universe_membership_retrospective=True,price_shape_not_economic_profit=True))
    table=table5();table.to_parquet(out/'features_and_labels.parquet',index=False)
    data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    assert data.label_end.le('2024-12-31').all()
    results={};freezes={}
    for pool,subset in [('all',data),('leaders',data[data.is_leader])]:results[pool],freezes[pool]=run_pool(subset,out/pool)
    dump(out/'SUMMARY.json',dict(label_status=table.label_status.value_counts().to_dict(),results={pool:dict(n=r['n'],positive=r['positives'],base_rate=r['base_rate'],pooled=r['pooled'],yearly=r['yearly']) for pool,r in results.items()}))
    report(results,freezes,out);dump(HERE/'holdout_restricted/LATEST_TARGET5.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),results={pool:dict(n=r['n'],positive=r['positives'],base_rate=r['base_rate'],pooled=r['pooled']) for pool,r in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
