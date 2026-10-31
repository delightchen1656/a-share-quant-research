# 沪深1

平台入口：[supermind_hushen_1.py](supermind_hushen_1.py)。来源为D7f提速版；2026-10-09仅新增费用异常诊断，原交易逻辑保留，内部D11/版本号用于溯源，不代表另有当前策略。

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
| results/report.html、summary.csv | 历史固定半年度回放结果（旧执行口径） |
| results/latest/ | 输入指纹、冻结排名、运行明细与校验 |

## 本地运行

指定区间重跑使用 `quant_env/Scripts/python.exe -B 沪深1研究/backtest/run_range.py --start YYYY-MM-DD --cash 100000`，终点默认取最新成功提交的行情审计。
当前本地基线读取 `backtest/execution_baseline.json`（`open_003_guaranteed`）：调仓日买入按真实未复权开盘价×1.003、卖出×0.997，价格四舍五入到分，按资金和整手确定后的可交易目标数量足额成交；卖出净款当日可用。佣金万三最低5元，卖出印花税固定0.1%，不单列过户费；公司行动、到账时间、T+1及股息税FIFO规则保留。保证成交是本地理想化假设：绕过成交量/订单股数上限、涨跌停撮合和日内价格范围，不代表平台或国金保证成交；缺失/无效开盘价不能造价撮合。
四因子、目标5只、98%仓位、20交易日相位、缓冲1.5、资金不足整手减量保留。成交量限制仅在当前保证成交口径中停用，历史执行场景继续保留原限制。实际手工账本只录入真实成交价，不叠加假设滑点、不填造成交。平台策略入口原交易代码及其来源哈希保留，保证成交规则只在本地适配器中实现。
新结果写入 `results/holdout_restricted/range_..._unified_cash_cost/`；需要显式复核旧口径时可传 `--cost-policy strict_daily_limits`。

在仓库根目录执行：
```
.\quant_env\Scripts\python.exe 沪深1研究/backtest/run.py
.\quant_env\Scripts\python.exe 沪深1研究/backtest/tests/verify_callbacks.py --real
```

run.py转发到run_range.py：默认2020-01-01、10万元、最新已提交行情，使用当前open_003_guaranteed口径；可指定--start、--end、--cash。历史strict_daily_limits及unified_cash_cost场景仍可显式传--cost-policy复核，旧结果保留。新口径的结果写入含场景名的新目录。旧固定半年度入口源文件及本次变更前的引擎/账本保存在results/holdout_restricted/baseline_open003_change_20261029/。

原始行情仍在 K线数据/沪深/，未移动、未删除。旧沪深目录整体位于 archive/hushen/20261008_before_unification/；旧研究方向位于 archive/hushen/research_versions/。仅归档，未删除历史文件。日常回测不依赖归档；回归测试读取归档原版作为对照。

训练与验证边界：本次零调参；2025后曾被观察，不声称真正未见盲测。具体负面证据见research/思路与历史.md。

2026-10-09平台资料审计：[逐笔及逐日核查](results/platform_20261009/report.html)。43笔卖出税率差异仍需平台处理；当前代码只告警，不修改现金。原始三文件在该目录inputs/。

沪深1本地前向模拟账户及18:30自动任务已于2026-10-25按用户要求取消；延迟行情造成的历史模拟状态不作为生产结论。当前只维护平台入口、本地回测与研究记忆。
