"""Reproduce the holding-rule ablation and consolidate the completed research rounds."""
import json
import pandas as pd
import backtest as base


def main():
    root=base.ROOT
    out=root/'return_exploration'
    raw,_,_=base.load_data()
    predictions=pd.read_csv(root/'medium_term/final_predictions.csv',index_col=0,parse_dates=True)
    curve,trades,_,_=base.simulate(raw,predictions.target,'previous_without_minimum',
                                  start='2025-01-01',min_hold_months=0)
    curve.to_csv(out/'previous_without_minimum_equity.csv')
    trades.to_csv(out/'previous_without_minimum_trades.csv',index=False)
    ablation=base.metrics(curve,trades)
    (out/'previous_without_minimum_summary.json').write_text(json.dumps(ablation,indent=2),encoding='utf-8')
    static=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    adaptive=json.loads((out/'adaptive/summary.json').read_text(encoding='utf-8'))
    old=json.loads((root/'medium_term/summary.json').read_text(encoding='utf-8'))
    pd.testing.assert_series_equal(curve.equity,
        pd.read_csv(root/'medium_term/selected_final_equity.csv',index_col=0,parse_dates=True).equity,
        check_names=False,check_freq=False)
    rows=[('上一版参数，已取消最低持仓',ablation),
          ('5340组中验证年化最高者',static['results']['cagr_champion']),
          ('验证期前10名投票',static['results']['top10_vote']),
          ('48组中验证最优轮换规则',adaptive['final']),
          ('买入持有',static['results']['buy_hold'])]
    lines=['# 恒银科技年化收益探索：本轮总报告','',
           '已取消至少持有一个月和验证回撤上限，比较5,340组固定策略、48组自适应轮换规则，并对上一版做了只取消持仓限制的直接对照。',
           '本轮新增的验证优胜方案，没有在2025年至今的后期历史评估中超过上一版。原版取消最低持仓后，交易和账户净值完全不变；两次持仓本身就是66天、97天。',
           '', '## 同期比较','',
           f"初始资金10万元，区间2025-01-02至{static['data_last']}，已计手续费、印花税、过户费、滑点及简化分红税；最大名义仓位100%，不融资、不做空。",'',
           '|策略|累计收益|年化收益|最大回撤|期末资金|买入/卖出|',
           '|---|---:|---:|---:|---:|---:|']
    for label,m in rows:
        lines.append(f"|{label}|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_drawdown']:.2%}|{m['final_equity']:,.2f}元|{int(m['buy_count'])}/{int(m['sell_count'])}|")
    lines+=['','## 搜索的范围与结果','',
            '- 固定策略：逻辑回归、两种梯度提升树，预测5/10/21/42/63/126交易日，两个收益标签、两种训练窗口、不同进出阈值；另含均线、突破、RSI与布林带，测试不设持仓期、最长21交易日、最低21交易日及收盘止损/移动止盈。',
            '- 动态策略：每月/季度按最近21/63/126/252交易日表现，从策略池选前1/3/10名，比较收益率或收益/回撤评分。',
            f"- 固定策略验证期最高年化{static['results']['cagr_champion_validation']['cagr']:.2%}，后期年化{static['results']['cagr_champion']['cagr']:.2%}。轮换规则选参期年化{adaptive['validation']['cagr']:.2%}，后期年化{adaptive['final']['cagr']:.2%}。高验证收益没有延续，不能拿选参期数字当实盘预期。",
            '- 取消限制并不等于强制缩短持仓，搜索仍允许自行选择较长持仓。市场T+1、涨跌停和交易成本继续保留。',
            '', '## 当前可保留的参考基线','',
            '上一版逻辑回归：预测次日起63交易日复权收益超过5%的概率，达到65%买入，降至30%及以下卖出；每季度用当时已完成的标签重训。最低持仓限制现已解除。',
            f"它在本段评估中的年化为{ablation['cagr']:.2%}，最大回撤{ablation['max_drawdown']:.2%}，共两次完整交易。两次交易不足以证明稳定性；这里保留它作为比较基线，不将它重新包装成独立测试选出的新策略。",'',
            '## 数据隔离与局限','',
            '2020—2022初始训练；固定方案使用2023—2024选参，再评估2025以后。轮换方案使用2023形成评分历史、2024选轮换规则，再评估2025以后。训练和每次换选都只使用当时已知历史。',
            '然而后期行情已经在多轮研究中被查看，轮换结构也是看到固定策略失效后追加的探索；所有后期数字均应视为有研究选择偏差的历史评估，不是完全独立测试。',
            '12项执行与轮换边界测试通过；数组搜索账户已与原现金账户逐日对齐；5,340个专家在追加未来数据后，2023—2024期末净值逐一与此前结果相同；截断未来行情不改变过去信号。',
            '日线不能精确模拟竞价排队，止损在收盘触发次日执行，分红税统一按20%近似。未使用杠杆放大收益，未根据后期结果把另一个候选偷偷改称冠军。',
            '', '## 文件入口','',
            '- [固定策略完整报告](REPORT.md)',
            '- [动态轮换报告](adaptive/REPORT.md)',
            '- [全部固定策略验证结果](all_validation_candidates.csv)',
            '- [全部轮换规则验证结果](adaptive/meta_validation_candidates.csv)',
            '- [无最低持仓限制的基线交易明细](previous_without_minimum_trades.csv)',
            '- [执行入口与环境](../README.md)',
            '', '![各轮策略对照](adaptive/research.png)','']
    (out/'OVERVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Consolidated report:',out/'OVERVIEW.md')
    print('Holding-rule ablation: daily equity unchanged; CAGR',ablation['cagr'])


if __name__=='__main__':
    main()
