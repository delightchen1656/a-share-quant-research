"""Descriptive comparison only; never selects a filter or reads sealed audit labels."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
from research import INPUT,OUT,verify_inputs,sha

NAMES={
 'flat_net_change':'横盘15日首尾涨跌',
 'volume_multiple':'信号量 / 横盘均量',
 'base_decline_volume_ratio':'横盘均量 / 下跌均量',
 'close_relative_ma60':'信号收盘偏离MA60',
 'ma20_slope20':'MA20相对20日前变化',
 'return20':'信号日前20日涨跌',
 'return60':'信号日前60日涨跌',
 'body_range_ratio':'阳线实体占振幅',
 'upper_shadow_ratio':'上影占振幅',
 'flat_width':'箱体宽度',
 'day_change':'信号日涨跌',
 'volume5_prior20':'近5日均量 / 此前20日均量',
 'box_position_num':'信号收盘在箱体中的相对位置',
 'decline_return':'前段20日跌幅',
 'close_high60':'信号收盘距60日最高价',
 'volatility20':'近20日日收益波动',
 'is_st':'信号当日ST标记'}

def dist(x):
    x=x.dropna().to_numpy(float)
    return dict(n=len(x),median=float(np.median(x)),q25=float(np.quantile(x,.25)),q75=float(np.quantile(x,.75)))

def pair_effect(a,b):
    a=a.dropna().to_numpy(float);b=b.dropna().to_numpy(float)
    pairs=len(a)*len(b)
    total=int((a[:,None]>b).sum()-(a[:,None]<b).sum())
    return total,pairs

def main():
    verify_inputs();f=pd.read_parquet(INPUT/'features.parquet')
    labels=pd.read_parquet(INPUT/'labels_trainval.parquet')
    f=f.merge(labels.drop(columns='split'),on='event_id',validate='one_to_one')
    assert f.split.isin(['train','validation']).all()
    assert f.label_end.le('2023-12-31').all()
    receipt=sha(OUT/'FROZEN_CANDIDATE.json')
    keys=json.loads((INPUT/'manifest.json').read_text(encoding='utf-8'))['features']
    rows=[]
    for k in keys:
        low=f.loc[f.bad,k];high=f.loc[~f.bad,k];total,pairs=pair_effect(low,high)
        year_total=year_pairs=0;years=[]
        for year,g in f.groupby('year'):
            v,n=pair_effect(g.loc[g.bad,k],g.loc[~g.bad,k])
            if n:
                year_total+=v;year_pairs+=n
                years.append(dict(year=int(year),direction=int(np.sign(v)),low_n=int(g.bad.sum()),high_n=int((~g.bad).sum())))
        rows.append(dict(feature=k,name=NAMES[k],low=dist(low),high=dist(high),
            rank_effect=total/pairs if pairs else None,
            within_year_rank_effect=year_total/year_pairs if year_pairs else None,year_directions=years))
    categories=[('横盘首尾收盘不涨','flat_net_change','<=',0),
        ('信号量不足横盘均量2倍','volume_multiple','<',2),
        ('信号收盘低于MA60','close_relative_ma60','<',0),
        ('20日均线仍下倾','ma20_slope20','<',0),
        ('横盘均量超过下跌均量1.2倍','base_decline_volume_ratio','>',1.2),
        ('信号未收过箱顶','box_position_num','<=',1),
        ('信号日涨幅不足2%','day_change','<',.02)]
    categories_report=[]
    for name,k,op,t in categories:
        row=dict(name=name,feature=k,op=op,threshold=t)
        for islow,label in [(True,'low'),(False,'high')]:
            x=f.loc[f.bad.eq(islow),k].dropna()
            count=int((x<=t).sum()) if op=='<=' else int((x<t).sum()) if op=='<' else int((x>t).sum())
            row[label]=dict(count=count,n=len(x),share=count/len(x))
        categories_report.append(row)
    report=dict(type='descriptive_only_not_a_new_filter',signal_period='2019-2023',
        label_end_boundary='2023-12-31',low_n=int(f.bad.sum()),high_n=int((~f.bad).sum()),
        low_definition='future60maximumadjustedhigh/signalclose-1<10%',
        features=rows,categories=categories_report,whitelist_sha256=sha(INPUT/'manifest.json'),
        sealed2024_labels_not_read=True,post2024_labels_not_read=True,
        prior_frozen_candidate_unchanged=True,viewer_not_modified=True,
        warning='Small, retrospectively selected leader pool; differences describe these samples, not proven predictive rules.')
    (OUT/'COMMON_TRAITS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    f.to_parquet(OUT/'common_traits_cohort.parquet',index=False)
    # Export a standard standalone research figure; groups overlap visibly.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':11})
    fig,axes=plt.subplots(2,2,figsize=(12,8.3),facecolor='#f7f9fc')
    selected=[('flat_net_change',100,'%'),('volume_multiple',1,'倍'),
              ('base_decline_volume_ratio',1,'倍'),('close_relative_ma60',100,'%')]
    rng=np.random.default_rng(0);colors=['#d49539','#4e77bc']
    for ax,(k,mult,unit) in zip(axes.flat,selected):
        groups=[f.loc[f.bad,k].dropna().to_numpy()*mult,f.loc[~f.bad,k].dropna().to_numpy()*mult]
        boxes=ax.boxplot(groups,positions=[1,2],widths=.38,patch_artist=True,showfliers=False,
            medianprops={'color':'#26364c','linewidth':2})
        for box,color in zip(boxes['boxes'],colors):box.set_facecolor(color);box.set_alpha(.22)
        for i,(x,color) in enumerate(zip(groups,colors),1):
            ax.scatter(i+rng.uniform(-.13,.13,len(x)),x,s=25,color=color,alpha=.8,zorder=3)
            ax.text(i,np.median(x),f'  中位数 {np.median(x):.2f}{unit}',fontsize=9,color='#26364c',va='bottom')
        ax.set_xticks([1,2],['不足10%','达到10%']);ax.set_title(NAMES[k],loc='left',pad=12,weight='bold')
        ax.set_ylabel(unit);ax.grid(axis='y',alpha=.16);ax.set_facecolor('white')
        for spine in ['top','right']:ax.spines[spine].set_visible(False)
    fig.suptitle('★龙头箱体信号：低峰组与达标组的共同特征对照',x=.08,ha='left',fontsize=17,weight='bold',color='#26364c')
    fig.text(.08,.02,'2019–2023：20次不足10%，17次达到10%。2024及之后不参与本图。箱线为中位数及四分位区间，点为单次信号。\n未来60日最高点仅用于事后分组；这张图描述样本差异，不是已验证的删除规则。',fontsize=10,color='#68778b')
    fig.subplots_adjust(top=.88,bottom=.15,hspace=.42,wspace=.3,left=.08,right=.96)
    fig.savefig(OUT/'共同特征对照.png',dpi=150,facecolor=fig.get_facecolor());plt.close(fig)
    lines=['龙头箱体低峰信号共同特征对照','',
        '仅使用预先白名单内2019–2023年的37次研发样本：不足10%20次，达到10%17次。',
        '2024封存审计及之后行情标签未参与本次共性分析。不修改既有冻结候选，也不修改软件筛选。','',
        '指标 | 不足10%组中位数 | 达到10%组中位数 | 同年比较方向（-1=低峰组更低）']
    percent=set(keys)-{'volume_multiple','base_decline_volume_ratio','volume5_prior20','box_position_num','is_st'}
    for row in rows:
        k=row['feature'];m=100 if k in percent else 1;unit='%' if k in percent else ''
        directions=', '.join(f"{y['year']}:{y['direction']}" for y in row['year_directions'])
        lines.append(f"{row['name']} | {row['low']['median']*m:.2f}{unit} (n={row['low']['n']}) | {row['high']['median']*m:.2f}{unit} (n={row['high']['n']}) | {directions}")
    lines+=['','固定口径的描述性占比（未搜索新阈值）：']
    for row in categories_report:
        a,b=row['low'],row['high'];lines.append(f"{row['name']}：不足10%组 {a['count']}/{a['n']}={a['share']:.1%}；达到10%组 {b['count']}/{b['n']}={b['share']:.1%}")
    lines+=['','低峰组名单（未来60日最高涨幅）：']
    for row in f[f.bad].sort_values('signal_date').itertuples():
        lines.append(f'{row.signal_date} {row.code} {row.name} {row.peak_return60:.2%}')
    lines+=['','解释边界：横盘有量无明显价格推进、信号日相对放量较弱，是本样本中的统计倾向，不能据此断言吸筹、派发或未来必然低涨幅。',
        '两组都普遍处于下行均线环境，且实体、上影差别很小；共性不等于能够无误删地筛选。',
        '先前冻结过滤候选在2024年审计误删3次达标信号，已拒绝接入软件；本分析不回头改动那次检验。']
    (OUT/'共同特征说明.txt').write_text('\n'.join(lines),encoding='utf-8')
    assert sha(OUT/'FROZEN_CANDIDATE.json')==receipt
    print(json.dumps(dict(cohort=len(f),low=int(f.bad.sum()),high=int((~f.bad).sum()),
        report=str(OUT/'共同特征说明.txt'),figure=str(OUT/'共同特征对照.png'),frozen_candidate_unchanged=True),ensure_ascii=False))

if __name__=='__main__':main()
