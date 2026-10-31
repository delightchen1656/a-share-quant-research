"""Two independent objectives: lower drop30 probability, OR raise touch5 precision to90%."""
import datetime,json,math
import numpy as np
import pandas as pd
import joblib
from study import HERE,INPUT,sha,dump,metrics,wilson
from study5_precision80 import table5,Bank5,catalog5
from study5_risk30 import risk_labels,risk_order,RiskBank
from improve40_v2 import ALL_FEATURES,mask_rule,time_slices,eligible,rank_reference

def choose_independent(inner,goal):
    candidates=[]
    for key,g in inner.groupby('candidate'):
        if (goal=='risk30' and not key.startswith('risk_')) or (goal!='risk30' and not key.startswith('hit_')):continue
        m=metrics(g.y,g.pick);picked=g[g.pick];bad=int(picked.drop30.sum())
        m.update(drop30_n=bad,drop30_rate=bad/m['selected'] if m['selected'] else None)
        minimum=max(12,math.ceil(m['n']*(.4 if goal=='risk30' else .15)))
        if m['selected']<minimum:continue
        if goal!='risk30' and (m['recall'] is None or m['recall']<.2):continue
        m['risk95_upper']=1-wilson(m['selected']-bad,m['selected']);m['hit95_lower']=wilson(m['hits'],m['selected'])
        candidates.append((key,m))
    if goal=='risk30':
        if not candidates:return dict(candidate='risk_all',goal_met=False,fallback=True)
        best=min(candidates,key=lambda x:(x[1]['risk95_upper'],-x[1]['coverage'],x[0]));met=True
    else:
        qualified=[x for x in candidates if x[1]['precision']>=.9-1e-12]
        if qualified:best=max(qualified,key=lambda x:(x[1]['coverage'],x[1]['hit95_lower'],x[0]));met=True
        elif goal=='precision90':return dict(candidate='abstain',goal_met=False,fallback=True,reason='no inner90% screen with sufficient support; issue no signal')
        elif candidates:best=max(candidates,key=lambda x:(x[1]['hit95_lower'],x[1]['precision'],x[1]['coverage'],x[0]));met=False
        else:return dict(candidate='abstain',goal_met=False,fallback=True)
    return dict(candidate=best[0],goal_met=met,inner_metrics=best[1],fallback=not met)

class IndependentBank:
    def __init__(self):self.hit=Bank5();self.risk=RiskBank()
    def masks(self,train,test):
        hit_masks,hit_specs=self.hit.masks(train,test)
        masks={'hit_'+k:v for k,v in hit_masks.items()};specs={'hit_'+k:v for k,v in hit_specs.items()}
        caps=[('atr14_pct','<=',v) for v in [.02,.025,.03,.035]]+[
            ('volatility20','<=',v) for v in [.015,.02,.025,.03]]+[
            ('decline_return','>=',-.2),('pre_return120','>=',-.25),('base_width','<=',.10),('signal_return','<=',.05)]
        masks['risk_all']=np.ones(len(test),bool);specs['risk_all']=dict(conditions=[])
        for i,c in enumerate(caps):
            masks[f'risk_rule_{i}']=mask_rule(test,[c]);specs[f'risk_rule_{i}']=dict(conditions=[c])
        for i,j in [(2,5),(1,8),(2,9),(3,10),(6,9)]:
            masks[f'risk_pair_{i}_{j}']=mask_rule(test,[caps[i],caps[j]]);specs[f'risk_pair_{i}_{j}']=dict(conditions=[caps[i],caps[j]])
        pack=self.risk.risk_pack(train)
        if pack['models'] is not None:
            score={k:m.predict_proba(test[ALL_FEATURES])[:,1] for k,m in pack['models'].items()}
            ref=pack['reference'];score['mix']=.5*rank_reference(ref['lr'],score['lr'])+.5*rank_reference(ref['extra'],score['extra'])
            refs=dict(ref,mix=pack['mix_reference'])
            for name in ['lr','extra','mix']:
                for q in [.3,.5,.7,.9]:
                    threshold=float(np.quantile(refs[name],q));key=f'risk_model_{name}_q{q}'
                    masks[key]=score[name]<=threshold;specs[key]=dict(risk_model=name,training_quantile=q,threshold=threshold)
        masks['abstain']=np.zeros(len(test),bool);specs['abstain']=dict(abstain=True)
        return masks,specs

