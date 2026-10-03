# 沪深R08多轮研究源码

本方向是现行沪深1的直接研究来源。历史累计完成631个配置、13,352个开发窗口、39个冻结候选全期结果和124个诊断窗口；R08最终参考为年化18.82%、Sharpe 0.908、最大回撤21.85%、平均股票仓位91.91%。它未达到原定Sharpe大于1和跨起点稳健性门槛，后由用户作版本管理决定晋升。

## 代码与研究思路

| 代码 | 对应策略或思路 |
|---|---|
| `core_research_engine.py` | 历史股票池、特征、排名和候选生成的公共研究核心 |
| `core_execution_engine.py` | 现金、整手、费用、T+1和成交限制的公共执行账本 |
| `pre_affordability_engine.py` | 整手可买性约束加入前的对照引擎 |
| `daily_risk_overlay_engine.py` | 允许组合风险状态变化日调整仓位的扩展引擎 |
| `learning_models.py` | 第6轮滚动学习候选的模型定义 |
| `round01_historical_baselines.py` | 防守、反转、回调、趋势、流动性、杠铃等历史基线 |
| `round02_broad_lowvol.py` | 宽股票池与低波资格边界 |
| `round03_calendar_regime.py` | 共同日历和市场状态切换 |
| `round04_adjustment_proxy.py` | 历史价格调整代理，不等同真实分红数据库 |
| `round05_adjustment_weights.py` | 调整代理权重的有限组合 |
| `round06_learning.py` | 严格滚动训练的学习排序 |
| `round07_diversification.py` | 组合分散与相关性结构 |
| `round08_long_momentum.py` | 长期风险调整动量；R08核心来源 |
| `round09_affordability.py` | 10万元账户的整手可买性 |
| `round10_cluster_rotation.py` | 历史收益聚类与簇轮动 |
| `round11_high_exposure_floor.py` | 85%/95%等高仓位下限，形成R08高仓精选 |
| `round12_core_neighborhood.py` | R08核心附近的有限结构邻域 |
| `round13_liquidity_universe.py` | 500万/2000万/5000万元成交额股票池 |
| `round14_style_adaptation.py` | 价格构造的历史风格适应 |
| `round15_historical_dividend.py` | 2019年公开历史持仓构造的分红研究 |
| `round16_financial_quality.py` | 财务质量小样本研究 |
| `round17_broad_quality.py` | 扩展历史主板覆盖后的广义质量研究 |
| `round18_earnings_value.py` | 盈利/流通市值代理与价值回调 |
| `round19_daily_risk.py` | 日度指数风险覆盖 |
| `round20_style_risk.py` | 风格价格指数风险覆盖 |
| `round21_breadth_retention.py` | 增加持仓数量与缓冲宽度 |
| `round22_staggered_accounts.py` | 双/三子账户错峰调仓 |

当前平台入口、2024-11-30截止重估和D11测试2均在 `strategies/hushen/`，不放入本历史目录。原轮次报告、Parquet特征、排名缓存、训练模型和逐日账本没有恢复。
