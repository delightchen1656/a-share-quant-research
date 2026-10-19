# 沪深1

唯一平台入口：[supermind_hushen_1.py](supermind_hushen_1.py)。来源为D7f提速版；2026-10-09仅新增费用异常诊断，原交易逻辑保留，内部D11/版本号用于溯源，不代表另有当前策略。

- SuperMind：完整复制该文件，设置每日频率、10万元、独立空仓账户。
- 核心：四因子权重-0.35/-0.20/+0.25/-0.20；波动60日、隔夜/日内20日、5日平滑至少3日；5只、98%、20交易日调仓、缓冲1.5。
- 提速：只在调仓日更新全市场，其余日期更新持仓与未完成目标。不是周/月初调仓，不是机器学习模型。
- 兼容边界：继承D7c回调，不包含D7额外的回报去重/穿限价停单；现已有安全费用告警。平台耗时与实际成交仍待服务器验证。

## 目录

| 路径 | 用途 |
|---|---|
| research/ | 思路、时间协议、因子重算与迁移来源 |
| backtest/run.py | 唯一本地回测入口 |
| backtest/engine.py、ledger.py、actions.py | 日线撮合、账户账本、公司行动 |
| backtest/data/ | 必要的基准日历、公司行动响应；不是完整股票行情副本 |
| backtest/tests/ | 平台回调对照验证 |
| results/report.html、summary.csv | 当前入口本地回放结果 |
| results/latest/ | 输入指纹、冻结排名、运行明细与校验 |

## 本地运行

在仓库根目录执行：
```
.\quant_env\Scripts\python.exe strategies/hushen/backtest/run.py
.\quant_env\Scripts\python.exe strategies/hushen/backtest/tests/verify_callbacks.py --real
```

run.py固定复跑2020—2026年每年1月/7月起点，10万元，结束2026-09-30。使用冻结因子排名与日线账本；修改策略后会拒绝直接沿用旧缓存，须重建和验证。盘前取数逻辑另由回调测试覆盖。收益含已实现费用，未强制末日平仓，非平台实测。

原始行情仍在 sh_sz_market_research/data_pipeline/data/，未移动、未删除。旧沪深目录整体位于 archive/hushen/20261008_before_unification/；旧研究方向位于 archive/hushen/research_versions/。仅归档，未删除历史文件。日常回测不依赖归档；回归测试读取归档原版作为对照。

训练与验证边界：本次零调参；2025后曾被观察，不声称真正未见盲测。具体负面证据见research/思路与历史.md。

2026-10-09平台资料审计：[逐笔及逐日核查](results/platform_20261009/report.html)。43笔卖出税率差异仍需平台处理；当前代码只告警，不修改现金。原始三文件在该目录inputs/。

本地独立模拟入口：[tracking/README.md](tracking/README.md)，2026-10-17起账、每天北京时间18:30维护。
