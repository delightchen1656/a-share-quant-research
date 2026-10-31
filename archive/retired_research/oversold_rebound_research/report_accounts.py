"""Account report and equity plots; retain both explicitly labeled missing-price cases."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from account_backtest import OUT


def main():
    result=json.loads((OUT/'summary.json').read_text(encoding='utf8'));items=result['results']
    clean=result.get('exclude_special_cases',False)
    proxy=None if clean else json.loads((OUT/'missing_price_sensitivity.json').read_text(encoding='utf8'))
    lines=['方向2：筛选前后，3%止盈、买入后第5日收盘平仓的8组账户',
      '期间：2021年初—2024年底连续账户；2018—2020用于筛选器初始训练，不倒推模型。2025年之后未读取。',
      '范围：已有947股票白名单中的基础信号，排除连续疑似跌停；非全量沪深主板普查。龙头为当前冻结归属回看。',
      '筛选后：固定上轮验证目标95%的逐年时间筛选结果，不按本次账户收益重新调模型；2024年两池均无入选信号。',
      '100万元50槽 / 10万元5槽，两者每槽固定2万元，包含买入费用；盈利留在现金中，不自动提高单槽额度。',
      '买入：信号次一正式交易日开盘，按用户要求假设保证成交，不做涨停/流动性拒单。现金及槽位不足仍会跳过。',
      '股数向下取100股整手，必要时再减100股使成交额+费用不超过预算；同一股票已持仓不加仓，同日按代码升序。',
      'B0是买入当天，不能卖出。B1至B5盘中触及成本上方3%止盈；若开盘超过目标，按开盘卖；否则目标向上取分成交。',
      'B5（买入后第5个正式交易日）未止盈则收盘卖，不另设止损。收盘或盘中卖出资金不能拿去买同日开盘。',
      '佣金双边万三、每笔最低5元；过户费双边2022-04-29前万分0.2、之后万分0.1；卖方印花税2023-08-28前千一、之后万分五。',
      '原始价格与真实整数股数记账；区分分红除权、现金支付、送转股上市日期、应收现金；持股短期现金/应税红股按20%红利税，转增不计红利税。',
      '公司行动审计基于全部候选持有窗的原始/前复权因子变动，复用核验哈希的边界内记录，补查11个缺失年度；不宣称全年度/全市场公司行动表完整。',
      '现金与逐笔已实现损益已对账；6项单元测试覆盖T+1、B5、槽位、资金时序、分红应收和送转上市。',
      '最大回撤按每日收盘总权益计算，非盘中最大回撤。止盈率与净盈利交易比例不同。',
      '', '8组主结果（已排除到期缺价特殊信号）：' if clean else '8组主结果（缺价时顺延，1笔例外见下）：',
      '范围 | 筛选 | 初始/槽位 | 成交数 | 止盈/强平 | 期末资金 | 累计收益 | 年化收益 | 最大回撤 | 净盈利交易比例']
    for x in items:
        s=x['summary'];pool='龙头' if s['pool']=='leaders' else '样本池';stage='后' if s['filtered'] else '前'
        lines.append(f"{pool} | {stage} | {s['capital']}/{s['slots']} | {s['trades']} | {s['takeprofit']}/{s['forced']} | {s['final_equity']:.2f} | {s['total_return']:.2%} | {s['annualized_return']:.2%} | {s['max_drawdown']:.2%} | {s['net_win_rate']:.2%}")
        t=pd.read_parquet(OUT/x['key']/'trades.parquet')
        detail=['代码 | 股票 | 信号日 | 买入日 | 买股数 | 买价 | 卖出日 | 买入后第几日 | 原因 | 净损益 | 净收益率 | 总费用']
        for _,r in t.sort_values(['buy_date','code']).iterrows():detail.append(f"{r.code} | {r['name']} | {r.signal_date} | {r.buy_date} | {r.buy_qty} | {r.buy_price:.2f} | {r.sell_date} | B{r.buy_offset} | {r.reason} | {r.pnl:.2f} | {r.return_pct:.2%} | {r.fees:.2f}")
        (OUT/x['key']/'逐笔交易.txt').write_text('\n'.join(detail),encoding='utf8')
    if clean:
        lines+=['','按用户要求排除特殊情况：',
          '统一从信号清单排除到期缺价、实际触发延迟退出的特殊信号，释放槽位后按时间重跑所有账户，不直接扣原交易损益。',
          '排除清单：'+json.dumps(result['excluded_specials'],ensure_ascii=False),
          '全部8组最终延迟退出数量均为0；不采用停牌前收盘价假设成交。',
          '这属于使用后续可交易性信息清理异常样本，不是买入前能够知道的过滤条件，也没有用于重训原筛选器。']
    else:
        lines+=['','停牌缺价例外与理想假设敏感性：',
      '仅样本池筛选前100万元/50槽组：002633申科股份，2022-05-05买，B5应为05-12；当日无有效报价。',
      '主表不造价格，顺延至05-18复牌开盘8.32元卖出。这笔偏离严格B5规则，不能叫完全符合用户强平规则。',
      '另一份结果在B5使用停牌前最近有效收盘价作为理想成交估值，仅是假设，不是真实到期收盘价：']
        s=proxy['summary'];lines.append(f"假设价版：期末{s['final_equity']:.2f}，总收益{s['total_return']:.2%}，年化{s['annualized_return']:.2%}，最大回撤{s['max_drawdown']:.2%}，成交{s['trades']}笔。")
        lines+=['其他7组没有到期缺价导致的延迟，两个缺价口径对它们无影响。']
    lines+=['', '逐年收益 / 年内最大回撤：范围 | 筛选 | 资金/槽位 | 年份 | 收益 | 回撤 | 年末权益']
    for x in items:
        s=x['summary']
        for y in x['yearly']:lines.append(f"{s['pool']} | {'after' if s['filtered'] else 'before'} | {s['capital']}/{s['slots']} | {y['year']} | {y['return_pct']:.2%} | {y['max_drawdown']:.2%} | {y['end_equity']:.2f}")
    lines+=['','解释：',
      '筛选器原目标是40日内触及+3%，本次账户最多等到B5，不能把上轮约95%准确率等同于本次止盈率或收益率。',
      '50槽账户虽分散，但筛选后信号很少，长期现金占比高；5槽账户更易在信号扎堆时满槽，实际成交集合不同。',
      '原始股数向下取整导致每笔资金并非严格相等；账户收益不会等于信号平均收益乘次数。',
      '保证成交是用户指定的理想假设，不代表历史涨跌停队列和成交能力已经验证。',
      '本研究复用了先前已分析时期，仍属于研发内历史比较，不能作为全新盲测。',
      '税费依据：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230827_5725662.shtml',
      '过户费变更依据：https://www.xinhuanet.com/2022-04/28/c_1128605983.htm']
    (OUT/'账户回测说明.txt').write_text('\n'.join(lines),encoding='utf8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(13,8),sharex=True)
    styles={('sample',False):('#b75c5e','--'),('sample',True):('#286fd0','-'),('leaders',False):('#bf963d','--'),('leaders',True):('#218a71','-')}
    for x in items:
        s=x['summary'];nav=pd.read_parquet(OUT/x['key']/'daily_nav.parquet');color,style=styles[(s['pool'],s['filtered'])]
        ax=axes[0] if s['capital']==1000000 else axes[1]
        ax.plot(pd.to_datetime(nav.date),(nav.equity/s['capital']-1)*100,color=color,ls=style,lw=1.2,
            label=('样本池' if s['pool']=='sample' else '龙头')+('筛选后' if s['filtered'] else '筛选前'))
    for ax,title in zip(axes,['100万元 / 50槽位','10万元 / 5槽位']):
        ax.set_title(title);ax.set_ylabel('累计账户收益（%）');ax.grid(alpha=.16);ax.legend(ncol=4,fontsize=9);ax.axhline(0,color='#bbb',lw=.5)
    fig.suptitle('方向2：3%止盈，买入后B5收盘退出\n固定单槽2万元、整手、含税费；'+('已排除到期缺价特殊信号' if clean else '样本池筛选前50槽含1笔停牌顺延例外'),fontsize=13)
    fig.tight_layout(rect=[0,0,1,.90]);fig.savefig(OUT/'八组账户净值.png',dpi=140);plt.close(fig)
    print(OUT/'账户回测说明.txt')


if __name__=='__main__':main()
