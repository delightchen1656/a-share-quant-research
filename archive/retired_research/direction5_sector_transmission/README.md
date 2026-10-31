# 方向5：板块强弱传导

这是根目录新建的独立研究。采用纯数据、因子筛选和机器学习路线，研究行业走强后，行业内哪些股票可能继续领涨或出现补涨。当前阶段仅建立数据底座，不汇报未经验证的策略收益。

用户追加的行业间H3统计遍历已单独完成，见 `SECTOR_LEADLAG_SCAN_V1.md`：81个规范行业、6,480个有方向组合、4种滞后共25,920项清单，其中16,900项可估；多重校正和跨年验证后没有通过标准的稳定正向行业对。该统计扫描使用报价强弱指标，经济收益标签、账户回测和原研究验收门槛保持关闭。

## 文件与数据边界

- 研究代码、配置、审计、输入快照、因子、模型和结果：全部在本目录。
- 唯一已有研究数据来源：`../sh_sz_market_research/data_pipeline/data/raw/` 原始K线，只读。
- 用户追加授权的行业数据位置：`../sh_sz_market_research/data_pipeline/data/classifications/direction5/`，新建，保留来源、原始返回与校验记录。
- 不读取现有策略、旧研究、模型、结果、其他线程、生产登记或现有行业metadata；不复用其结论。
- 使用项目默认Python环境作为运行依赖，不复制其他策略代码。
- 研发截止2024年底；原始源数据经日期过滤、校验后才生成 `inputs_pre2025/` 白名单。模型不得直接读取持续更新的行情目录。

## 研究问题草案

在交易日收盘信息可得后，行业自身强度、上涨广度、领涨集中度、个股相对行业的强弱与滞后程度，是否能够预测下一可执行买点之后的收益排序及风险？

领涨延续与落后补涨可能方向相反，两者先分别登记为子假设，不预设补涨必然有效。行业统计需要排除目标股票自身贡献，避免把个股自己的走势误当成板块传导。行业传导是否提供增量，应与只有个股量价的基准比较。

## 初版研究配置

第2—5步已登记在 `RESEARCH_SPEC_V1.md` 与 `research_protocol_v1.json`：沪深主板、五个交易间隔的经济收益排序，收盘评分、次日开盘尝试买入；2018—2020起始训练，2021—2023逐年开发验证，2024最终保留验收。初始账户100万元、10个等权仓位、五日调仓。这些是本轮默认研究设置，不是已验证的最优参数。

历史费用、执行细节、因子窗口和模型实验预算仍需在对应步骤登记，不能在缺省状态下开始收益选优。协议与输入清单在 `audits/protocol_v1_registration.json` 留存哈希，修改采用新版本。

行业采用真实行业归属。来源由本任务查找，优先检查历史可得性。供应商接受历史日期参数并不自动证明返回的是当时归属，必须核对返回日期与分类版本。官方季度/半年度文件以实际发布日期确定最早可用日期，不能以报告期末作为提前可用日期。

## 已完成的数据准备

- K线白名单：2018-01-02至2024-12-31，3,336只股票，5,154,043行；逐文件哈希、截止日、代码、重复日期及基础OHLC检查已通过。源文件在截取期间没有变化。
- 实际K线前缀仅覆盖沪深主板；没有把这批数据称为完整沪深全市场，也没有静默纳入创业板或科创板。
- 行业来源：证监会18份季度公报与上市公司协会3份半年度公报，共21份官方文件。每份PDF完整提取股票代码集合与原文核对一致；已检查首页合集，并对不同版式和跨页合并单元格作视觉抽查及12条逐行核对。
- 归属白名单：82,823条沪深A股历史公报归属记录，附原文行业名称、行业代码、公布日期、来源页码及哈希。行业聚合使用行业代码；旧PDF分页处的截断、重复或空名称仅在展示名层面按同一文件补齐，原文提取保留在 `industry_name_raw`。
- 时间语义是“当时已公开的最新行业分类”，不是未经证实的精确行业变更生效日。最早使用日严格晚于公布日；新公报未列出的股票不沿用更旧公报中的归属。
- 28个季度末的分类覆盖检查已完成，对当日有交易记录的现有K线股票覆盖约95.24%—99.59%；这是输入覆盖率，不是模型命中率或收益指标。
- 历史分类缺失、旧公报沿用时长、主板缺失K线与其他板块缺失K线分别留档。2023年公报实际在2024年公布，未回填至其报告期。

## 当前数据限制

原始K线可提供量价、换手率与日度交易状态，单位已经按官方字段和全量数值检查核对；历史股票池完整性与公司行动齐全性仍不能据此证明。`qfq` 不作为默认输入，防止使用未核查的全历史复权序列。缺失公司行动时不得伪造完整收益标签或账户回测。

行业历史白名单已完成，但没有把公司行动、完整历史股票池和经济收益标签视为已审计。行业旧版本沿用与分类体系变化的研究政策已登记，具体因子窗口预热将在对应步骤落实。模型实验入口保持关闭，避免跳过前置步骤。

