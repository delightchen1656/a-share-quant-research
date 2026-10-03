# 沪深事件预测与趋势模型研究

| 代码 | 对应策略或思路 |
|---|---|
| `train_pool_models.py` | 事件股票池模型训练 |
| `train_trend_models.py` | 趋势延续模型训练 |
| `backtest_pool_ge1.py` | 事件概率达到阈值后的股票池回测 |
| `research_trend_10_rounds.py` | 趋势模型10轮有限优化 |
| `research_alternative_10_routes.py` | 十条替代事件路线 |
| `research_positive_routes.py` | 正收益方向筛选 |
| `research_rebalance_routes.py` | 再平衡与持有结构 |
| `research_public_sharpe_routes.py` | 公开风险调整收益思路 |
| `research_cn_local_sharpe_routes.py` | 中国本地市场Sharpe路线 |

该方向是沪深早期机器学习事件研究，不属于R08。当前沪深1是三因子规则策略，没有沿用这些模型。模型实物、候选缓存和阶段输出不恢复。
