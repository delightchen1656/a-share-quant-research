# 项目指令与记忆入口

instruction_boundary_version: public-pre2025-v1

## 上下文隔离

- 本文件会自动注入新代理，因此只保存通用指令，不存储后验业绩、亏损股票或据后验形成的研究建议。
- 完整原项目记忆逐字节保存在 `project_memory/holdout_restricted/history_before_split_20261015.md`；哈希与迁移记录见同目录 `memory_split.json`。历史没有删除，版本变更、旧路径、业绩和审计边界仍以原件及后续受限记录为准。
- 根代理、后验审计代理和生产维护任务按需读取受限记忆；隔离开发代理禁止读取 `project_memory/holdout_restricted/`、任何holdout目录、含后验的全局汇总、其他线程或未经白名单批准的行情/结果。
- 新隔离开发代理开始工作前，确认首始上下文包含本文件的boundary_version且没有后验数字。若自动注入旧记忆，即使未主动读文件也算接触，必须停止开发并报告；不能声称忽略即实现隔离。
- 新后验结果只写受限记忆与相应审计目录，不再写入本文件。fork_turns=none不能替代自动注入检查。共享文件系统是逻辑隔离，不是操作系统安全边界。

## 当前研究授权与要求

- 2026-10-20用户已停止并删除“沪深筛选1”方向；不得从历史记录恢复其模型、规则、研究、回测、跟踪或自动任务，除非用户之后明确重新授权。

## 生产与日常维护

- 日常先读策略README、CURRENT_SELECTION及tracking/README、tracker.json。跟踪是独立模拟，不是用户真实持仓或订单。信号适用日原件只新增不回改；输入完整核验公司行动及sha256，历史成交变化停下核查。表格沿用tracking/replay.py、build_tracker.mjs及Spreadsheets技能。

## 行情与保护资产

- 行情入口 `tools/daily_market_update.py`：先检查当日data_updates审计、metadata refresh及更新进程；成功提交则复用，更新中不读混合数据，不并发启动第二个更新。
- 沿用事务式暂存、备份、校验后提交，不绕过完整性检查。非交易日或供应商未发布不能把旧名单称今日预测；严格交易日历，不凭工作日猜测。
- 预测核验build_manifest哈希，只用截止日信息，不自动重训。停牌缺行核实真实状态并单独留档，不按未来退市信息删池或填造停牌。
- `sh_sz_market_research/data_pipeline/data/`、`evening_accumulation/data/`、`data_updates/`及备份/审计为核心资产，不是缓存；Git忽略不代表可删除或已备份。
- 正式模型、训练源码、旧研究、冻结快照、公司行动、迁移清单、失败结果、history及research_versions均保留。常规清理仅限明确可重建字节码，不删除实质资产。
- 沪深1与科创1统一入口和迁移边界见各自README、provenance及archive记录，不把归档修复或收益当当前生产版本。

## 工程约束

- Python默认 `quant_env/Scripts/python.exe -B`。价格成交单位、税费、股份调整、应收支付和红股上市日期须区分，不用未经核查的空公司行动表假装完整。
- 收益训练标签跨送转须调整股数，不能用送转后每股退出价/原买价直接当经济收益。训练分类目标和账户执行目标可能不同，须明确记录。
- 用户当前授权研究可以继续；读取仓库不代表恢复其他历史暂停任务或实盘交易。无关用户变更不得回退。