## 顺序与状态

1. 已确认：方向5、行业板块、独立目录、纯数据和外部读取范围。
2. 已完成：官方行业历史来源收集、K线和行业白名单快照、基础质量与信息时点检查。
3. 已登记：目标、主板范围、信号/成交时点、时间划分及行业历史口径。单位与行情涨跌幅公式已核对；全量分红送转接口采集、两源对账、配股采集、交易日历及已知代码例外修正已完成本轮核验，仍需解决事件缺口、完整历史股票池与经济标签。
4. 上述事项完成后：因子定义与时点检查、训练窗内因子筛选、简单基准、机器学习、时间滚动验证、账户回测、稳健性检查、候选冻结。
5. 边界后的单向审计必须按项目隔离规则另行执行，不把结果带回本开发目录。

## 运行

从仓库根目录运行：

```powershell
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\prepare_data.py snapshot
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\prepare_data.py verify
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\prepare_data.py probe-industry
```

`snapshot` 不覆盖已有快照，过滤后才计算质量统计；源目录发生变化则拒绝提交。`probe-industry` 是备用供应商可得性探测，出现超时的结果保留为失败记录，没有纳入训练白名单。正式行业源使用官方公报。

行业准备入口：

```powershell
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\collect_industry.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_industry.py render
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_industry.py promote
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_industry.py coverage
```

`promote` 需要本目录中已通过的人工视觉抽查记录，且不覆盖已有白名单；`coverage` 可从已冻结的输入重新核验覆盖和发布日期边界。`collect_industry.py` 读取供应商静态网页数据时只作文本解析，不执行下载的JavaScript。

PDF依赖安装在本目录 `_vendor/`；运行环境版本与依赖分别保存在 `runtime_versions.json`、`requirements.txt` 和 `requirements-pdf.txt`。未修改共享Python环境。

完整28步顺序和当前状态见 `RESEARCH_PLAN.md`。当前数据审计汇总见 `audits/data_readiness.json`。

当前进度见 `LABEL_DEFINITION_AND_AVAILABILITY_V1.md`：第10步标签定义已登记，第11步调度与覆盖审计已做。原3,737,172条资格记录中3,646,742条通过首轮基础数据检查，尚非批准训练的标签，收益值没有生成。下一项是最小成交与单笔记账核验，通过后检查实际标签分布，再进入因子。阶段门槛为 `research_stage_gates_v2.json`。原资格初筛报告与公司行动审计保留，未知事件15处及812处通用公式差异仍在审计清单，模型与账户回测继续关闭。

初版采集与核对入口（已登记来源和台账需保留；后续新增来源使用新版本目录）：

```powershell
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\collect_action_bulk.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\collect_action_detail.py --workers 4
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\reconcile_actions.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\reconcile_reference_windows.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\finalize_action_collection.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_industry.py coverage
```

`finalize_action_collection.py` 核验原协议哈希、已确认特殊分配、重复记录、日历及身份边界，登记本轮补充版本；已有登记与重跑结果不一致时拒绝覆盖，需保留原版并建立新修订。它不会批准公司行动用于标签。

第二版修正与当前审计入口：

```powershell
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\build_action_revision_v2.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_reference_revision_v2.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\finalize_action_revision_v3.py
& .\quant_env\Scripts\python.exe -B .\direction5_sector_transmission\src\audit_industry.py coverage
```

本轮登记绑定884个文件，原先38个已登记文件核验不变。补证脚本保留分页与来源失败，未把空返回或未下载的PDF当作完整证据。代码变更证据仅用于回溯核对事件，未修改历史可用的行业归属。

开发期资格面板入口为 `src/build_observed_eligibility_v1.py`，输出在 `inputs_pre2025/eligibility_observed_dev_v1/`；已有快照拒绝覆盖。`src/register_pool_milestone_v1.py` 验证并登记本轮24个文件与当前审计配置。面板只标记已观察记录的开仓资格规则，不使用未来公司行动知识筛股；流动性/容量和最终执行资格尚未补齐。2024保留测试未纳入该面板。

标签定义及调度审计入口为 `src/register_label_definition_v1.py`、`src/audit_label_schedule_v1.py` 和 `src/register_label_availability_milestone_v1.py`，对应 `inputs_pre2025/label_schedule_dev_v1/`。只生成计划日期与数据诊断，不计算收益。原资格池不受未来缺失原因影响；2024仅可出现在尾部未成熟计划的日历日期中，不读取其价格来补标签。每次训练按完整信息实际可得日期清除未成熟标签，不能把名义退出日当作实际信息已经齐备。

用户追加的长期区间震荡研究独立保存在 `range_oscillation_v1/`。入口为该目录的 `REPORT.txt`、`spec.json` 和 `registration.json`；代码为 `run_scan.py`、`validate_and_report.py`。这是截至2023年底的单股价格形态扫描，与原行业传导假设和经济收益标签流程分开；2024行情未用于计算，原全局门槛不变。所有该分支数据和结果均留在分支内，不覆盖之前的登记成果。


