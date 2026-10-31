"""Development-only report; this program must never open the future audit directory."""
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from settings import OUT,sha,dump

LABELS={
 'gap1':'前一日跳空','intraday1':'前一日日内涨跌','range1':'前一日振幅','close_position1':'前一日收盘位置',
 'upper_wick1':'前一日上影线','lower_wick1':'前一日下影线','mean_close_position5':'近5日平均收盘位置',
 'range_expansion1_20':'前一日振幅扩张','momentum3':'3日动量','momentum10':'10日动量','momentum120':'120日动量',
 'acceleration5_20':'短期动量加速度','volume_surprise1_20':'前一日成交量异常','amount_surprise1_20':'前一日成交额异常',
 'turnover_ratio5_20':'换手率加速','price_volume_corr20':'价量相关','downside_deviation20':'20日下行波动',
 'max_up20':'近20日最大单日上涨','max_down20':'近20日最大单日下跌','volatility_ratio5_20':'短期波动扩张',
 'beta60':'历史市场贝塔','market_corr60':'历史市场相关性','idiosyncratic_vol60':'历史特有波动','residual_momentum5':'剔除市场后的短期动量',
 'quote_momentum20':'20日动量','quote_momentum60':'60日动量','quote_reversal5':'5日反转','quote_reversal1':'前一日反转',
 'quote_volatility20':'20日波动','quote_volatility60':'60日波动','log_median_amount20':'成交额水平',
 'volume_ratio5_20':'量能扩张','turnover_mean20':'换手率水平','quote_high_position20':'20日区间位置',
 'quote_efficiency20':'20日路径效率','last_quote_change':'前一日涨跌','lastday_pair':'前一日涨跌及其反向重复项'}
GROUP_LABELS={'candle':'跳空/实体/振幅/位置组','wick':'影线及位置持续性组','horizon':'多周期动量组','flow':'量价活动组','tail':'波动尾部组','market':'市场联动组'}


def name(variant):
    if variant=='baseline12':
        return '原12因子基准'
    if variant=='all_new24':
        return '一次加入全部24个新因子'
    if variant.startswith('drop__'):
        return '删除：'+LABELS[variant[6:]]
    if variant.startswith('add__'):
        return '加入：'+LABELS[variant[5:]]
    return '加入：'+GROUP_LABELS[variant[7:]]


