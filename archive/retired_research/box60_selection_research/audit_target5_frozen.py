"""One-way new-label posterior: predict with frozen pre2025 models, never fit or select."""
from pathlib import Path
import datetime,json
import joblib
import numpy as np
import pandas as pd
from study import HERE,sha,dump,features,metrics
from study5_precision80 import relabel5,detailed_metrics
from improve40_v2 import enrich,mask_rule,rank_reference

ROOT=HERE.parent
def apply_frozen(bundle,data,spec):
    if 'conditions' in spec:return mask_rule(data,spec['conditions'])
    name=spec['model'];models=bundle['models'];refs=bundle['references']
    def score(key):
        model,cols=models[key];return model.predict_proba(data[cols])[:,1]
    if name=='rank_ensemble':values=.5*rank_reference(refs['lr_all_02'],score('lr_all_02'))+.25*rank_reference(refs['extra_trees'],score('extra_trees'))+.25*rank_reference(refs['balanced_boost'],score('balanced_boost'))
    else:values=score(name)
    result=values>=spec['threshold']
    if spec['up_volume_gate'] is not None:result &= data.base_up_volume_share.ge(spec['up_volume_gate']).to_numpy()
    return result

def main():
    source=Path(json.loads((HERE/'holdout_restricted/LATEST_TARGET5.json').read_text(encoding='utf-8'))['path'])
    frozen={};bundles={};hashes={}
    for pool in ['all','leaders']:
        f=source/pool/'FROZEN_CANDIDATES.json';model=source/pool/'frozen_models_pre2025.joblib'
        frozen[pool]=json.loads(f.read_text(encoding='utf-8'));assert frozen[pool]['boundary']=='2024-12-31'
        hashes[pool]=dict(candidate_sha256=sha(f),model_sha256=sha(model))
        bundles[pool]=joblib.load(model)
    current=ROOT/'leader_pattern_research/market_wide/holdout_restricted/CURRENT.json';b=json.loads(current.read_text(encoding='utf-8'))
    assert b['status']=='ok' and b['scope']=='SH_SZ_MAIN_BOARD_ONLY'
    for key in ['events','manifest','universe']:assert sha(b[key])==b[key+'_sha256']
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('posterior_target5_frozen_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'FROZEN_AUDIT_SPEC.json',dict(source=str(source),model_hashes=hashes,
        candidate_specs={p:frozen[p]['profiles'] for p in frozen},fixed_baselines=['all','volume60','volume60_signal15'],
        target='max HIGH D1..D60 >= D1 OPEN*1.05, qfq price label',entry='D1 OPEN',
        signal_period='2025..snapshot cutoff',cutoff=b['cutoff'],generation=b['generation'],events_sha256=b['events_sha256'],
        code_sha256=sha(__file__),no_fit=True,no_recalibration=True,no_posterior_selection=True,no_feedback=True,
        not_fresh_blind=True,current_membership_retrospective=True))
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(b['calendar']).date));dates=dates[dates<=b['cutoff']]
    events=pd.read_parquet(b['events'],columns=['event_id','code','name','signal_date','year','is_leader'])
    events=events[events.signal_date.ge('2025-01-01')&events.signal_date.le(b['cutoff'])]
    manifest=json.loads(Path(b['manifest']).read_text(encoding='utf-8'));lookup={(x['code'],x['mode']):x for x in manifest['files']}
    rows=[];hash_audit=[]
    for code,group in events.groupby('code'):
        fs={}
        for mode in ['qfq','raw']:
            rec=lookup[(code,mode)];p=Path(rec['path']);assert sha(p)==rec['snapshot_sha256']
            f=pd.read_parquet(p).set_index('date').reindex(dates)
            for col in ['open','high','low','close','preclose','volume','amount']:
                if col in f:f[col]=pd.to_numeric(f[col],errors='coerce')
            fs[mode]=f;hash_audit.append(dict(code=code,mode=mode,sha256=rec['snapshot_sha256']))
        for e in group.to_dict('records'):
            t=dates.get_loc(pd.Timestamp(e['signal_date']))
            rows.append(dict(event_id=e['event_id'],code=code,name=e['name'],date=e['signal_date'],year=int(e['year']),is_leader=bool(e['is_leader']),
                **features(fs['qfq'],fs['raw'],t),**relabel5(fs['qfq'],fs['raw'],t)))
    table=enrich(pd.DataFrame(rows));table.to_parquet(out/'posterior_features_and_labels.parquet',index=False)
    data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    results={};predictions=[]
    for pool,subset in [('all',data),('leaders',data[data.is_leader])]:
        picks={'baseline':np.ones(len(subset),bool),'volume60':subset.base_up_volume_share.ge(.6).to_numpy(),
            'volume60_signal15':(subset.base_up_volume_share.ge(.6)&subset.signal_volume_ratio.ge(1.5)).to_numpy()}
        for name,c in frozen[pool]['profiles'].items():picks[name]=apply_frozen(bundles[pool],subset,c['spec'])
        results[pool]={}
        for name,pick in picks.items():
            frame=subset.copy();frame['selected']=pick
            results[pool][name]=dict(overall=detailed_metrics(frame),by_year={str(y):detailed_metrics(g) for y,g in frame.groupby('year')})
            predictions.extend(dict(pool=pool,method=name,event_id=e.event_id,code=e.code,date=e.date,year=e.year,y=int(e.y),selected=bool(e.selected),
                peak_gain60=float(e.peak_gain60),close_return60=float(e.close_return60)) for e in frame.itertuples())
    pd.DataFrame(predictions).to_parquet(out/'posterior_predictions.parquet',index=False)
    report=dict(cutoff=b['cutoff'],source=str(source),label_status=table.label_status.value_counts().to_dict(),results=results)
    dump(out/'SUMMARY.json',report);dump(out/'QUOTE_HASH_AUDIT.json',hash_audit)
    def pct(x):return '—' if x is None else f'{100*x:.2f}%'
    lines=['5%触及目标：冻结后单向后验核验',f'行情截至{b["cutoff"]}；只检查2025年以来的箱体事件。',
        '候选读取前已冻结。只做predict，不训练、不重选参数、不用后验结果决定哪个版本投入优化。',
        '模型阈值来自研发期训练分数，未经后验重新校准。最高触及+5%不等于实际交易盈利5%。',
        '当前龙头名单回看有归属偏差；此前已经见过部分后验汇总，本次不称作全新盲测。',
        '标签不完整与缺价单列，不把未成熟样本记为失败。','']
    for pool in ['all','leaders']:
        lines+=['全量池' if pool=='all' else '龙头池','方法 | 年份 | 保留 | 命中 | 正确率 | 保留比例 | 正样本误删 | D2以后可卖出触及率']
        for name,result in results[pool].items():
            for year,m in [('合计',result['overall'])]+list(result['by_year'].items()):
                lines.append(f'{name} | {year} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {pct(m["coverage"])} | {m["missed"]} | {pct(m["sellable_touch_rate"])}')
        lines+=['']
    lines+=['标签可用性 '+json.dumps(report['label_status'],ensure_ascii=False)]
    (out/'5%目标单向后验报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    dump(HERE/'holdout_restricted/LATEST_TARGET5_POSTERIOR.json',dict(path=str(out),source=str(source)))
    print(json.dumps(dict(output=str(out),cutoff=b['cutoff'],label_status=report['label_status'],overall={p:{k:v['overall'] for k,v in methods.items()} for p,methods in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
