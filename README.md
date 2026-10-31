# 量化研究与看盘工作台

维护沪深1、沪深2、科创1三条生产基线，以及独立研究尝试。软件提供行情展示、信号准备和人工成交记录。研究权限、冻结输入和受限审计以 AGENTS.md 为准。

## 项目结构

```text
quant/
├── K线数据/
│   ├── 沪深/                 # raw、qfq、日历、名录与分类
│   ├── 科创/                 # raw、qfq与元数据
│   ├── 黄金/                 # XAU/USD来源、快照与更新审计
│   ├── 指数/上证看盘/        # 指数和历史阶段标注
│   └── 更新备份与审计/       # 事务提交、备份与校验
├── 沪深1研究/                # 平台策略、因子、回测、研究与结果
├── 沪深2研究/                # 当前登记、冻结模型、执行与历史
│   └── K线练习/              # 独立程序、冻结执行引擎与题库
├── 科创1研究/                # 策略、训练源码、模型与回测
├── 研究尝试/
│   ├── 方向1_超跌反弹/       # 独立于生产沪深1
│   └── gold_trend_stock_trial/
├── K线看盘软件/
├── 沪深实盘工作台/           # 沪深1/2及各自独立账本
├── 国金ptrade/               # 原位保留
├── archive/                  # 历史源码、旧研究和报告
├── project_memory/           # 项目记忆、审查与受限审计
├── tools/                    # 公共更新、路径映射与验证
├── quant_env/
├── 启动沪深看盘.cmd
├── 启动实盘工作台.cmd
├── AGENTS.md
└── requirements.txt
```

公共行情统一存放；冻结白名单、回测快照、练习题库和看盘展示快照保留独立版本。研究中间产物写回所属研究目录，后验仍写入 `holdout_restricted/`。

## 当前基线

| 基线 | 当前口径 | 入口 |
|---|---|---|
| 沪深1 | 原四因子、5只目标、98%仓位、20交易日调仓；本地执行以登记为准 | `沪深1研究/supermind_hushen_1.py`、`backtest/run.py` |
| 沪深2 | 原每日前三后仅保留ATR≥2.5%，不递补、不重排，冻结模型 | `沪深2研究/CURRENT_SELECTION.json` |
| 科创1 | 原冻结动态策略，保留训练源码、模型及账户规则 | `科创1研究/supermind_kechuang_1.py`、`backtest/run.py` |

迁移不调整策略参数、不重训模型。详细交易、费用、撮合假设及历史成绩见各基线README与登记文件。

在仓库根目录执行：

```powershell
# 行情更新入口（运行前先检查已有更新和当日审计）
& .\quant_env\Scripts\python.exe -X utf8 -B .\tools\daily_market_update.py --help

# 三条基线回测入口
& .\quant_env\Scripts\python.exe -X utf8 -B .\沪深1研究\backtest\run.py
& .\quant_env\Scripts\python.exe -X utf8 -B .\tools\replay_hushen2_local.py --frozen-only
& .\quant_env\Scripts\python.exe -X utf8 -B .\科创1研究\backtest\run.py

# 工程与模型完整性验证
& .\quant_env\Scripts\python.exe -X utf8 -B .\tools\main.py
& .\quant_env\Scripts\python.exe -X utf8 -B .\沪深实盘工作台\verify_package.py
& .\quant_env\Scripts\python.exe -X utf8 -B .\沪深2研究\K线练习\verify_package.py
```

沪深2历史账户回放使用练习包内冻结引擎与输入；`沪深2研究/backtest/compute_risk_metrics.py` 仅复算冻结结果指标。

## 软件与保护资产

多对话分工、独立临时目录与环境重建见 `tools/environments/README.md`。通过 `tools/module_runtime.py` 按模块运行可隔离临时文件和绘图缓存；共享稳定环境不随研究升级，各模块可建立自己的 `.venv`。这不改变研究白名单和后验边界。

- 双击 `启动沪深看盘.cmd`，端口8766，展示股票、方向1信号、黄金和上证指数。
- 双击 `启动实盘工作台.cmd`，端口18762。沪深1的 `tracker/hushen1_data/` 和沪深2的 `tracker/data/` 独立保存现金、成交和持仓。
- 练习入口：`沪深2研究/K线练习/启动练习.pyw`，端口18763；题库和作答历史保留。
- 快捷方式、Windows晚间任务和黄金每日自动任务随目录迁移，沿用原时间与行为。工作台不连接券商自动下单。
- 行情读取以当前元数据对应的正式事务提交为准，不按目录名称推断最新版本。
- 行情、更新备份、冻结输入、公司行动证据、模型及账本都是保护资产。Git忽略不等于已备份；只克隆代码不能恢复本机行情与私人账户。

## 历史与迁移

旧路径映射见 `tools/layout_paths.json`，历史记录可通过 `tools/workspace_paths.py` 显式解析。原始白名单和历史证据保留哈希核验，路径迁移不扩大数据访问授权。

`archive/retired_research/` 中的旧研究保持停止；保留源码不代表恢复研究。原 `reports/`、`outputs/`、`research_versions/` 收入 `archive/`。本次文件清单、原始指纹、路径修改备份与验证证据位于 `project_memory/holdout_restricted/layout_20261031/`。
