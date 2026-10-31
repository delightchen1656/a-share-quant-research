"""Full pre2024development report and execution diagnostics; no audit feedback."""
import json
import sys
import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from settings import BASE,OLD,PRIOR,OUT,variants,sha,dump,install_read_boundary

LABELS={'quote_momentum60':'60日动量','quote_reversal5':'5日反转','quote_reversal1':'前一日反转',
    'quote_volatility20':'20日波动','quote_volatility60':'60日波动','log_median_amount20':'成交额水平',
    'volume_ratio5_20':'量能扩张','turnover_mean20':'换手率水平','quote_high_position20':'20日区间位置',
    'quote_efficiency20':'路径效率','last_quote_change':'前一日涨跌',
    'up_day_fraction60':'60日上涨天数占比','positive_run20':'连续上涨天数',
    'return_autocorr20':'收益自相关','jump_share20':'单日跳跃集中度',
    'close_to_vwap1':'收盘相对日均价','range_compression5_20':'振幅收缩'}
BLOCK_LABELS={'long_momentum':'120日动量','acceleration':'动量加速度','amount':'成交额异常','tail':'波动尾部组'}


def name(variant):
    if variant=='original12':return '原12因子'
    if variant=='anchor11':return '上一轮11因子'
    if variant=='new_group6':return '11因子＋六个新特征'
    if variant=='long_plus_new6':return '11因子＋120日动量＋六个新特征'
    if variant.startswith('combine__'):
        return '11因子＋'+'＋'.join(BLOCK_LABELS[b] for b in variant.split('__')[1:])
    if variant.startswith('prune__'):
        return '11因子再删'+LABELS[variant[7:]]
    return '11因子＋'+LABELS[variant[5:]]


