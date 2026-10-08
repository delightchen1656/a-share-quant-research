# 科创高进攻与结构改进版本

本方向保存科创3-1形成过程中的研究代码。原3-1、标准日频版和3-2候选已归档至 `archive/kechuang/20261009_before_unification/`；当前唯一科创入口是 `strategies/kechuang/supermind_kechuang_1.py`。

| 代码 | 对应策略或思路 |
|---|---|
| `research_high_risk_20_directions.py` | 20个单变量进攻方向：阈值、候选数、持仓数、仓位、止损、止盈和持有期；选出0.63阈值 |
| `research_structural_10_directions.py` | 10个非网格结构方向；强趋势自适应延期胜出，形成3-1 |
| `research_sharpe_portfolios.py` | 科创3-1与2-2的固定配比、逆波动、目标波动和回撤节流组合 |
| `research_public_sharpe_structures.py` | 基于公开思路的波动目标、趋势确认和下行风险结构 |
| `baseline_3_1_daily_capital_120k.py` | 3-1标准日频的12万元资金派生版 |
| `baseline_3_1_daily_120k_dynamic20.py` | 12万元派生版上的动态20%结构 |

历史冻结结论：原3-1使用0.63阈值，30日到期时浮盈达到10%则延长至最多60自然日。120k和dynamic20只作为资金口径研究；这些旧名称均不属于当前入口。
