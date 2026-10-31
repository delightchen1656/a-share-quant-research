"""Boundary, as-of replay and model reproducibility checks; readable artifacts."""
from pathlib import Path
import json
import sys
import math
import platform
import numpy as np
import pandas as pd
import sklearn
import scipy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from build_dataset import HERE, ROOT, SPEC, FEATURES, past_features, sha, dump, describe, traversals, longest_run
from analyze import selection, equal_date_weights, TrainOnlyTransform, probability_metrics, lift_statistics
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier


def main():
    out=HERE/'results'
    registration=json.loads((HERE/'registration.json').read_text(encoding='utf-8'))
    for source in registration['sources']:
        assert sha(source['path'])==source['sha256'],source['path']
    old_registry=json.loads((HERE.parent/'artifact_registration.json').read_text(encoding='utf-8'))
    for source in old_registry['files']:
        assert sha(HERE.parent/source['path'])==source['sha256'],source['path']
    data=pd.read_parquet(out/'factor_dataset.parquet')
    data['label_end']=pd.to_datetime(data.label_end)
    audit=json.loads((out/'dataset_audit.json').read_text(encoding='utf-8'))
    analysis=json.loads((out/'analysis_audit.json').read_text(encoding='utf-8'))
    assert audit['original_protocol_sha256']==sha(ROOT/'research_protocol_v1.json')
    assert audit['original_gates_sha256']==sha(ROOT/'research_stage_gates_v2.json')
    assert audit['post_2023_price_rows_loaded']==0 and audit['maximum_price_date']=='2023-12-29'
    assert not data.duplicated(['symbol','asof']).any()
    assert data.loc[data.label_status.ne('known'),'y'].isna().all()
    assert data.loc[data.label_status.ne('known'),'y_persistence'].isna().all()
    known=data.loc[data.label_status.eq('known')]
    np.testing.assert_array_equal(known.y,((known.y_persistence==1)&(known.future_traversals>=2)).astype(int))
    assert ((known.y_persistence==1)&(known.y==0)).any(), 'static containment must not imply oscillation'
    assert data.loc[data.future_structural_dates.gt(0),'label_status'].eq('unknown_structural_event').all()
    assert data.loc[data.label_end.notna(),'label_end'].le('2023-12-31').all()
    assert data.loc[data['asof'].eq('2023-06-30'),'label_status'].eq('immature').all()
    mature=data.loc[data.label_end.notna()]
    validation=mature.loc[mature.year.isin([2022,2023])]

    # Full replay from a historical prefix for every candidate stock-date.
    calendar=pd.read_parquet(ROOT/'inputs_pre2025/trading_calendar_v1/calendar.parquet')
    index=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1)&calendar.calendar_date.le(SPEC['data_cutoff']),'calendar_date'])
    end_map={str(d.date()):i for i,d in enumerate(index)}
    replayed=0
    for symbol,group in data.groupby('symbol'):
        df=pd.read_parquet(ROOT/'inputs_pre2025/kline_v1'/f'{symbol}.parquet',filters=[('date','<=',pd.Timestamp(SPEC['data_cutoff']))])
        df['date']=pd.to_datetime(df.date)
        aligned=df.set_index('date').reindex(index)
        nums=aligned[['open','high','low','close','volume','amount','pctChg','preclose']].apply(pd.to_numeric,errors='coerce').to_numpy(float)
        v=aligned.tradestatus.eq('1').to_numpy()&np.isfinite(nums[:,:7]).all(axis=1)&(nums[:,:6]>0).all(axis=1)&(nums[:,6]>-100)
        chain=np.cumsum(np.log1p(np.where(v,nums[:,6]/100,0.)))
        for row in group.itertuples():
            end=end_map[row.asof]
            start=end-503
            desc=describe(nums[start:end+1,3],v[start:end+1],chain[start:end+1])
            # No future array entries are present when recomputing predictors.
            feat=past_features(nums[:end+1].copy(),v[:end+1].copy(),end,desc)
            combined={**desc,**feat}
            for feature in FEATURES+['score']:
                np.testing.assert_allclose(combined[feature],getattr(row,feature),rtol=1e-10,atol=1e-10,equal_nan=True)
            if pd.notna(row.label_end):
                f=v[end+1:end+127]
                close=nums[end+1:end+127,3]
                inside=float(((close[f]>=row.lower)&(close[f]<=row.upper)).mean())
                outside=f&((close<.99*row.lower)|(close>1.01*row.upper))
                count=traversals(close,f,chain[end+1:end+127],row.lower,row.upper)
                assert count==row.future_traversals
                assert math.isclose(inside,row.future_inside_fraction,abs_tol=1e-12)
                assert longest_run(outside)==row.future_max_outside_run
                if row.label_status=='known':
                    assert row.y_persistence==int(inside>=.8 and longest_run(outside)<10)
            replayed+=1
    assert replayed==len(data)

    # Old 64 stock-date candidates and their secondary persistence labels unchanged.
    old=pd.read_parquet(HERE.parent/'results/primary_candidates.parquet')
    december=data.loc[data['asof'].str[5:7].eq('12')&data.strict_v1]
    assert set(zip(old.symbol,old.year))==set(zip(december.symbol,december.year))
    prior_forward=pd.read_parquet(HERE.parent/'results/forward_persistence.parquet')
    for row in prior_forward.loc[prior_forward.horizon.eq(126)].itertuples():
        new=december.loc[december.symbol.eq(row.symbol)&december.year.eq(row.year)].iloc[0]
        if row.status in ['success','broken_or_low_coverage_in_band']:
            assert new.y_persistence==int(row.status=='success')
        else:
            assert pd.isna(new.y_persistence)

    # Selection must be invariant to all future-label edits.
    mutated=validation.copy()
    mutated['y']=1-mutated.y
    mutated['label_status']='synthetic_changed'
    for feature in SPEC['features_order']:
        for adjusted in [False,True]:
            pd.testing.assert_series_equal(selection(validation,feature['name'],feature['direction'],adjusted),
                                           selection(mutated,feature['name'],feature['direction'],adjusted))

    predictions=pd.read_parquet(out/'validation_predictions.parquet')
    predictions['label_end']=pd.to_datetime(predictions.label_end)
    details=json.loads((out/'model_training_details.json').read_text(encoding='utf-8'))
    model_replays=0
    for year in [2022,2023]:
        train=mature.loc[mature.label_end.lt(f'{year}-01-01')&mature.y.notna()]
        test=validation.loc[validation.year.eq(year)]
        assert train.label_end.max()<pd.Timestamp(f'{year}-01-01')
        weights=equal_date_weights(train)
        weights/=weights.mean()
        expected=predictions.loc[predictions.year.eq(year)].set_index(['symbol','asof'])
        for name in ['width_only','logistic','random_forest']:
            prep=TrainOnlyTransform().fit(train,['box_width'] if name=='width_only' else FEATURES)
            before=json.dumps(prep.record(),sort_keys=True)
            changed=test.copy()
            for column in prep.columns:
                changed[column]=1e99
            prep.transform(changed)
            assert before==json.dumps(prep.record(),sort_keys=True)
            registered=[d for d in details if d['year']==year and d['model']==name][0]
            assert before==json.dumps(registered['preprocessing'],sort_keys=True)
            estimator=RandomForestClassifier(**SPEC['models']['random_forest']) if name=='random_forest' else LogisticRegression(**SPEC['models']['logistic'])
            estimator.fit(prep.transform(train),train.y.astype(int),sample_weight=weights)
            got=estimator.predict_proba(prep.transform(test))[:,1]
            np.testing.assert_allclose(got,expected.loc[list(zip(test.symbol,test['asof'])),name].to_numpy(),rtol=1e-12,atol=1e-12)
            model_replays+=1

    factors=pd.read_parquet(out/'factor_results.parquet')
    models=pd.read_parquet(out/'model_results.parquet')
    splits=json.loads((out/'time_splits.json').read_text(encoding='utf-8'))
    strict_models=json.loads((out/'strict_subset_diagnostics.json').read_text(encoding='utf-8'))
    strict_factors=json.loads((out/'strict_factor_diagnostics.json').read_text(encoding='utf-8'))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    names={
        'center_drift':'中枢漂移小','boundary_drift':'边界漂移小','abs_trend':'长期趋势小',
        'traversals':'历史穿越次数多','second_half_frozen_coverage':'旧箱体覆盖高',
        'edge_distance':'当前更靠近箱体中部','vol60_box':'近60日报价波动小',
        'vol_ratio60_252':'近期波动收缩','recent_trend60':'近期净移动小',
        'autocorr1':'一阶报价变化相关低','variance_ratio5':'5日方差比低',
        'efficiency60':'近60日方向效率低','log_liquidity':'成交额高',
        'amount_cv60':'成交额更稳定','intraday_range60_box':'日内振幅小','box_width':'箱宽大（机械基准）'}
    chart=factors.loc[factors.feature.ne('box_width')].sort_values('adjusted_lift')
    fig,ax=plt.subplots(figsize=(12,9),layout='constrained')
    y=np.arange(len(chart))
    colors=['#176d73' if lead else '#5475a0' for lead in chart.directional_lead]
    for i,row in enumerate(chart.itertuples()):
        ax.plot([row.ci_lower*100,row.ci_upper*100],[i,i],color='#a7b3c0',lw=2)
    ax.scatter(chart.adjusted_lift*100,y,c=colors,s=55,zorder=3)
    ax.axvline(0,color='#333',lw=1)
    ax.set_yticks(y,[names[f] for f in chart.feature])
    ax.set_xlabel('相对同日候选池的成功率提升（百分点；按箱宽分层后）\n线段：股票簇与相邻两季度块的探索性95%区间；未做16项多重比较校正。',fontsize=10,labelpad=10)
    ax.set_title('未来126日继续区间往返：16因子中的15个非箱宽因子\n2022四个截面 + 2023一个截面；所有探索区间均跨过零',fontsize=13)
    ax.grid(axis='x',alpha=.18)
    fig.savefig(out/'factor_comparison.png',dpi=150,bbox_inches='tight')
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,5),layout='constrained')
    labels=['仅箱宽模型','逻辑回归','随机森林','旧形态分']
    codes=['width_only','logistic','random_forest','score']
    for offset,year,color in [(-.18,2022,'#527aa5'),(.18,2023,'#d19b46')]:
        g=models.loc[models.year.eq(year)].set_index('model')
        ax.bar(np.arange(4)+offset,[g.loc[c,'hit_rate']*100 for c in codes],width=.34,label=f'{year}（'+('四个截面）' if year==2022 else '一个截面）'),color=color)
        ax.axhline(g.loc['prior','pool_rate']*100,color=color,ls='--',lw=1,label=f'{year}候选池基准')
    ax.set_xticks(range(4),labels)
    ax.set_ylabel('前1/3筛选成功率（%；按截面等权）')
    ax.set_title('复杂模型没有稳定超过简单筛选；宽松池结果不能直接套回旧20只名单')
    ax.legend(fontsize=8,ncol=2)
    ax.grid(axis='y',alpha=.15)
    fig.savefig(out/'model_comparison.png',dpi=150)
    plt.close(fig)

    checks=dict(old_artifact_files_unchanged=len(old_registry['files']),all_candidate_prefix_replays=replayed,
                factor_selection_future_labels_invariant=True,strict_v1_year_end_candidates_preserved=len(december),
                old_secondary_labels_unchanged=True,static_containment_not_oscillation=True,
                model_probability_replays=model_replays,train_only_preprocessing_verified=True,
                immature_and_unknown_not_training_negatives=True,no_post_2023_prices_used=True,
                original_economic_gates_unchanged=True)
    dump(out/'validation.json',checks)
    dump(out/'runtime_versions.json',dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,
                                         scipy=scipy.__version__,sklearn=sklearn.__version__,matplotlib=matplotlib.__version__))
    base=float(np.mean([g.y.eq(1).mean() for _,g in validation.groupby('asof')]))
    lines=[
        '哪些因子更容易筛出未来继续区间震荡的股票：探索研究 v1',
        '='*64,'',
        '结论：尚未确认可靠因子。历史穿越次数多在后续截面提升较大，但早期发现期方向相反；近60日方向效率低是唯一通过宽松池预定跨时期方向线索门槛的因子，但提升很小、不确定区间跨零，在严格池反而下降。复杂模型没有给出可以套用原20只名单的稳定优势。',
        '', '一、研究边界与执行顺序',
        '用户本轮授权新增形态标签、因子与离线模型实验，仅限此子分支。先冻结spec.json并登记哈希，再生成样本、标签、分析、核验；没有调参搜索。原行业研究协议、经济标签及账户回测门槛未修改；旧20只名单、形态规则和旧结果未修改。',
        '截止2023-12-29，仅读取已授权白名单行情快照，3336文件哈希核验。2024行情未用于计算。既有退市覆盖/存活偏差未解决，事件账本为回溯质量审计，不能宣称点时可执行股票池。',
        '此前已看过部分年末截面的未来维持统计，因此2022/2023只称时间顺序开发验证，不能冒称完全未看过的最终保留检验。',
        '', '二、候选池：与原20只分开',
        '按2020Q1至2023Q4每季最后交易日形成快照，每次回看504个市场交易日。保留原报价质量、流动性、股份变化检查，箱宽10%—40%、最高/最低收盘价幅度不超过60%、当前价在5%—95%分位箱体内。宽松池要求全窗至少2次单程穿越、各半窗至少1次；漂移、趋势、更多往返、旧箱体覆盖变成待检验因子。原严格v1子集另行保留。',
        f'得到{len(data)}个股票—截面样本、{data.symbol.nunique()}只不同股票；有完整126日观察窗口{len(mature)}个，其中已知标签{len(known)}个，未知{len(mature)-len(known)}个，未成熟{len(data)-len(mature)}个。重复股票和相邻观察窗有依赖，不是独立样本数量。',
        '', '三、标签：必须继续上下往返',
        '信号当日固定历史完整504日的下/上界L/U，未来126个市场交易日不移动边界。',
        '次要标签“区间维持”：未来有效报价覆盖至少95%，至少80%有效收盘在[L,U]内，不出现连续10个市场交易日位于[0.99L,1.01U]外。',
        '主要标签“区间往返维持”：满足次要标签，且未来单独窗口至少2次异侧穿越，即至少一次上下往返；触及区间两侧20%区域，异侧间隔至少5个市场交易日，且同向参考价对数报价移动至少达到历史对数箱宽35%。现金除息机械落差不能单独构成一次有效往返。',
        '未来股份结构事件记未知，低报价覆盖记未知；未来未知不删除当日候选，监督训练时不用未知当负样本，筛选保守成功率则将其留在初始分母。未知项也可能改变因子提升估计。未使用未来ST/退市状态删池。',
        f'开发验证共{len(validation)}个股票—截面样本（{validation.symbol.nunique()}只股票），已知{validation.y.notna().sum()}个、未知{validation.y.isna().sum()}个；仅留在箱内{int(validation.y_persistence.sum())}个，兼具往返{int(validation.y.sum())}个。两种目标不可混称。',
        '', '四、时间划分与可得日期',
        '发现期：126日标签在2022年以前完整成熟的季度样本。2022验证模型只用2022年初已经成熟的标签；2023模型同理。每个验证年年内不重训，不随机切分；中位数填补、1%/99%截尾和标准化参数只在对应训练数据拟合。',
        '年份 | 训练已知样本/股票/正例 | 最后训练信号 | 最后训练标签可得日 | 验证截面 | 验证总样本/已知/正例',
    ]
    for s in splits:
        lines.append(f"{s['year']} | {s['train_rows']}/{s['train_unique']}/{s['train_positive']} | {s['train_last_signal']} | {s['train_max_label_end']} | {','.join(s['validation_dates'])} | {s['validation_rows']}/{s['validation_known']}/{s['validation_positive']}")
    lines += [
        '冻结spec中关于“四个2022截面、两个2023截面”的文字是预期，不是替代日历的规则；按已登记的完整126日成熟条件，2023Q2实际上未到期，只能保留2023Q1一个验证截面。此澄清未改变阈值、未补2024价格。',
        '', '五、全部16因子结果',
        '所有方向先登记：低漂移/低趋势/低方向效率/低波动/低方差比/低自相关/稳定成交额预期有利，更多穿越/更高覆盖/距边界更远/更高成交额预期有利；箱宽大单独作机械基准。没有将失败因子事后反向。',
        '每截面按因子取前1/3；除箱宽外，还按当日箱宽秩分为三组、各组取前1/3，以减少“只是箱子更宽”的影响。表中成功率和提升对验证截面等权，未知仍在分母；并非简单汇总命中数/样本数。',
        f'验证候选池按截面等权成功率为{base:.2%}；以下“提升”为百分点。',
        '因子（预定有利方向） | 选择后成功率 | 宽度分层后提升 | 2022提升 | 2023提升 | 早期发现期提升 | 探索95%区间 | 方向线索',
    ]
    for row in factors.itertuples():
        effect=row.raw_lift if row.feature=='box_width' else row.adjusted_lift
        lines.append(f'{names[row.feature]} | {row.primary_hit_rate:.2%} | {effect*100:+.2f} | {row.lift2022*100:+.2f} | {row.lift2023*100:+.2f} | {row.discovery_lift*100:+.2f} | [{row.ci_lower*100:+.2f},{row.ci_upper*100:+.2f}] | {"弱线索" if row.directional_lead else "未通过"}')
    lines += [
        '箱宽行不进行按自身宽度分层，其提升为原始比较值。其他行宽度分层与原始比较完整保存在factor_details.json。',
        '近60日方向效率=abs(sum(r))/sum(abs(r))，r是参考价对数报价变化；越低表示来回走动多、净方向移动少，不等同于波动率越低。这个因子从早期发现到两个验证年份均小幅同向，但宽度分层后仅提升约0.52个百分点。',
        '历史穿越次数更多在2022和2023验证分别提升约2.85、2.69个百分点，但早期发现期约-3.36个百分点，因此按事前门槛不保留为跨时期一致线索。长期趋势小、中枢漂移小、旧箱体覆盖高也没有通过跨期方向门槛。',
        '低近期波动、低日内振幅在本次“未来还要完成往返”的目标下表现差；不能据此推断低波动对“只留在箱内”或投资收益有害。',
        '所有16项探索95%区间均跨零；区间通过股票簇与相邻两季度循环块交叉重采样1000次获得，只有5个验证时间截面、约2.5个两季块，且没有16项多重比较校正。它们是描述性不确定性，不能提供统计显著或未来概率保证。',
        '', '六、模型比较（固定参数，无搜索）',
        '逻辑回归L2、C=0.1；浅随机森林300棵、深度3、叶节点至少30；训练损失按截面等权。对照为训练正例率、只看箱宽的逻辑回归和旧形态分。旧形态分只作排序，不冒充概率。常数先验不具备选股排序能力，不能因代码平局顺序产生“选股提升”。',
        '年份 | 模型 | 前1/3成功率 | 同日池基准 | 提升百分点 | AUC | Brier（越低越好）',
    ]
    model_names={'prior':'训练常数先验','width_only':'只用箱宽','logistic':'逻辑回归','random_forest':'随机森林','score':'旧形态分'}
    for row in models.itertuples():
        hit='—' if pd.isna(row.hit_rate) else f'{row.hit_rate:.2%}'
        lift='—' if pd.isna(row.lift) else f'{row.lift*100:+.2f}'
        brier='—' if pd.isna(row.brier) else f'{row.brier:.6f}'
        lines.append(f'{row.year} | {model_names[row.model]} | {hit} | {row.pool_rate:.2%} | {lift} | {row.auc:.3f} | {brier}')
    lines += [
        '随机森林通过了事前定义的最低模型门槛（两年均比池基准选股率高、Brier低于先验与宽度模型），但2022相对先验Brier仅改善约0.000008；前1/3命中率两年都低于只用箱宽模型，不能据此宣称复杂模型更好。逻辑回归2023筛选反而恶化。所有模型只做离线比较，没有部署或重排旧20只。',
        '', '七、原严格箱体子集：不能混用宽松池结论',
        '以下仅诊断，未依据它反向改特征或阈值。样本更小，模型在宽松池训练。',
        '年份 | 模型 | 严格子集样本 | 选出数 | 成功数 | 等权成功率 | 子集基准',
    ]
    for r in strict_models:
        lines.append(f"{r['year']} | {model_names[r['model']]} | {r['pool_n']} | {r['selected_n']} | {r['selected_successes']} | {r['hit_rate']:.2%} | {r['pool_rate']:.2%}")
    lines += ['', '严格子集全部因子诊断（按相同预定方向与箱宽分层方法，合并验证截面等权）',
              '因子 | 选择数 | 成功数 | 成功率 | 子集基准 | 提升百分点']
    for r in strict_factors:
        lines.append(f"{names[r['feature']]} | {r['selected_n']} | {r['selected_successes']} | {r['hit_rate']:.2%} | {r['pool_rate']:.2%} | {r['lift']*100:+.2f}")
    lines += ['方向效率低在严格子集中提升约-3.41个百分点；因此连这个宽松池弱线索也不能直接套用旧20只。历史穿越频率在严格子集为正，但仍没有解决早期发现期反向和时间段太少的问题。严格子集不是旧20只在2024的表现，没有查看这些未来价格。',
              '严格子集的全部16因子逐截面结果也已保存strict_factor_diagnostics.json。宽松池只有一个弱方向线索，并不证明能进一步精选原20只股票。',
              '', '八、研究判断与下一阶段',
              '本轮保留的只是研究线索：方向效率低；历史穿越频率可作待复核线索，不能因验证阶段较好就忽略早期反向。没有已确认因子，也没有收益或可交易性结论。',
              '若继续，优先在新登记版本中研究“能否留在区间”和“能否完成往返”两个目标的冲突，以及对严格候选池的适用性；需要更多独立时间段和足够正例，再考虑复杂模型。不要在已看过的2022/2023数据上反复改阈值，把它包装成独立验收。2024仍保留，未经候选冻结不打开。',
              '快照覆盖偏差、回溯公司行动质量检查、重叠标签、少数正例和仅一个2023截面均限制外推。17个验证未知样本留在分母，未知并非已证实失败；剔除未知训练也会影响适用范围。',
              '', '九、核验与产物',
              f'{replayed}个候选股票—截面用各自历史前缀重算全部16因子一致；所有已成熟形态标签重新核验；旧64个年末候选及次要标签不变；6组模型概率独立重拟合一致；未来标签修改不改变任何单因子选择；训练预处理不受验证数据修改影响。',
              'results/factor_dataset.parquet：全部季度候选、因子、标签、未知/未成熟原因和严格子集标记。',
              'results/factor_results.parquet、factor_details.json：全部16因子与各截面结果，不隐藏失败试验。',
              'results/model_results.parquet、validation_predictions.parquet：模型对照及验证预测。',
              'results/time_splits.json、model_training_details.json：标签成熟边界及训练预处理参数。',
              'results/factor_comparison.png、model_comparison.png：静态科研图。',
              'results/validation.json、dataset_audit.json、analysis_audit.json：边界、复算及审计。',
              'registration.json、artifact_registration.json：事前规则和最终产物哈希。',
              '', '方法参考（不支持金融有效性，仅用于时间切分和防泄漏原则）',
              'scikit-learn TimeSeriesSplit：https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html',
              'scikit-learn数据泄漏与预处理：https://scikit-learn.org/stable/common_pitfalls.html',
              '实际项目按市场日历、股票面板和标签结束日自定义切分，未直接把普通行号TimeSeriesSplit当作已解决标签重叠。',
    ]
    (HERE/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files=[p for p in HERE.rglob('*') if p.is_file() and p.name!='artifact_registration.json' and '__pycache__' not in p.parts]
    dump(HERE/'artifact_registration.json',dict(spec_sha256=sha(HERE/'spec.json'),files=[dict(path=str(p.relative_to(HERE)),sha256=sha(p)) for p in sorted(files)]))
    print(json.dumps(checks,ensure_ascii=False,indent=2),flush=True)
    print('Report: '+str(HERE/'REPORT.txt'),flush=True)


if __name__=='__main__':
    main()
