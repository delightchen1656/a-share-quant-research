# A股量化研究仓库

本仓库当前只登记三条策略基线：**沪深1、沪深2、科创1**。它是个人量化研究、回测和人工跟踪工程，不代表稳定盈利，也不授权自动实盘交易。

## 当前入口

| 名称 | 入口 | 当前口径 | 本地运行 |
|---|---|---|---|
| 沪深1 | `strategies/hushen/supermind_hushen_1.py` | 5只、98%仓位、20交易日调仓 | `strategies/hushen/backtest/run.py` |
| 沪深2 | `strategies/hushen_2/CURRENT_SELECTION.json` | C04_NEW原前三后仅保留ATR≥2.5%，不递补、不重排 | 根目录 `沪深2_星轨软件/` |
| 科创1 | `strategies/kechuang/supermind_kechuang_1.py` | 当前冻结科创基准1 | `strategies/kechuang/backtest/run.py` |

沪深2的生产血缘是“原版 → ATR-only → P12 → 回退到ATR-only”。因此它确实从P12阶段回退而来，但当前不执行P12的规模代理和60日波动门槛。

## 目录结构

```text
quant/
├── strategies/
│   ├── hushen/                  # 沪深1基线、回测和研究记忆
│   ├── hushen_2/                # 沪深2登记、冻结模型、最小运行/复算
│   └── kechuang/                # 科创1基线、训练源码、回测和结果
├── 沪深2_星轨软件/               # 独立软件：代码/模型/账本自包含
├── 沪深2_K线练习/                # 独立练习：代码/引擎/冻结输入自包含
├── sh_sz_market_research/data_pipeline/data/ # 沪深公共日线，保护资产
├── evening_accumulation/data/   # 科创行情，保护资产
├── data_updates/                # 行情更新备份与审计，保护资产
├── archive/                     # 标志性历史源码与迁移审计，不是当前入口
├── project_memory/              # 公共与受限项目记忆
├── research_versions/           # 其他历史研究源码索引
├── 国金ptrade/                  # 独立研究线
├── 量化审查/                    # 审查记录
├── tools/                       # 行情更新和仓库自检
└── AGENTS.md                    # 项目边界与维护规则
```

根目录两个沪深2应用均可读取公共K线，但各自拥有运行代码和模型/冻结输入。星轨软件的 `tracker/data/` 是本机账户历史，K线练习的 `frozen_inputs/` 是本机冻结题库；二者体积大且含本地状态，使用清单和哈希校验，不进入普通Git提交。

## 研究与数据边界

- 三条基线的当前运行不能依赖 `archive/` 导入代码。
- 训练源码、冻结模型、标志性版本、历史思路和来源清单保留；过渡脚本、缓存和可重建批次明细可以清理。
- `sh_sz_market_research/data_pipeline/data/`、`evening_accumulation/data/`、`data_updates/` 及其备份/审计是核心资产，Git忽略不等于可以删除。
- 沪深1和沪深2都存在公司行动与日线撮合边界；本地结果不是平台或券商逐笔实测。
- 后验研究只写受限目录，不能回流成伪盲测结论。

## 验证

```powershell
& .\quant_env\Scripts\python.exe -B .\tools\main.py
& .\quant_env\Scripts\python.exe -B .\strategies\hushen\backtest\tests\verify_callbacks.py --real
& .\quant_env\Scripts\python.exe -B .\沪深2_星轨软件\verify_package.py
& .\quant_env\Scripts\python.exe -B .\沪深2_K线练习\verify_package.py
```

`tools/main.py --full-archive` 会额外逐文件核对科创历史归档，耗时明显更长。
