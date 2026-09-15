# A股量化研究与平台验证工程

这是一个面向 A 股中低频策略研究的个人工程，覆盖数据治理、特征与模型研究、真实交易约束回测、冻结基准管理，以及同花顺 SuperMind 平台验证。历史结果仅用于技术研究，不构成投资建议。

## 项目组成

```text
quant/
├── evening_accumulation/     # 科创板异常拉升前建仓、止损过滤与组合风控
├── star_industry_rotation/   # 科创板行业温度门控研究
├── sh_sz_market_research/    # 沪深主板数据管线、策略研究与平台校准
├── supermind_baselines/      # 规范命名的平台交付版策略
├── archive/                  # 基准登记、研究结论、迁移记录与平台审计
├── notebooks/                # CSI100 多因子与机器学习研究
├── tools/                    # 环境检查和下载控制台入口
├── data/                     # 本地数据，不进入 Git
└── requirements.txt
```

完整职责与维护边界见 [`archive/PROJECT_STRUCTURE.md`](archive/PROJECT_STRUCTURE.md)。

## 研究主线

### 1. 科创板事件识别

使用历史量价、波动、换手、横盘压缩和突破状态识别异常上涨前形态，并逐步增加先止损概率过滤、熊市软缩仓、下行相关性分散和行业温度门控。正式与候选版本统一登记在 [`archive/baseline_registry/STRATEGY_BASELINES.md`](archive/baseline_registry/STRATEGY_BASELINES.md)。

### 2. 沪深主板研究

建立 2018 年以来的原始价/前复权双口径行情管线，覆盖历史股票池、公司行动、停牌、涨跌停、T+1、整数手、费用和成交容量。当前正式基准为“沪深基准1：状态切换红利反转”；新一代收益优先研究仍处于候选验证阶段，详见 [`sh_sz_market_research/README.md`](sh_sz_market_research/README.md)。

### 3. 平台校准与审计

本地回测与 SuperMind 平台结果分别保存，通过成交、持仓、账户净值和原始行情交叉核对。平台原始记录、校验值和联合审计位于 [`archive/platform_audits/`](archive/platform_audits/)。

## 工程口径

- T 日收盘生成信号，T+1 使用原始价格成交；复权价格只用于特征。
- 模拟停牌、涨跌停、A 股 T+1、100/200 股整数手、现金、费用和滑点。
- 训练、开发、验证与锁定观察区间分开报告；不以单一区间反复调参。
- 正式基准冻结保存，新增研究不得覆盖历史基准。
- 原始行情、本地模型、派生面板、缓存和可再生成逐日曲线不进入 Git。

## 快速入口

```powershell
# 环境检查
.\quant_env\Scripts\python.exe .\tools\main.py

# 科创板数据续传
.\tools\继续下载.cmd

# 沪深主板下载控制台
.\tools\启动沪深主板下载控制台.cmd
```

各研究线的具体运行命令以其目录内 README 为准。

## 数据与版本控制

GitHub 只保存源码、配置、文档、正式基准、小型汇总结果和必要的审计证据。以下内容仅保留在本地并可按流程重建：

- `data/` 及各项目行情目录；
- `quant_env/`、`__pycache__/`；
- 派生特征、训练缓存、模型工作副本和普通 `outputs/`；
- 第三方仓库副本。外部参考只记录来源链接。

目录调整记录见 [`archive/REORGANIZATION_LOG.md`](archive/REORGANIZATION_LOG.md)。