def inner_predictions(data,outer,bank):
    available=data[data.label_end.lt(f'{outer}-01-01')];frames=[];audit=[]
    for year in range(2020,outer):
        train,test=time_slices(available,year)
        if not eligible(train) or test.empty:continue
        masks,_=bank.masks(train,test)
        for name,pick in masks.items():
            frames.append(pd.DataFrame(dict(candidate=name,event_id=test.event_id.to_numpy(),year=year,y=test.y.to_numpy(int),drop30=test.drop30.to_numpy(int),pick=pick)))
        audit.append(dict(year=year,train_label_max=train.label_end.max(),test_label_max=test.label_end.max()))
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['candidate','event_id','year','y','drop30','pick']),audit

def report_metrics(g):
    m=metrics(g.y,g.pick);s=g[g.pick];bad=int(s.drop30.sum());total_bad=int(g.drop30.sum())
    m.update(drop30_n=bad,drop30_rate=bad/m['selected'] if m['selected'] else None,total_drop30=total_bad,removed_drop30=total_bad-bad,
        removed_drop30_rate=(total_bad-bad)/total_bad if total_bad else None,
        risk95_upper=1-wilson(m['selected']-bad,m['selected']) if m['selected'] else None,
        mean_min_gain=float(s.min_gain60.mean()) if len(s) else None,mean_close60=float(s.close_return60.mean()) if len(s) else None,
        before5_drop30=int(s.drop_before5.sum()),after5_drop30=int(s.drop_after5.sum()),sellable_touch_rate=float(s.sellable_y.mean()) if len(s) else None)
    return m

