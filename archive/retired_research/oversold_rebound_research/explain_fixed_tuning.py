"""Extract parameter explanation from the completed grid, no new optimization."""
import json
from study import ROOT
from tune_fixed_income import OUT,GRID,config_key


def main():
    m=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    rows=json.loads((OUT/'comparison.json').read_text(encoding='utf8'))
    lookup={config_key(r['config']):r for r in rows};new=m['winner']['config']
    lines=['v15每个参数的调整过程与控制变量拆解',
      '实际流程是联合网格搜索，不是逐参数贪心调整。以下单参数比较是从已完成网格提取的事后解释。',
      '2021—2024均参与参数选择，不是独立盲测；不存在这些参数已在2021年之前确定的说法。',
      '统一10万元账户，逐日模拟现金、槽位、T+1、整手、税费、公司行动及同日代码排序。未读2025年之后的数据。',
      '', '1. 原候选：价格<10元，低于MA20至少10%，5%止盈，B3收盘，5槽，不加价格止损。',
      '2. 固定网格：'+json.dumps(GRID,ensure_ascii=False),
      '4×4×3×4×5×3=2880个不同组合。每个组合独立按时间跑完整账户，不能用单笔平均收益替代。',
      '3. 先要求四年各年收益>0、每年至少10笔买入、全期收盘权益最大回撤<=12%，合格1299组。',
      '4. 优先保留四个年度收益均不低于旧候选、且全期回撤不高于旧候选的4组；再按最低年度收益、累计收益、回撤依次排序。',
      '5. 在同一优先层中，有合格邻域时优先邻域稳定者：至少75%邻居四年均盈利，邻居最低年度收益中位数至少达到自身的75%。',
      '6. 最终选中'+json.dumps(new,ensure_ascii=False),
      '7. 邻域9组均四年正收益，但这些邻居也在同一研发样本内，不能视作独立验证。',
      '8. 发现002069/2022-04-27到期缺价后，所有涉及组合统一排除重跑；旧候选按相同排除口径复核，权益变化0元。',
      '', '参数的控制变量比较：以下每次只改所列参数，其余均固定为最终v2配置。',
      '参数 | 测试值 | 累计收益 | 最低年度收益 | 全期最大回撤 | 成交笔数']
    names=dict(price='信号日原始收盘价上限（严格小于）',deviation='相对MA20至少低多少',take_profit='止盈幅度',forced_day='买入后第几日收盘',slots='槽位数',stop_loss='价格止损')
    for field,values in GRID.items():
        for value in values:
            config=dict(new);config[field]=value;r=lookup[config_key(config)];s=r['result']['summary']
            lines.append(f"{names[field]} | {value} | {s['total_return']:.2%} | {r['worst_year']:.2%} | {-s['max_drawdown']:.2%} | {s['trades']}")
    lines+=['','便于理解的逐步回放：这是事后拆解，不是真实调参顺序。',
      '步骤 | 累计收益 | 最低年度收益 | 全期回撤']
    config=dict(price=10,deviation=.10,take_profit=.05,forced_day=3,slots=5,stop_loss=None)
    sequence=[('原候选',None,None),('仅把MA20偏离10%改8%','deviation',.08),('再把5槽改7槽','slots',7),('再把止盈5%改6%','take_profit',.06)]
    for title,field,value in sequence:
        if field:config[field]=value
        r=lookup[config_key(config)];s=r['result']['summary']
        lines.append(f"{title} | {s['total_return']:.2%} | {r['worst_year']:.2%} | {-s['max_drawdown']:.2%}")
    lines+=['','解释边界：',
      '单价12元、5槽等有更高累计收益的组合，但弱年份收益更低或回撤超限制，因此没有只按总收益挑选。',
      '加5%/8%止损在此账户时序下会改变持仓退出及后续可买股票，不能把它当作对同一组交易简单截断损失；也不能据本样本推论不止损在实盘更安全。',
      'MA20偏离8%和止盈6%分别在本轮网格边缘，范围外尚未测试，不能声称全局最优。',
      '邻域拆解不能证明独立因果贡献；多个参数会通过买卖时间、现金和满槽发生交互。']
    (OUT/'参数调整全过程.txt').write_text('\n'.join(lines),encoding='utf8')
    print(OUT/'参数调整全过程.txt')


if __name__=='__main__':main()
