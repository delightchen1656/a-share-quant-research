# 沪深收益优先M02—M18研究

该路线先撤销旧低仓位约束，依次研究收益排序、强势回踩、低波反转、机会质量、风险节奏和公开策略复现。它是R08之前的另一条系统研究线，没有晋升为当前正式入口。

| 阶段代码 | 对应策略或思路 |
|---|---|
| `m02_simple_baselines.py` | 可交易收益排序、强势调整后延续、板块联动三个最简基线 |
| `m03_walkforward_return_rank.py` | 5/10/20日滚动收益排名模型 |
| `m03_reversal_regime.py` | 低波反转、确认反转、长期反转和市场状态 |
| `m03_limit_event_study.py` | 涨停后延续与回调事件 |
| `m04_candidate_blends.py` | R8/Q3候选持股数、周期与固定组合 |
| `m04_portfolio_overlays.py` | 净值趋势、目标波动、回撤和指数覆盖 |
| `m04_residual_reversal.py` | 市场beta残差反转 |
| `m05_opportunity_quality_gates.py` | 普跌、离散度等10种机会质量门控 |
| `m06_asymmetric_risk_state.py` | 不对称降仓与恢复状态 |
| `m06_risk_cadence_blends.py` | 10/40日风险检查和双节奏组合 |
| `m07_public_strategy_reproductions.py` | 反MAX、低特异波动、量价质量等公开策略复现 |
| `m07_public_strategy_combinations.py` | 公开防守袖套与核心策略组合 |
| `m08_seasonality.py` | 同月收益季节性 |
| `m08_factor_portfolio_momentum.py` | 五因子袖套的组合动量 |
| `m08_pit_style_clusters.py` | 只用当时数据生成的动态风格簇 |
| `m09_three_sleeve_frontier.py` | 三防守袖套的固定有效前沿 |
| `m10_position_risk_weighting.py` | 逆特异波动等持仓权重 |
| `m11_walkforward_reversal_success.py` | 滚动反转成功率二级模型 |
| `m13_core_overnight_frontier.py`、`m13_overnight_path_strategies.py` | 隔夜、日内和价格路径收益源 |
| `m14_staggered_cohorts.py` | 2/4/8批错峰建仓 |
| `m15_q3_overnight_fusion.py` | Q3与隔夜因子融合 |
| `m16_intraday_flow_reversal.py` | 日内资金流反转 |
| `m17_equity_state_sweep.py` | 组合净值状态和波动覆盖 |
| `m18_short_residual_reversal.py` | 5/10日短期特异反转 |

路线最高记录约为18%组合波动目标、40日检查的Sharpe 0.759，仍未达到1.0目标。诊断脚本、分析器和输出报告未恢复；结论以本文和 `strategies/hushen/HISTORY.md` 为准。
