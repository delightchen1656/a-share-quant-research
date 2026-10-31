"""Verify prefix causality and render an honest pilot report, including failed signals."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from study import SOURCE, OUT, scan, independent


def main():
    # Verify every feature on multiple truncation dates, then perturb future bars.
    q = pd.read_parquet(SOURCE/'qfq/000006.parquet')
    r = pd.read_parquet(SOURCE/'raw/000006.parquet')
    full,_,_ = scan(q,r)
    for cut in ['2020-06-30','2022-04-29','2024-06-28']:
        mask = q.date.astype(str) <= cut
        prefix,_,_ = scan(q.loc[mask],r.loc[mask])
        got = full.loc[full.date.astype(str) <= cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix,got)
        fq,fr=q.copy(),r.copy()
        for col in ['open','high','low','close','volume']:
            fq.loc[~mask,col] *= 100
            fr.loc[~mask,col] *= 100
        altered,_,_=scan(fq,fr)
        pd.testing.assert_frame_equal(prefix,altered.loc[altered.date.astype(str) <= cut].reset_index(drop=True))
        assert independent(prefix.candidate) == [i for i in independent(full.candidate) if i < len(prefix)]
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    verification={'prefix_dates_checked':3,'future_perturbation_invariance':'passed',
                  'first_signal_prefix_invariance':'passed','input_hashes':'verified by study.py',
                  'future_data_used_to_select_signals':False}
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf8')
    names={'baseline':'基础超跌转阳','signal_volume_ge_1_2':'信号量≥前20日均量1.2倍',
           'signal_volume_ge_1_5':'信号量≥前20日均量1.5倍','prior3_volume_shrink':'前3日均量≤更前10日均量0.8倍',
           'strong_body_ge_0_6':'阳线实体≥全天振幅60%','close_above_prev_high':'收盘超过前日最高价',
           'long_lower_shadow':'下影≥全天振幅20%','deep_below_ma20':'收盘低于MA20至少10%'}
    lines=['方向2：超跌反弹——第一轮形态研究',
           '研发截止2024-12-31。没有读取2025年及之后行情；截图含边界后示例，因此不是全新独立盲测。',
           '', '共同结构假设：下跌趋势→末段加速→均线负乖离→低位阳线确认。',
           'MA5拐头、均线交叉与后续连阳可能属于反弹结果，不要求回看未来后再把低点标成信号。',
           '截图只能支持价格形态假设；成交量刻度、股票、完整日期和信号锚点不齐，不能声称5图均通过下面的数值条件。',
           '', '基础规则（未按收益搜索阈值）：',
           '1. 信号日前20个有效交易日收盘跌幅≥15%；前5日跌幅≥8%。',
           '2. 信号日收盘低于MA20和MA60；最近3日最低价距20日最低价≤2%。',
           '3. 信号日为阳线，实体/振幅≥40%、上影/振幅≤30%；收盘距最近3日最低价≤12%。',
           '4. 仅使用当天与此前行情。同股首次触发后10个有效交易日内不重复；并非五阴三阳。',
           '5. 分组均在同一基础信号清单上附加条件，筛掉后不向后补选。',
           '', '数据与收益口径：',
           '已有白名单947只主板股票，属于以前箱体研究的股票集合，不能代表全量主板。',
           '龙头是该白名单中已有的当前龙头标记回看，并非历史时点龙头。',
           '按下一正式交易日开盘为起点，观察D1—D60。停牌/无成交日剔除，不用下一可成交日替代缺失的D1；D60缺价不进完整样本。',
           '价格为已有前复权路径，非账户经济收益；未扣费、未模拟涨跌停成交、分红与股数变化。触及+5%与跌超30%可在同一事件同时发生。',
           '最高/最低都是事后极值；本轮未剔除涨超100%的样本，报告均值时同时给中位数，避免悄悄删除极端结果。',
           '', '分组统计（基础之上只追加一项）：']
    for pool,title in [('sample_mainboard','947只股票样本池'),('leaders','其中龙头子样本')]:
        lines.extend(['',title,'条件 | 完整样本 | 触及+5% | 触及+10% | 跌超30% | 平均最大涨幅 | 中位最大涨幅 | 平均最大跌幅 | D60收盘平均变化'])
        for x in summary['rules']:
            if x['pool']==pool:
                vals=[names[x['rule']],str(x['complete60'])]+[f'{x[k]*100:.2f}%' for k in ['touch5','touch10','fall30','mean_max_up60','median_max_up60','mean_max_down60','mean_close60']]
                lines.append(' | '.join(vals))
    lines.extend(['','龙头：基础 vs 低于MA20至少10%的逐年对比',
                  '年份 | 基础样本/+5%触及/跌超30% | 深乖离样本/+5%触及/跌超30%'])
    for year in range(2018,2025):
        pairs=[]
        for rule in ['baseline','deep_below_ma20']:
            x=next(x for x in summary['yearly'] if x['pool']=='leaders' and x['year']==year and x['rule']==rule)
            pairs.append(f"{x['complete60']} / {x['touch5']*100:.2f}% / {x['fall30']*100:.2f}%")
        lines.append(f'{year} | '+' | '.join(pairs))
    lines.extend(['','本轮判断：',
                  '深负乖离是值得继续验证的候选；放量提高部分反弹幅度指标，但在龙头里不能据此认为尾部风险下降。',
                  '下影更长、实体更饱满、突破前日高点单独都没有稳定提升。前3日缩量在龙头的跌超30%频率较低，但触及率改善很小。',
                  '按时间有明显差异，且信号常扎堆于市场急跌，同一股票的60日观察窗也会重叠；不能把数百条信号当作数百次独立验证。',
                  '当前只完成描述性筛选。未训练机器学习，未证明因果共同点或稳定90%命中；方向2未部署到查看器，方向1.1/1.2未改。',
                  '下一阶段应扩大为经过审计的主板白名单，并与同股同年其他阳线匹配比较；按时间及市场急跌事件整组验证，不按随机行切分。'])
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')

    # Deterministically display both outcomes. Labels only choose illustrations.
    d=pd.read_parquet(OUT/'events.parquet')
    leaders=d.loc[d.is_leader & d.complete60 & (d.below_ma20<=-.10)].sort_values(['date','code'])
    winners=leaders.loc[(leaders.max_up60>=.10)&(leaders.max_down60>-.15)].head(2)
    failures=leaders.loc[(leaders.max_up60<.05)|(leaders.max_down60<=-.30)].head(2)
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,2,figsize=(15,9))
    for ax,(_,e) in zip(axes.flat,pd.concat([winners,failures]).iterrows()):
        q=pd.read_parquet(SOURCE/'qfq'/(e.code+'.parquet'))
        r=pd.read_parquet(SOURCE/'raw'/(e.code+'.parquet'))
        valid=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)
        q=q.loc[valid].reset_index(drop=True)
        t=int(np.flatnonzero(q.date.astype(str)==str(e.date))[0]);start=max(0,t-45);end=min(len(q),t+61)
        x=np.arange(start,end)-t
        for j,i in enumerate(range(start,end)):
            o,h,l,c=q.loc[i,['open','high','low','close']]
            color='#d94b58' if c>=o else '#148c7d'
            ax.vlines(x[j],l,h,color=color,lw=.8)
            ax.add_patch(plt.Rectangle((x[j]-.32,min(o,c)),.64,max(abs(c-o),.003),edgecolor=color,facecolor='white' if c>=o else color,lw=.8))
        for win,color in [(5,'#d59531'),(20,'#469dc5'),(60,'#d65083')]:
            ax.plot(x,q.close.rolling(win).mean().iloc[start:end],lw=.9,color=color,label=f'MA{win}')
        ax.axvline(0,color='#5568bd',ls='--',lw=1)
        ax.axvspan(.5,x[-1],color='#eef1f7',alpha=.6,zorder=-5)
        ax.set_title(f"{e['name']} {e.code} · {e.date}\n60日最高 {e.max_up60:+.1%} / 最低 {e.max_down60:+.1%}",fontsize=11)
        ax.set_xlabel('信号日 D0；右侧为事后走势（仅供复盘）');ax.grid(alpha=.14);ax.legend(fontsize=8,loc='upper left')
    fig.suptitle('方向2：超跌后低位转阳 · 两个反弹案例与两个失败/高风险案例\n事后分组只用于展示，信号形成不读取未来',fontsize=15)
    fig.tight_layout(rect=[0,0,1,.92]);fig.savefig(OUT/'形态与失败案例.png',dpi=140);plt.close(fig)
    print(json.dumps(verification,ensure_ascii=False));print(OUT/'研究说明.txt')


if __name__=='__main__':main()
