# 沪深主板量化研究工程

本目录是沪市、深市普通主板研究的唯一入口，与科创板研究线隔离。当前同时维护一个已冻结基准和一条尚未晋升的收益优先研究线。

## 目录

```text
sh_sz_market_research/
├── baselines/mainboard_baseline_1/ # 正式沪深基准及平台校准记录
├── data_pipeline/                  # 下载、质量检查、股票池、标签和模型管线
├── studies/                        # 研究源码、报告与小型汇总
├── platform/supermind/             # SuperMind适配与测试代码
└── references/README.md            # 外部参考链接，不复制第三方仓库
```

## 数据口径

- 市场：沪市 `600/601/603/605`、深市 `000/001/002/003` 普通主板 A 股。
- 时间：数据管线从 2018-01-01 开始，配置日自动回退到最近交易日。
- 原始价用于成交、资金结算和涨跌停判断；前复权价用于信号与特征。
- 历史股票池包含区间内上市、退市股票，降低当前成分股造成的幸存者偏差。
- 本地行情保存在 `data_pipeline/data/raw` 与 `qfq`，不进入 GitHub。

## 当前状态

- **正式基准：**`baselines/mainboard_baseline_1/`，状态切换红利反转；正式指标、平台校准和风险限制以该目录 README 为准。
- **当前研究：**`studies/return_first_research/`，已完成数据审计、简单基线、滚动模型、反转、风险门控和公开策略复现；当前最佳 Sharpe 仍未达到预设目标，因此未晋升正式基准。
- **已停止任务：**旧 100 路线任务只完成 60 条，停止结论已归档到 `../archive/optimization_studies/sharpe_100_routes_stopped_20260914/`，执行残留已删除。

## 常用入口

```powershell
# 本地下载控制台
.\tools\启动沪深主板下载控制台.cmd

# 数据管线（在项目根目录执行）
.\quant_env\Scripts\python.exe .\sh_sz_market_research\data_pipeline\m1_prepare_and_audit.py
```

数据管线完整顺序见 [`data_pipeline/README.md`](data_pipeline/README.md)，收益优先研究计划见 [`studies/return_first_research/PLAN.md`](studies/return_first_research/PLAN.md)。

## 版本控制边界

保留源码、配置、报告、小型指标汇总、正式基准和必要的平台原始记录；排除原始/复权行情、派生面板、模型工作副本、普通输出、逐日 Parquet 曲线、缓存及第三方仓库副本。
