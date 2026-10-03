# 科创事件识别与风险控制版本

本方向记录科创1-1到1-3及早期平台风控演进。当前正式科创1-2仍在 `strategies/kechuang/supermind_baseline_1_2_stop_filter.py`，训练源码在 `strategies/kechuang/training_source/`。

| 代码 | 对应策略或思路 |
|---|---|
| `train_event_model_v1.py` | 第一代异常上涨事件识别训练；作为现行V2训练器之前的标志版本 |
| `platform_event_standard.py` | 最早的标准事件策略平台实现 |
| `platform_baseline30_strict.py` | 30%事件目标的严格交易约束版 |
| `platform_live_constraints_v2.py` | 增加实盘股票池、成交与持仓限制 |
| `platform_live_realistic_v3.py` | 强化费用、整手和可成交性近似 |
| `platform_risk_control_v4.py` | 加入组合风险覆盖 |
| `platform_risk_control_v5_confirmed.py` | 风控确认版，保留作为平台演进节点 |
| `platform_star_r09.py` | 科创R09研究平台版本 |
| `baseline_1_1_accumulation_rally.py` | 科创1-1：暴涨前建仓，事件模型原始基准 |
| `baseline_1_3_bear_diversification.py` | 科创1-3：在1-2上加入季度熊市软缩仓和下行相关性分散 |

最终研究结论是：先止损概率过滤改善了收益与回撤，形成科创1-2；1-3进一步压低回撤，但收益前沿不如当前主线组合。归档文件内嵌历史模型或旧路径，只用于复核版本差异。
