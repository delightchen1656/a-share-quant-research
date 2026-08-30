# 工程结构说明

更新时间：2026-08-25。

## 根目录原则

根目录只保留三个标准文件：`README.md`、`requirements.txt`、`.gitignore`，以及一级功能目录。单次回测、平台导出、分析报告、快捷脚本不得直接散落在根目录。

## 当前目录

```text
quant/
├── README.md                     # 总入口
├── requirements.txt             # 根环境依赖
├── .gitignore                    # 大文件和缓存规则
├── archive/                      # 冻结记录与审计档案
│   ├── baseline_registry/        # 五基准名称、结果总表及本地对比
│   └── platform_audits/
│       └── baseline_1-2_2-2_joint_audit/
│           ├── raw_exports/      # 6个SuperMind原始导出及校验值
│           ├── outputs/          # 机器可读审计结果
│           ├── REPORT.md         # 联合审计报告
│           └── 基准1-2与2-2平台交易联合审计.xlsx
├── evening_accumulation/         # 研究线1：暴涨前建仓识别
├── star_industry_rotation/       # 研究线2：行业温度门控
├── supermind_baselines/          # 五个正式平台单文件交付版
├── tools/                        # 环境检查和下载快捷入口
├── notebooks/                    # CSI100研究Notebook
├── data/                         # 本地数据
└── quant_env/                    # 本地虚拟环境
```

## 正式基准

| 编号 | 名称 | 研究归档 |
|---|---|---|
| 基准1-1 | 暴涨建仓 | `evening_accumulation/baselines/baseline_1/` |
| 基准1-2 | 止损过滤 | `evening_accumulation/baselines/baseline_2/` |
| 基准1-3 | 熊市分散 | `evening_accumulation/baselines/baseline_3/` |
| 基准2-1 | 温度进攻 | `star_industry_rotation/baselines/strategy_4_temperature_attack/` |
| 基准2-2 | 升温防守 | `star_industry_rotation/baselines/strategy_5_rising_defense/` |

## 常用入口

- 环境验证：`python .\tools\main.py`
- 继续下载：双击 `tools/继续下载.cmd`
- 基准总表：`archive/baseline_registry/STRATEGY_BASELINES.md`
- 平台代码：`supermind_baselines/`
- 基准1-2与2-2联合审计：`archive/platform_audits/baseline_1-2_2-2_joint_audit/`

## 维护边界

1. 研究过程进入对应项目目录。
2. 正式基准必须进入项目下的 `baselines/` 冻结目录。
3. 平台原始导出及独立审计进入 `archive/platform_audits/`。
4. 可再生成数据放在 `outputs/`，原始证据放在 `raw_exports/` 并保存校验值。
5. 根目录不得新增单次报告、CSV、日志、临时脚本或平台导出文件。
