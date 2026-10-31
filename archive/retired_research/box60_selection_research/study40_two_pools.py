"""User-requested >40% price-shape label, independently evaluated in ALL and LEADER pools."""
import datetime,json
import numpy as np
import pandas as pd
from study import HERE,INPUT,CORE,NAMES,RULE_FEATURES,sha,dump,build_table,metrics,contrasts,rules,evaluate

TARGET=.40
LABELS={'all':'全量池','leaders':'龙头池'}
METHODS={'logistic':'逻辑回归','boosting':'梯度提升','learned_rule':'训练期自动选择单规则'}

def relabel(table):
    table=table.copy()
    table['y']=np.nan
    complete=table.label_status.eq('complete')
    table.loc[complete,'y']=(table.loc[complete,'peak_gain60']>TARGET+1e-10).astype(int)
    return table

def summary(table):
    d=table[table.label_status.eq('complete')]
    return dict(events=len(table),complete=len(d),stocks=d.code.nunique(),positive_events=int(d.y.sum()),
        positive_stocks=d[d.y.eq(1)].code.nunique(),rate=float(d.y.mean()) if len(d) else None,
        excluded=table[~table.label_status.eq('complete')].label_status.value_counts().to_dict(),
        by_year={str(y):dict(n=len(g),positive=int(g.y.sum()),rate=float(g.y.mean())) for y,g in d.groupby('year')})

def join_predictions(rows,data):
    return pd.DataFrame(rows).merge(data.reset_index(names='index')[['index','event_id','code','date','year','y','peak_gain60']],on='index',validate='many_to_one')

def pool_study(table,out):
    out.mkdir();data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    data.to_parquet(out/'complete_events.parquet',index=False)
    positive=data[data.y.eq(1)].sort_values(['date','code'])
    positive.to_parquet(out/'positive_events.parquet',index=False)
    dump(out/'DESCRIPTIVE.json',dict(contrasts=contrasts(data),fixed_rules={k:metrics(data.y,m) for k,m in rules(data).items()}))
    folds={};predictions=[]
    for year in [2021,2022,2023,2024]:
        start=f'{year}-01-01';train=data[data.label_end.lt(start)];test=data[data.year.eq(year)]
        if len(train)<35 or train.y.sum()<3 or train.y.nunique()<2 or test.empty:
            folds[str(year)]=dict(skipped=True,train_n=len(train),train_positive=int(train.y.sum()));continue
        rows,detail=evaluate(train,test,str(year));predictions+=rows
        folds[str(year)]=dict(train_n=len(train),train_positive=int(train.y.sum()),train_label_max=train.label_end.max(),test_n=len(test),results=detail)
        print(out.name,year,'train',len(train),'test',len(test),flush=True)
    pred=join_predictions(predictions,data)
    pred.to_parquet(out/'walkforward_predictions.parquet',index=False)
    pooled={method:metrics(g.y,g.selected,g.score.to_numpy() if g.score.notna().all() else None) for method,g in pred.groupby('method')}
    yearly={method:{str(y):metrics(g.y,g.selected,g.score.to_numpy() if g.score.notna().all() else None) for y,g in group.groupby('year')} for method,group in pred.groupby('method')}
    train=data[data.label_end.lt('2023-01-01')];test=data[data.year.ge(2023)]
    rows,frozen=evaluate(train,test,'frozen_before2023');fp=join_predictions(rows,data)
    fp.to_parquet(out/'frozen_2023_2024_predictions.parquet',index=False)
    result=dict(summary=summary(table),walkforward=pooled,walkforward_by_year=yearly,folds=folds,frozen_before2023=frozen,
        frozen_by_year={method:{str(y):metrics(g.y,g.selected,g.score.to_numpy() if g.score.notna().all() else None) for y,g in group.groupby('year')} for method,group in fp.groupby('method')},
        frozen_train_n=len(train),frozen_train_positive=int(train.y.sum()))
    dump(out/'RESULTS.json',result)
    lines=['信号后D1至D60最高前复权价/信号D1开盘−1>40%；这是事后样本清单，不是已验证的预测名单。',
           '信号日 | 代码 | 名称 | 60日最高涨幅 | 首次最高日 | 当前★龙头标记']
    for row in positive.itertuples():lines.append(f'{row.date} | {row.code} | {row.name} | {row.peak_gain60*100:.2f}% | {row.peak_date} | {"★" if row.is_leader else ""}')
    (out/'超过40%的箱体信号清单.txt').write_text('\n'.join(lines),encoding='utf-8')
    return result

