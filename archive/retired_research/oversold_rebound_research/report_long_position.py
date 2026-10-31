"""Cross-check overlapping hypotheses; do not treat marginal differences as independent."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from study_long_position import OUT
from study_continued_decline import metrics


def main():
    d=pd.read_parquet(OUT/'events.parquet')
    d=d.loc[d.is_leader & d.position3y.notna() & d.touch_order.ne('same_day_unknown')].copy()
    rows=[]
    for (price,position),g in d.groupby([d.raw_signal_close>=20,d.position3y>=.5]):
        rows.append(dict(price_ge20=bool(price),position3y_upper_half=bool(position),**metrics(g)))
    high=d.loc[d.position3y>=.5];low=d.loc[d.position3y<.5]
    check=dict(cross=rows,baseline=metrics(d),removed_high=metrics(high),kept_low=metrics(low),
        removed_high_hit10=int((high.max_up60>=.10).sum()),total_hit10=int((d.max_up60>=.10).sum()))
    (OUT/'cross_checks.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['','交叉检查：仅有完整3年历史的481条龙头基础信号，避免窗口覆盖不同导致比较失真。',
      '单价 | 3年位置 | 数量 | 修正失败率']
    for x in rows:lines.append(f"{'≥20元' if x['price_ge20'] else '<20元'} | {'上半区' if x['position3y_upper_half'] else '下半区'} | {x['n']} | {x['continued_rate']:.2%}")
    lines+=['高价与高位没有显示简单相加关系：≥20元组里，上半区反而低于下半区。不能把两个边际关联当作两个独立风险原因。',
      '若直接排除3年上半区：删91条，其中20条修正失败、62条曾触及+10%。保留390条，修正失败率从同覆盖基准13.51%降至11.54%。',
      '同覆盖触及+10%的357条中会误删62条（17.37%）；删掉失败20/65（30.77%）。这是描述性取舍，不是已冻结推荐过滤器。',
      '2021—2024上半区样本数分别41、38、6、6；末两年高位样本极少，不能宣称逐年稳定。']
    with (OUT/'研究说明.txt').open('a',encoding='utf8') as f:f.write('\n'+'\n'.join(lines))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(11,5.1))
    for ax,price in zip(axes,[False,True]):
        group=[x for x in rows if x['price_ge20']==price]
        values=[x['continued_rate']*100 for x in group]
        bars=ax.bar(['3年区间下半部','3年区间上半部'],values,color=['#389b92','#de7765'],width=.56)
        for bar,x in zip(bars,group):ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+.8,f"{x['continued_rate']:.2%}\n{x['continued']}/{x['n']}条",ha='center',fontsize=11)
        ax.set_ylim(0,40);ax.set_ylabel('修正后持续走弱比例（%）');ax.set_title('原始单价'+('≥20元' if price else '<20元'));ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('方向2：长期位置与单价存在交互，不能简单相加\n同一批481条龙头信号；先触及+10%的不算失败',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.88]);fig.savefig(OUT/'长期位置与单价交叉.png',dpi=140);plt.close(fig)
    print('\n'.join(lines))


if __name__=='__main__':main()
