# 沪深2基线

唯一生产登记为 [CURRENT_SELECTION.json](CURRENT_SELECTION.json)。当前版本由原冻结 `C04_NEW` 衍生，生产血缘是：原版 → ATR≥2.5% → P12 → 撤销P12并回到ATR-only。现行规则不是P12：先生成原每日前三，再仅保留信号日 `ATR比例 >= 0.025` 的股票，不递补、不重排、不重训模型。

## 当前保留内容

- `CURRENT_SELECTION.json`：唯一登记与哈希。
- `runtime/`：冻结因子构建、排序和ATR-only信号过滤。
- `model/`：`utility.txt`、`pen025.txt`、`pen100.txt` 及等价性证据；当前非零权重模型为utility和pen025。
- `backtest/compute_risk_metrics.py`：从冻结权益曲线复算风险指标的最小入口。
- `results/`：当前登记的四份汇总/权益结果；历史大规模研究结果不属于运行依赖。

执行规则仍为10万元、5槽、7个自然日条件买入、最长持有30个自然日、4ATR止盈、1.5ATR止损、T+1、同日双触止损优先。登记已受2025年后结果影响，不称为新盲测，也不包含券商自动下单授权。

## 独立应用

- 根目录 `沪深2_星轨软件/`：当前晚间工作台，包含自己的代码、模型、登记、测试与本地账本历史。只读访问公共沪深日线和更新审计。
- 根目录 `沪深2_K线练习/`：自包含练习代码、冻结执行引擎与本地冻结题库/行情，不依赖本目录或归档运行。

P12和回退的标志性代码、登记及说明保存在 `沪深2_星轨软件/history/`；更早的登记前研究源码在 `archive/hushen_2/`。它们只用于溯源，不参与当前运行。

## 验证

```powershell
& .\quant_env\Scripts\python.exe -B .\strategies\hushen_2\runtime\verify.py
& .\quant_env\Scripts\python.exe -B .\沪深2_星轨软件\verify_package.py
& .\quant_env\Scripts\python.exe -B .\沪深2_K线练习\verify_package.py
```