def main():
    install_read_boundary()
    summary=pd.read_parquet(OUT/'summary.parquet')
    annual=pd.read_parquet(OUT/'annual_means.parquet')
    weekly=pd.read_parquet(OUT/'weekly_all_folds.parquet')
    selected=pd.read_parquet(OUT/'selected_signal_labels.parquet')
    selected=selected.loc[selected.year.ge(2021)].copy()
    adaptive=pd.read_parquet(OUT/'causal_selector_weeks.parquet')
    decision=json.loads((OUT/'decision.json').read_text(encoding='utf-8'))
    lookup=summary.set_index('variant')
    best=decision['best_exploratory_variant']
    original=lookup.loc['original12']
    anchor=lookup.loc['anchor11']
    bestrow=lookup.loc[best]
    # Flags only: all selected signals stay in reported means/unknown counts.
    sys.path.insert(0,str(BASE/'src'))
    from portfolio import Quotes
    from common import tick
    q=Quotes()
    flags={}
    for row in selected[['symbol','monday','tuesday']].drop_duplicates().itertuples():
        b=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.monday)))
        e=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.tuesday)))
        flags[(row.symbol,row.monday)]=(bool(b['active'] and not b['st'] and b['open']<tick(b['preclose']*1.1)-.004),
            bool(e['active'] and e['close']>tick(e['preclose']*(.95 if e['st'] else .9))+.004))
    diagnostics=[]
    for variant,g in selected.groupby('variant'):
        a=np.array([flags[(r.symbol,r.monday)] for r in g.itertuples()])
        diagnostics.append(dict(variant=variant,total_signals=len(g),opening_cannot_buy=int((~a[:,0]).sum()),Tuesday_cannot_exit=int((~a[:,1]).sum())))
    dump(OUT/'execution_flags.json',diagnostics)
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained')
    shown=[('original12','原12因子','#91969a'),('anchor11','上一轮11因子','#577c98'),
           (best,'本轮样本最高（探索）：'+name(best),'#b76341')]
    if decision['upgrade_eligible'] and decision['retained_variant']!=best:
        shown.append((decision['retained_variant'],'通过预登记门槛的开发候选','#955e99'))
    for variant,label,color in shown:
        g=weekly.loc[weekly.year.ge(2021)&weekly.variant.eq(variant)].sort_values('monday')
        axes[0].plot(pd.to_datetime(g.monday),g.signal_mean.cumsum()*100,label=label,color=color,lw=1.2)
        axes[1].plot(pd.to_datetime(g.monday),g.improvement.cumsum()*100,label=label,color=color,lw=1.2)
    g=adaptive.sort_values('monday')
    axes[0].plot(pd.to_datetime(g.monday),g.signal_mean.cumsum()*100,label='仅按此前两年选择的路径',color='#398571')
    axes[1].plot(pd.to_datetime(g.monday),g.improvement.cumsum()*100,label='仅按此前两年选择的路径',color='#398571')
    axes[0].set_title('周一开盘→周二收盘：第二轮因子开发（2021—2023）\n每期前10只；条件信号毛收益累加，不是复利账户净值；未使用后验成绩')
    axes[0].set_ylabel('逐期均值累加（百分点）')
    axes[1].set_ylabel('较上一轮11因子提升累加（百分点）')
    for ax in axes:
        ax.grid(alpha=.2)
        ax.axhline(0,color='#666',lw=.6)
        ax.legend(fontsize=8)
    fig.savefig(OUT/'development_curves.png',dpi=160)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(13,7),layout='constrained')
    top=summary.loc[~summary.variant.isin(['original12','anchor11'])].head(12).sort_values('mean_improvement')
    ax.barh(np.arange(len(top)),top.mean_improvement*100,color=['#b76341' if v==best else '#577c98' for v in top.variant])
    ax.set_yticks(np.arange(len(top)),[name(v) for v in top.variant],fontsize=9)
    ax.axvline(0,color='#666',lw=.6)
    ax.grid(axis='x',alpha=.2)
    ax.set_xlabel('较上一轮11因子每期平均信号收益变化（百分点）')
    ax.set_title('本轮34个新方案中的前12项（样本内开发排名，不代表通过升级门槛）')
    fig.savefig(OUT/'factor_lift.png',dpi=160)
    plt.close(fig)
    lines=['周一梯度提升：第二轮因子优化（v5）',
        '仅使用本项目2018—2023白名单。初始训练2018—2020，逐年向前比较2021—2023；2019/2020用于此前两年选择路径的内部诊断。',
        '主代理/本轮脚本未读取后验成绩、图片、行情或报告；读取拒绝钩子与Parquet白名单启用并验证。本轮没有重新测试任何后验窗口。',
        '本轮36组=2个复现基准+15个旧开发有效因子块组合+11个11因子基准删减+6个新单因子+2个新特征组。',
        '前一轮45组加本轮36组均属于重复使用开发年份的探索；本轮两基准为复现，不是新增独立证据。',
        '目标固定为每期前10只已知普通报价标签的平均毛收益，再对周等权。未扣费用，无法买入/退出信号未删除，未知标签保留计数。',
        '',f'原12因子：{original.mean_signal_return:.4%}/期；上一轮11因子：{anchor.mean_signal_return:.4%}/期。',
        f'本轮最高样本均值：{name(best)}（{best}），{bestrow.mean_signal_return:.4%}/期；较11因子{bestrow.mean_improvement*100:+.4f}个百分点。',
        f'逐年相对11因子提升：2021:{bestrow.improvement2021*100:+.4f}，2022:{bestrow.improvement2022*100:+.4f}，2023:{bestrow.improvement2023*100:+.4f}个百分点。',
        f'最高方案标签覆盖{bestrow.known_coverage:.3%}；共同全标签周{int(bestrow.joint_complete_weeks)}，该口径提升{bestrow.joint_complete_improvement*100:+.4f}个百分点。',
        f'最高方案配对95%块自助区间[{bestrow.improvement_ci_low*100:+.4f},{bestrow.improvement_ci_high*100:+.4f}]个百分点；34新方案近似同时区间[{bestrow.simultaneous_ci_low*100:+.4f},{bestrow.simultaneous_ci_high*100:+.4f}]个百分点。',
        f'删去最好1周的同周配对提升{bestrow.improvement_without_best1_week*100:+.4f}个百分点；删去最好5周后提升{bestrow.improvement_without_best5_weeks*100:+.4f}个百分点。仅为后果敏感性描述，不是可交易规则。',
        f'只用此前两年选择方案的历史路径：均值{adaptive.signal_mean.mean():.4%}/期；较11因子{adaptive.improvement.mean()*100:+.4f}个百分点。',
        '', '预登记升级门槛：总体提升、三个年份均提升、近似同时区间下限>0、覆盖率不低于原11因子超过0.5个百分点，须全部满足。',
        ('本轮有方案通过预登记开发门槛，保留方案：'+name(decision['retained_variant']) if decision['upgrade_eligible'] else '本轮无方案通过全部升级门槛，保留上一轮11因子基准；更高样本均值只作为探索线索。'),
        '即使通过本轮门槛，也仍是开发候选，不能称为独立验证或实际账户盈利保证。',
        '', '逐年每期平均毛收益（不是年度账户收益）']
    for variant in ['original12','anchor11',best]:
        a=annual.loc[annual.variant.eq(variant)].set_index('year')
        lines.append(name(variant)+' | '+' | '.join(f'{y}:{a.loc[y,"mean_signal_return"]:.4%}' for y in [2021,2022,2023]))
    lines+=['仅此前两年选择路径 | '+' | '.join(f'{y}:{adaptive.loc[adaptive.year.eq(y),"signal_mean"].mean():.4%}' for y in [2021,2022,2023]),
        '', '全部36组：每期平均毛收益/较11因子提升/逐年提升（百分点）/标签覆盖/门槛']
    for r in summary.itertuples():
        lines.append(f'{r.variant} | {name(r.variant)} | {r.mean_signal_return:.4%} | {r.mean_improvement*100:+.4f} | {r.improvement2021*100:+.4f}/{r.improvement2022*100:+.4f}/{r.improvement2023*100:+.4f} | {r.known_coverage:.3%} | {r.upgrade_gate}')
    lines+=['','新6特征定义',
        'up_day_fraction60：近60个市场交易日有效报价中上涨天数比例，至少54个有效观测。',
        'positive_run20：截至信号日连续上涨天数，上限20；非上涨或缺失中断。',
        'return_autocorr20：近20日收益与其前一日收益的相关性，至少18对观测。',
        'jump_share20：近20日最大单日绝对收益除以绝对收益之和。',
        'close_to_vwap1：信号日收盘价除以成交额/成交量形成的日均成交价，再减1；量为股，保持已核验原数据单位。',
        'range_compression5_20：近5日平均振幅除以近20日平均振幅。',
        '', '全部信号报价可执行性标记（不删除、不构造成功成交）']
    for r in diagnostics:
        lines.append(f"{r['variant']} | 信号{r['total_signals']} | 开盘不可买{r['opening_cannot_buy']} | 周二收盘不可卖{r['Tuesday_cannot_exit']}")
    lines+=['','核验及局限',
        '原始数据与旧冻结包保持不变。6新因子90组历史前缀复算一致，两基准5个年度全部前30名及分数复现。',
        '首次并行构建出现索引重复，未产生模型成绩；改为顺序构建、独立日历复制并检查唯一性，工程修改已留档，因子公式与模型参数未改。',
        '普通报价标签不构成完整经济收益核准；公司参考价变化/报价缺失为未知，不能当作0，标签覆盖差异仍可能影响结果。',
        '历史退市覆盖、当前供应商历史修订、重复开发择优偏差尚未消除；逐周信号累加不是复利净值或可实现年化。',
        '本轮结束于开发对照与决策，不读取/修改/重复使用先前审计；不据其成绩优化因子，不部署、不下单。']
    (OUT/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    spec=json.loads((OUT/'spec.json').read_text(encoding='utf-8'))
    dump(OUT/'DEVELOPMENT_CANDIDATE.json',dict(retained_variant=decision['retained_variant'],features=decision['retained_features'],
        fixed_HGB=spec['fixed_HGB'],training_boundary='2023-12-31',top_n=10,
        candidate_stage='development_only',upgrade_eligible=decision['upgrade_eligible'],no_final_model_retrained_or_postperiod_audited=True,
        original_frozen_candidate_preserved=True,not_production_selection=True))
    original_registration=json.loads((OLD/'artifact_registration.json').read_text(encoding='utf-8'))
    for r in original_registration['files']:
        assert sha(BASE/r['path'])==r['sha256']
    prior_registration=json.loads((PRIOR/'DEVELOPMENT_ARTIFACTS.json').read_text(encoding='utf-8'))
    for r in prior_registration['files']:
        assert sha(BASE/r['path'])==r['sha256']
    files=[p for p in OUT.iterdir() if p.is_file() and p.name!='ARTIFACTS.json']
    files+=list((BASE/'src_factor_v5').glob('*.py'))
    dump(OUT/'ARTIFACTS.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        no_posterior_reads_or_retests=True,original_and_prior_development_hashes_unchanged=True,
        files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(files)]))
    print('Pre2024development report complete:',OUT/'REPORT.txt',flush=True)


if __name__=='__main__':
    main()
