"""Render all predeclared operating points, including abstention years and errors."""
import json
import pandas as pd
from study_precision40 import OUT


def pct(x):return '—' if x is None else f'{x:.2%}'


def main():
    m=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    p=pd.read_parquet(OUT/'outer_predictions.parquet')
    lines=['方向2：高准确率优先，排除慢涨/未涨信号',
      '正样本：假设信号次一正式交易日开盘买入后，从B1至B40首次盘中触及买价+3%。',
      '负样本：B41—B59才首次触及，或B0—B59窗口中B1起始终未触及。B0触及不能卖出。',
      '只在原基础信号并剔除连续疑似跌停的清单上筛选，不新增信号、不按未来收益直接删股。',
      '比较11种预设配置：4个规则、逻辑回归、直方图梯度提升、随机森林、4/8类KMeans。',
      '四种验证准入目标92%/95%/97%/99%事先写入PROTOCOL；各池最小内层验证信号为20条龙头/50条样本池。',
      '选择器先满足内层准确率目标，再优先Wilson下界。该下界仅是小样本惩罚，信号存在相关性，不能当作真实95%置信保证。',
      '2021—2024逐年滚动评估：内层在前一年选择方法/阈值，之前成熟标签训练；年初仅用此前成熟标签重拟合，年内不改。',
      '标签要求买入后40个正式交易日窗口成熟才可训练，跨年未成熟信号剔除。预测只用信号日及此前36项白名单特征，无次日开盘跳空/未来极值/股票身份。',
      '2018—2020用于最初训练与内层验证，因此本报告时间评估分母为2688条样本池、516条龙头，不是原4641/881。',
      '所有数据截止2024年底。本对话已经分析过这些时期，因此是研发内时间验证，非未触碰盲测。原947股票集合/当前龙头回看仍有偏差。',
      '未读取2025年及以后行情或结果；未修改查看器与其他模型。',
      '价格触及准确率不是账户胜率、可成交率或净收益；本次不模拟未止盈信号最终亏损。',
      '', '合并时间评估：池 | 内层目标 | 总数 | 保留 | 正确 | 实际准确率 | 坏样本排除 | 正样本误删']
    for x in m['aggregates']:
        lines.append(f"{x['pool']} | {x['target']:.0%} | {x['total']} | {x['selected']} | {x['hits']} | {pct(x['precision'])} | {x['bad_removed']} ({pct(x['bad_removal_rate'])}) | {x['good_removed']} ({pct(x['good_removal_rate'])})")
    lines+=['','逐年（含零信号年）：池 | 内层目标 | 年份 | 总数 | 保留 | 正确 | 实际准确率 | 漏入负样本']
    for x in m['annual']:lines.append(f"{x['pool']} | {x['target']:.0%} | {x['year']} | {x['total']} | {x['selected']} | {x['hits']} | {pct(x['precision'])} | {x['bad_kept']}")
    lines+=['','方法族对比（展示所有配置族，未按外层结果再选赢家）：池 | 内层目标 | 方法族 | 保留 | 正确 | 实际准确率']
    for x in m['families']:lines.append(f"{x['pool']} | {x['target']:.0%} | {x['family']} | {x['selected']} | {x['hits']} | {pct(x['precision'])}")
    lines+=['','重要限制：',
      '所有池在2024年的总选择器均未满足上一年内层准入要求，因此全部弃选；不能把全年空仓算成100%准确率。',
      '目标越严格，时间外实际准确率未必提高；龙头97%目标实际只有90.20%，不能用训练/内层的完美结果宣传。',
      '高准确率依靠删掉大量正样本：样本池95%目标误删2146/2391个正样本；龙头95%目标误删264/455个。',
      '尚未做到排掉全部负样本，也尚未证明跨年稳定达到95%—97%。没有根据这批外层结果再次调参再冒充独立验证。']
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    for pool in ['sample','leaders']:
        g=p.loc[(p.pool==pool)&(p.requested_precision==.95)&p.selected]
        details=['95%内层目标选择器：逐条时间评估入选信号（包括误选）',
            '注意95%为选择时目标，不是事后实现准确率。',
            '代码 | 信号日 | 年度方法 | B1—40触及+3% | 首次T+1触及日']
        for _,e in g.sort_values(['date','code']).iterrows():
            day='窗口内未触及' if pd.isna(e.first_t1_touch_day) else 'B'+str(int(e.first_t1_touch_day))
            details.append(f"{e.code} | {e.date} | {e.method} | {'是' if e.target else '否'} | {day}")
        (OUT/(pool+'_95目标入选明细.txt')).write_text('\n'.join(details),encoding='utf8')
    print(OUT/'研究说明.txt')


if __name__=='__main__':main()
