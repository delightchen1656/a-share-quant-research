# 沪深主板量化研究工程

本目录是沪市、深市普通主板研究的唯一入口，与科创板研究线隔离。2026-09-26 起，R08 高仓精选被指定为当前“沪深基准1”，其余沪深策略统一作为历史研究保存。

## 目录

```text
sh_sz_market_research/
├── data_pipeline/                  # 下载、质量检查、股票池、标签和模型管线
├── studies/                        # 研究源码、报告与小型汇总
├── platform/supermind/             # 当前R08正式入口、测试与旧平台代码
└── references/README.md            # 外部参考链接，不复制第三方仓库
```

## 数据口径

- 市场：沪市 `600/601/603/605`、深市 `000/001/002/003` 普通主板 A 股。
- 时间：数据管线从 2018-01-01 开始，配置日自动回退到最近交易日。
- 原始价用于成交、资金结算和涨跌停判断；前复权价用于信号与特征。
- 历史股票池包含区间内上市、退市股票，降低当前成分股造成的幸存者偏差。
- 本地行情保存在 `data_pipeline/data/raw` 与 `qfq`，不进入 GitHub。

## 当前状态

- **正式平台基准：**`platform/supermind/supermind_mainboard_baseline_1.py`，R08 高仓精选；分钟频率、10万元、最多12只、目标仓位95%。本地冻结参考为年化18.82%、Sharpe 0.908、最大回撤21.85%。
- **研究结论：**R08 未达到原定 Sharpe 大于1及完整跨起点稳健性门槛；晋升是版本管理决策，不改写研究失败记录。完整过程归档在 `../archive/optimization_studies/hs_fresh_R08_20260925/`。
- **历史版本：**原四份沪深 SuperMind 文件位于 `platform/supermind/legacy/`；原沪深基准2研究位于 `../archive/legacy_mainboard_research/`。
- **旧基准研究：**原状态切换红利反转基准及平台校准记录已整体迁入 `../archive/legacy_mainboard_research/mainboard_baseline_1_pre_R08_20260926/`。
- **既有研究：**`studies/return_first_research/` 保留早期收益优先研究的源码与结论，不再作为正式基准入口。
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
