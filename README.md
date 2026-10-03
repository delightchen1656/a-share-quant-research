# A股量化策略核心仓库

2026-10-03新增用户授权的独立修订版：**科创3-2（强势延持审计修正版）**，平台入口 `strategies/kechuang/supermind_baseline_3_2_audited_daily.py`，说明与测试位于 `strategies/kechuang/baseline_3_2/`。当前四条正式主线保持，3-2作为待平台验证修订版单独维护。

本仓库经过2026-10-03核心整理，只维护四条正式主线：**科创1-2、科创2-2、科创3-1、沪深1**。科创3-2是待平台验证的审计修订候选，不属于第五条正式主线。预测模型训练源码继续保留；历史尝试主要由每个基准自己的Markdown记录，不再保留大批阶段脚本和输出。

## 目录

```text
quant/
├── strategies/
│   ├── kechuang/       # 科创三基准、3-2候选、训练源码和逐基准历史
│   └── hushen/         # 沪深1、平台测试和历史记录
├── 国金ptrade/          # 独立保留，供以后单独研究
├── 量化审查/            # 审查记忆与决定；不作为策略入口
├── tools/              # 核心文件完整性检查
├── quant_env/          # 当前本地Python环境，暂不调整
├── AGENTS.md           # 当前主线和操作边界
├── requirements.txt
└── README.md
```

## 正式入口

| 当前名称 | 文件 |
|---|---|
| 科创1-2 | `strategies/kechuang/supermind_baseline_1_2_stop_filter.py` |
| 科创2-2 | `strategies/kechuang/supermind_baseline_2_2_rising_defense.py` |
| 科创3-1 | `strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry.py` |
| 沪深1 | `strategies/hushen/supermind_mainboard_baseline_1.py` |

科创3-1另保留标准日频版。各基准的研究路线从 `strategies/kechuang/HISTORY.md` 和 `strategies/hushen/HISTORY.md` 进入。

## 核心源码

- 科创预测模型训练：`strategies/kechuang/training_source/`
- 每个基准的研究思路与尝试方向：`strategies/kechuang/history/`、`strategies/hushen/HISTORY.md`

科创3-1已经完成并冻结；它复用科创1-2的两套预测模型，相关训练源码和模型实物必须保留。沪深1是因子与规则策略，不存在独立机器学习训练模型，因此不再保留大批旧轮次研究引擎。

## 运行边界

- 科创策略使用日频平台口径；沪深1使用分钟频率并在调仓日09:31执行，两者不能混用。
- 科创2-2内嵌季度熊市模型历史有效期截至2026-09-30，进入2026年第四季度后必须先更新或核对。
- 本地回测、平台回测和实际账户持仓必须分开表述。
- 历史回测结果不代表未来收益，也不构成投资建议。

## 核心检查

```powershell
.\quant_env\Scripts\python.exe .\tools\main.py
.\quant_env\Scripts\python.exe -m unittest .\strategies\hushen\test_mainboard_baseline_1.py -v
```
