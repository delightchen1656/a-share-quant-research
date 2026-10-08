# 已退出的沪深基准2与Monthly-A研究

该方向历史名称为“沪深基准2：八成反转”，冻结结构 `deep_reversal_20_0.8`。历史本地参考为年化20.46%、最大回撤27.83%、Sharpe 1.031，未超过当时沪深基准1，且选型过程已接触验证结果，因此现已退出正式范围。

## 代码与思路

| 代码组 | 对应策略或思路 |
|---|---|
| `core_execution_engine.py`、`group_controls.py` | 基准2公共撮合与分组控制 |
| `round01_research.py`、`round02_defensive_selection.py` | 第一轮31路线与第二轮防守候选冻结 |
| `research_group_round01.py`—`research_group_round03.py` | 三轮分组研究、风险状态和信号压力检验 |
| `research_cadence_multiround.py` | 月度/双月/季度调仓节奏 |
| `research_calendar_structure.py` | 共同日历和结构调仓 |
| `research_moderate_tuning.py` | 冻结候选附近的中等幅度调参 |
| `research_monthly6_neighbors.py`、`research_monthly_robustness.py` | 月度六邻域和跨窗口稳健性 |
| `research_phase_robustness.py`、`research_start_date_robustness.py` | 调仓相位和起始日敏感性 |
| `research_robust_policy.py` | 稳健策略族筛选 |
| `research_two_family_return_sharpe.py` | 两类信号的收益/Sharpe联合比较 |
| `research_provisional_two_rounds.py` | 临时候选的两轮冻结验证 |
| `research_quarter_anchor_all_years.py`、`research_quarter_anchor_scan.py`、`research_quarter_anchor_scan_2021.py` | 季度锚点及各年份扫描 |
| `research_small_account.py` | 10万元整手可买性与小账户版本 |

Monthly-A子线保留以下版本：

- `monthly_a_aligned_engine.py`：平台对齐执行引擎；
- `monthly_a_covweight_engine.py`、`research_monthly_a_covweight_sharpe.py`：协方差权重；
- `monthly_a_guard_engine.py`、`research_monthly_a_guard_refinement.py`、`research_monthly_a_guard_sharpe.py`：风险守卫；
- `research_monthly_a_hundred_rounds.py`：100轮既有历史研究；
- `monthly_a_invested_engine.py`、`research_monthly_a_invested_sharpe.py`：实际投入仓位口径；
- `research_monthly_a_phase_sharpe.py`：调仓相位；
- `research_monthly_a_return_frontier.py`、`research_monthly_a_return_search.py`、`research_monthly_a_sharpe_search.py`：收益与Sharpe前沿；
- `research_monthly_a_signal_blend.py`、`research_monthly_a_signal_refine.py`：信号融合与精炼；
- `monthly_a_structure_engine.py`、`research_monthly_a_structure.py`：结构候选。

历史平台版本：

- `platform_baseline2.py`：八成反转冻结版；
- `platform_l04.py`：L04版本；
- `platform_monthly_a.py`：Monthly-A版本；
- `platform_monthly_next_session.py`：次交易日月度执行版；
- `platform_pending1.py`：待定候选1；
- `platform_start_anchored.py`：起点锚定版；
- `platform_small_account_100k.py`：10万元版本。

上述全部是历史研究代码，不是现行“沪深1 R08”，也不是重新授权的D11测试2。大型结果、平台导出、诊断脚本、构建器和缓存均未恢复。