def run_pool(data,out):
    out.mkdir();bank=IndependentBank();frames=[];folds={};inner_frames=[]
    for year in [2021,2022,2023,2024]:
        train,test=time_slices(data,year);inner,audit=inner_predictions(data,year,bank)
        inner['outer_year']=year;inner_frames.append(inner)
        choices={goal:choose_independent(inner,goal) for goal in ['risk30','precision90','best_effort90']}
        masks,specs=bank.masks(train,test)
        selections=dict(baseline='risk_all',old_two='hit_rule_pair_0_5',**{goal:c['candidate'] for goal,c in choices.items()})
        for method,key in selections.items():
            f=test[['event_id','code','name','date','year','y','drop30','sellable_y','min_gain60','close_return60','drop_before5','drop_after5']].copy()
            f['method']=method;f['candidate']=key;f['pick']=masks[key];frames.append(f)
        folds[str(year)]=dict(train_n=len(train),train_label_max=train.label_end.max(),inner_audit=audit,choices=choices,selected_specs={p:specs[k] for p,k in selections.items()})
        print(out.name,year,{g:c['candidate'] for g,c in choices.items()},flush=True)
    pred=pd.concat(frames,ignore_index=True);pred.to_parquet(out/'outer_predictions.parquet',index=False)
    pd.concat(inner_frames,ignore_index=True).to_parquet(out/'inner_predictions.parquet',index=False)
    result=dict(pooled={k:report_metrics(g) for k,g in pred.groupby('method')},yearly={k:{str(y):report_metrics(g) for y,g in f.groupby('year')} for k,f in pred.groupby('method')},folds=folds)
    inner,audit=inner_predictions(data,2025,bank);choices={goal:choose_independent(inner,goal) for goal in ['risk30','precision90','best_effort90']}
    _,specs=bank.masks(data,data.iloc[:1]);trained,refs=bank.hit.fit(data);risk_pack=bank.risk.risk_pack(data)
    freeze=dict(boundary='2024-12-31',independent_objectives=True,choices={p:dict(choice=c,spec=specs[c['candidate']]) for p,c in choices.items()},inner_audit=audit,
        features=ALL_FEATURES,code_sha256=sha(__file__),not_new_blind=True)
    dump(out/'FROZEN_CANDIDATES.json',freeze);joblib.dump(dict(hit_models=trained,hit_refs=refs,risk_pack=risk_pack,choices=freeze['choices']),out/'frozen_models_pre2025.joblib')
    dump(out/'RESULTS.json',result)
    for method in ['risk30','precision90','best_effort90']:
        selected=pred[pred.method.eq(method)&pred.pick].sort_values(['date','code'])
        lines=['历史时间外验证信号，不是今日预测。','信号日 | 代码 | 名称 | 是否触及5% | 是否跌超30% | 当时仅用更早资料确定的条件']
        for e in selected.itertuples():lines.append(f'{e.date} | {e.code} | {e.name} | {e.y} | {e.drop30} | {e.candidate}')
        (out/(method+'_选中信号.txt')).write_text('\n'.join(lines),encoding='utf-8')
    return result

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('separate_risk30_precision90_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'REGISTERED_SPEC.json',dict(independent_objectives=True,boundary='2024-12-31',touch5='D1..D60 high>=D1open*1.05',drop30='D1..D60 low<D1open*.70',
        risk_objective='minimize inner95% Wilson upper bound on drop30; retain>=40% and>=12; NO hit5 constraint',
        high_precision_objective='inner hit5 precision>=90%; retain>=15% and>=12 and hit5 recall>=20%; NO drop30 constraint. No qualified=>abstain.',
        best_effort_diagnostic='if no90% candidate, report largest inner hit5 Wilson lower with same support; never call it90% qualified',
        validation='nested annual outer2021..2024, inner2020..previous year; mature label purge; no random split',
        source_input_sha256=sha(INPUT/'MANIFEST.json'),model_code_sha256=sha(HERE/'study5_precision80.py'),risk_code_sha256=sha(HERE/'study5_risk30.py'),
        code_sha256=sha(__file__),no_after2024_reads=True,no_posterior_feedback=True,not_fresh_blind=True))
    table=table5();data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    data=risk_order(risk_labels(data));data.to_parquet(out/'features_and_labels.parquet',index=False)
    results={}
    for pool,subset in [('all',data),('leaders',data[data.is_leader])]:results[pool]=run_pool(subset,out/pool)
    dump(out/'SUMMARY.json',{p:r['pooled'] for p,r in results.items()})
    def pct(x):return '—' if x is None else f'{100*x:.2f}%'
    lines=['两个独立方向：降低跌超30%发生率 / 提高触及5%到90%命中率',
        '不做联合标签，不要求同一套策略同时做到两件事。全量主板箱体与当前龙头箱体分别训练，不加保留标签过滤。',
        '只读截至2024年底白名单。研发历史已经看过，是探索性嵌套时间复验；没有读取2025以后数据或据后验选参数。',
        '风险方向仅最小化跌超30%的统计上界，保留至少40%内层样本，不要求涨5%。',
        '90%方向只优化触及5%比例，不对跌超30%加约束；内层未达到90%则不发信号。best_effort单列，不能冒充90%达标。',
        '最大下降按最低价相对D1开盘，非从途中高点回撤。最高触及5%非期末或真实账户收益。','']
    for pool,r in results.items():
        lines+=['全量池' if pool=='all' else '龙头池','方法 | 选中 | 触及5% | 命中率 | 跌超30% | 风险率 | 保留率 | 剔除跌30%/全部风险 | 误删涨5%']
        for key,m in r['pooled'].items():lines.append(f'{key} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {m["drop30_n"]} | {pct(m["drop30_rate"])} | {pct(m["coverage"])} | {m["removed_drop30"]}/{m["total_drop30"]} | {m["missed"]}')
        for method in ['risk30','precision90','best_effort90']:
            lines.append(method+'分年: '+'；'.join(f'{y} 命中{m["hits"]}/{m["selected"]}={pct(m["precision"])}，跌30% {m["drop30_n"]}/{m["selected"]}' for y,m in r['yearly'][method].items()))
        lines+=['']
    (out/'两个独立方向研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    dump(HERE/'holdout_restricted/LATEST_SEPARATE_RISK30_PRECISION90.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),summary={p:r['pooled'] for p,r in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