def main():
    summary=pd.read_parquet(OUT/'summary.parquet')
    annual=pd.read_parquet(OUT/'annual_means.parquet')
    weeks=pd.read_parquet(OUT/'weekly_all_folds.parquet')
    adaptive=pd.read_parquet(OUT/'causal_selector_weeks.parquet')
    choices=json.loads((OUT/'causal_selector_choices.json').read_text(encoding='utf-8'))
    decision=json.loads((OUT/'final_development_decision.json').read_text(encoding='utf-8'))
    selected=decision['selected_variant']
    baseline=summary.set_index('variant').loc['baseline12']
    candidate=summary.set_index('variant').loc[selected]
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained')
    for variant,label,color in [('baseline12','原12因子基准','#6d7881'),(selected,'冻结候选：'+name(selected),'#b45c3b')]:
        g=weeks.loc[weeks.year.ge(2021)&weeks.variant.eq(variant)].sort_values('monday')
        axes[0].plot(pd.to_datetime(g.monday),g.signal_mean.cumsum()*100,label=label,color=color)
        axes[1].plot(pd.to_datetime(g.monday),g.improvement.cumsum()*100,label=label,color=color)
    g=adaptive.sort_values('monday')
    axes[0].plot(pd.to_datetime(g.monday),g.signal_mean.cumsum()*100,label='只用此前两年选择的路径',color='#378773')
    axes[1].plot(pd.to_datetime(g.monday),g.improvement.cumsum()*100,label='只用此前两年选择的路径',color='#378773')
    axes[0].set_title('周一开盘→周二收盘：因子开发比较（2021—2023）\n逐期前10只均值累加；条件报价毛收益，不是复利账户净值')
    axes[0].set_ylabel('信号平均收益累加（百分点）')
    axes[1].set_ylabel('较原模型提升累加（百分点）')
    for ax in axes:
        ax.grid(alpha=.2)
        ax.axhline(0,color='#777',lw=.6)
        ax.legend(fontsize=8)
    fig.savefig(OUT/'development_curves.png',dpi=160)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,7),layout='constrained')
    show=summary.loc[summary.variant.ne('baseline12')].head(12).sort_values('mean_improvement')
    ax.barh(np.arange(len(show)),show.mean_improvement*100,color=['#b45c3b' if v==selected else '#527d9c' for v in show.variant])
    ax.set_yticks(np.arange(len(show)),[name(v) for v in show.variant])
    ax.set_xlabel('较原模型每期平均收益提高（百分点）')
    ax.set_title('45组固定开发试验中的前12项；事后排名仅作开发线索')
    ax.axvline(0,color='#777',lw=.6)
    ax.grid(axis='x',alpha=.2)
    fig.savefig(OUT/'factor_lift.png',dpi=160)
    plt.close(fig)
    lines=['周一梯度提升：因子优化开发报告',
      '范围：只读本项目2018—2023白名单；验证开发年份2021—2023，未读取2024及以后股票行情/标签/成绩。',
      '全部45组事前登记试验保留，模型超参数及前10只不变。累计线是逐周平均普通报价毛收益累加，不是账户复利收益。',
      '2021—2023已经在此前研究中观察，本轮再择优属于开发，不称独立验证。缺失/公司参考价变化标签保留未知，结果为条件均值。',
      '',f'原12因子每期均值：{baseline.mean_signal_return:.4%}',
      f'按事前跨年规则冻结：{selected}（{name(selected)}）',
      f'候选每期均值：{candidate.mean_signal_return:.4%}；相对原模型提升：{candidate.mean_improvement*100:+.4f}个百分点；{int(candidate.positive_improvement_years)}/3年提升',
      f'双方全部10只标签完整的共同周次：{int(candidate.joint_complete_weeks)}；该口径平均提升{candidate.joint_complete_mean_improvement*100:+.4f}个百分点',
      f'候选标签覆盖率{candidate.known_coverage:.3%}；未加多重比较修正的配对块自助区间[{candidate.improvement_ci_low*100:+.4f},{candidate.improvement_ci_high*100:+.4f}]个百分点',
      f'44项比较近似同时区间[{candidate.simultaneous_ci_low*100:+.4f},{candidate.simultaneous_ci_high*100:+.4f}]个百分点；区间不消除择优、存活偏差和未来实盘不确定性。',
      f'严格只用此前两年选择因子的历史路径：每期均值{adaptive.signal_mean.mean():.4%}，较原模型{adaptive.improvement.mean()*100:+.4f}个百分点。',
      '', '原模型/冻结候选逐年每期均值（不是年度账户收益）']
    for year in [2021,2022,2023]:
        a=annual.loc[annual.year.eq(year)].set_index('variant')
        z=adaptive.loc[adaptive.year.eq(year)]
        lines.append(f'{year} 原模型{a.loc["baseline12","mean_signal_return"]:.4%} | 候选{a.loc[selected,"mean_signal_return"]:.4%} | 候选提升{a.loc[selected,"mean_improvement"]*100:+.4f}个百分点 | 当时选择路径{z.signal_mean.mean():.4%}')
    lines+=['','因果时序选择记录（只能用过去结果，仍是开发诊断）']
    lines += [str(c) for c in choices]
    lines += ['','所有45组试验：每期均值/较原模型提升/逐年提升（百分点）/标签覆盖率']
    for r in summary.itertuples():
        lines.append(f'{r.variant} | {name(r.variant)} | {r.mean_signal_return:.4%} | {r.mean_improvement*100:+.4f} | {r.improvement2021*100:+.4f}/{r.improvement2022*100:+.4f}/{r.improvement2023*100:+.4f} | {r.known_coverage:.3%}')
    lines += ['', '解释与边界',
      '单因子加入/删除的变化包含树的交互和相关因子的替代作用，不等于该因子的因果贡献。前一日反转与前一日涨跌是相反形式，单独删掉一个不能证明它无用；重复项联合删除也已保留。',
      '本轮不根据最高分再临时组合新因子；只按预先规则从45组中冻结。冻结后2025—2026审计结果不允许返回优化、换候选或重训。',
      '审计子代理只向优化端返回完成状态和报告路径；本开发报告不读取、不展示盲测成绩。失败/数据不足也保留。',
      '目前信号均值没有扣费用，不代表开盘/收盘都能成交。此前模型存在周二不能按时退出的情况，不能把毛收益提升直接换算成可实现年化。',
      '源码、训练边界、原基准复现、历史前缀核验与文件哈希均保留。冻结包为frozen_candidate_v1，盲测写独立restricted_audit_2025_2026目录。']
    (OUT/'DEVELOPMENT_REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump(OUT/'development_delivery.json',dict(only_pre2024_results=True,future_audit_results_not_read=True,
         candidate=selected,report='DEVELOPMENT_REPORT.txt',source_summary_sha256=sha(OUT/'summary.parquet')))
    print('Development report saved; only pre2024figures.',flush=True)


if __name__=='__main__':
    main()
