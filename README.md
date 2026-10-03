# A股量化研究仓库

本仓库当前只设四条正式主线：**科创1-2、科创2-2、科创3-1、沪深1**。科创3-2、沪深D11测试2和沪深1截止2024-11-30重估均为独立候选或验证版本，不自动增加正式基准，也不覆盖冻结入口。

## 当前入口

| 名称 | 状态 | 文件 |
|---|---|---|
| 科创1-2 | 正式、冻结 | `strategies/kechuang/supermind_baseline_1_2_stop_filter.py` |
| 科创2-2 | 正式 | `strategies/kechuang/supermind_baseline_2_2_rising_defense.py` |
| 科创3-1 | 正式、冻结 | `strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry.py` |
| 沪深1 | 正式、冻结对照 | `strategies/hushen/supermind_mainboard_baseline_1.py` |
| 科创3-2 | 审计修订候选 | `strategies/kechuang/supermind_baseline_3_2_audited_daily.py` |
| 沪深1截止日重估 | 仅使用2024-11-30前数据重估 | `strategies/hushen/supermind_mainboard_baseline_1_cutoff_20241130.py` |
| 沪深D11测试2 | 提速候选 | `strategies/hushen/supermind_test2_D11_fast_daily.py` |
| 沪深D11截止日版 | 测试2的2024-11-30截止重估 | `strategies/hushen/supermind_test2_D11_fast_cutoff_20241130.py` |

科创3-1另保留标准日频版。沪深1为分钟频率、调仓日09:31执行、10万元口径；科创与沪深平台设置不能混用。

## 目录结构

```text
quant/
├── strategies/                 # 当前正式策略、候选、训练源码与当前研究史
│   ├── kechuang/
│   └── hushen/
├── research_versions/          # 从Git恢复的标志性版本和研究版本源码
│   └── <研究方向>/README.md    # 每个方向仅一份研究说明
├── evening_accumulation/data/  # 科创原始价/前复权行情，保护资产
├── sh_sz_market_research/
│   └── data_pipeline/data/     # 沪深原始价/前复权行情，保护资产
├── data_updates/               # 行情更新前备份、供应商修正前原件和审计
├── 国金ptrade/                  # 未来独立研究线
├── 量化审查/                    # 审查决定与记忆
├── tools/                      # 完整性检查和行情恢复/更新说明
├── AGENTS.md                   # 项目边界与保护规则
└── README.md
```

## 保存原则

- 当前可运行入口、模型训练源码、模型实物和受保护行情完整保留。
- 历史中能代表策略版本、冻结候选或明确研究假设的代码保存在 `research_versions/`。
- 每个研究方向只用一份Markdown概括代码、策略、研究思路、结论和限制。
- 中间构建器、下载器、审计器、临时分析器、缓存、日志和大批量回测输出不进入版本归档。
- 历史代码可能依赖旧路径或已删除数据，仅用于追溯；不能把它当作当前入口。

恢复代码的索引见 `research_versions/README.md`。当前基准研究史从 `strategies/kechuang/HISTORY.md` 和 `strategies/hushen/HISTORY.md` 进入。

## 核心资产与边界

- 科创预测模型训练：`strategies/kechuang/training_source/`。主上涨模型、先止损模型、季度熊市模型和科创2-2温度门控不得在常规清理中删除。
- 科创2-2季度熊市模型有效期截至2026-09-30；进入第四季度必须先更新或核对。
- 沪深1截止日重估的观测截止2024-11-29、标签最晚2024-11-05；尚无新版平台收益。
- 行情已更新至2026-09-30。备份和行情均不是普通缓存，即使被Git忽略也不得删除。
- 本地回测、SuperMind平台回测和实际账户持仓必须分开表述；历史结果不构成收益承诺。

## 检查

```powershell
.\quant_env\Scripts\python.exe .\tools\main.py
.\quant_env\Scripts\python.exe -m unittest .\strategies\hushen\test_mainboard_baseline_1.py -v
.\quant_env\Scripts\python.exe -m unittest .\strategies\kechuang\baseline_3_2\test_revision.py -v
```