def report(results,out):
    def pct(x):return '—' if x is None else f'{x*100:.2f}%'
    lines=['沪深主板箱体信号：后60交易日最高涨幅超过40%，全量池/龙头池',
        '边界：只使用2019—2024信号与截至2024-12-31日线。未读取之后的行情或结果。',
        '定义：D1..D60最高前复权价/D1开盘−1>40%。最高触及价是事后形态标签，不是持有到D60的收益或实际账户收益。',
        '全量池包含全部主板箱体；龙头池是其中当前★龙头子集，两池有重叠。均不加保留标签过滤，不删除超过100%的涨幅。',
        '模型各池独立训练、独立取训练分数70分位阈值。2021—2024逐年验证；仅用验证年初前已成熟的60日标签训练。',
        '无随机划分；不在后续验证年份中按全年排序选前30%；不把D1开盘或未来高点作为特征。',
        '本次是看到前次60%研究后的用户指定40%阈值重筛，属于探索性时间验证，不是新的盲测。当前股票范围与龙头归属回看历史有选择偏差。','']
    for key,res in results.items():
        s=res['summary'];d=json.loads((out/key/'DESCRIPTIVE.json').read_text(encoding='utf-8'))
        lines+=[LABELS[key],f'原始事件{s["events"]}；完整事件{s["complete"]}；超过40%共{s["positive_events"]}次、{s["positive_stocks"]}只股票；占比{pct(s["rate"])}；排除{s["excluded"]}',
            '逐年 | 完整事件 | 超40%事件 | 占比']
        for year,x in s['by_year'].items():lines.append(f'{year} | {x["n"]} | {x["positive"]} | {pct(x["rate"])}')
        lines+=['','时间验证（逐年训练，2021—2024合并）','方法 | 候选数 | 命中超40% | 命中率 | 抓取率 | 漏掉 | 倍率（相对不筛选）']
        for method,m in res['walkforward'].items():
            name=METHODS.get(method,method.replace('fixed:','固定规则：'))
            lines.append(f'{name} | {m["selected"]} | {m["hits"]} | {pct(m["precision"])} | {pct(m["recall"])} | {m["missed"]} | {m["lift"]:.2f}' if m['lift'] is not None else f'{name} | 无有效选择')
        lines+=['','事后共同点（34指标，多重比较BH校正；不能据此声称预测有效）','特征 | 超40%中位数 | 其他中位数 | 校正q值']
        for x in d['contrasts'][:10]:lines.append(f'{x["name"]} | {x["positive_median"]:.6g} | {x["other_median"]:.6g} | {x["q_bh"]:.4f}')
        lines+=['','模型分年命中率（括号内命中/选出数）']
        for method in ['learned_rule','logistic','boosting']:
            lines.append(METHODS[method]+': '+'；'.join(f'{y} {pct(m["precision"])} ({m["hits"]}/{m["selected"]})，基准{pct(m["base_rate"])}' for y,m in res['walkforward_by_year'][method].items()))
        lines+=['','2023前一次冻结、2023—2024不更新的独立时间检查']
        for method in ['learned_rule','logistic','boosting']:
            m=res['frozen_before2023'][method]['metrics'];lines.append(f'{METHODS[method]}：{m["hits"]}/{m["selected"]}，命中率{pct(m["precision"])}，抓取率{pct(m["recall"])}，基准{pct(m["base_rate"])}')
        lines+=['','']
    (out/'研究报告.txt').write_text('\n'.join(lines),encoding='utf-8')

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('target40_two_pools_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'REGISTERED_SPEC.json',dict(target=TARGET,strictly_greater=True,boundary='2024-12-31',pools=['all mainboard box events','current leader subset; no keep filter'],
        independent_model_training=True,inputs='inputs_pre2025 whitelist only',input_manifest_sha256=sha(INPUT/'MANIFEST.json'),
        code_sha256=sha(__file__),feature_and_evaluation_code_sha256=sha(HERE/'study.py'),
        model_features=CORE,descriptive_features=list(NAMES),rule_features=RULE_FEATURES,
        validation='annual 2021..2024; train label_end < year start; threshold TRAIN-score q70',
        frozen_validation='train labels mature before2023; freeze then evaluate2023 and2024',
        target_type='adjusted price-shape label, not cash/share PnL; no raw unadjusted split-price ratio',
        earlier_target60_results_seen=True,user_requested_target_revision=True,no_after2024_data=True,not_new_blind=True))
    table=relabel(build_table());table.to_parquet(out/'features_and_labels.parquet',index=False)
    assert table.date.le('2024-12-31').all() and table.loc[table.label_status.eq('complete'),'label_end'].le('2024-12-31').all()
    results={}
    for key,pool in [('all',table),('leaders',table[table.is_leader])]:results[key]=pool_study(pool,out/key)
    report(results,out);dump(out/'SUMMARY.json',{k:dict(summary=r['summary'],walkforward=r['walkforward'],frozen_before2023={m:r['frozen_before2023'][m] for m in ['learned_rule','logistic','boosting']}) for k,r in results.items()})
    dump(HERE/'holdout_restricted/LATEST_TARGET40.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),results={k:dict(summary=r['summary'],walkforward={m:r['walkforward'][m] for m in ['learned_rule','logistic','boosting']}) for k,r in results.items()}),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
