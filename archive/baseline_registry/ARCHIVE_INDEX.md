# 仓库归档索引

归档日期：2026-08-25。当前仓库按“根目录入口—研究项目—冻结基准—审计档案—可再生产物”五层管理。

## 公共入口

| 文件 | 用途 |
|---|---|
| `../../README.md` | 环境、数据和运行入口 |
| `../PROJECT_STRUCTURE.md` | 当前工程结构、目录职责和入口路径 |
| `../REORGANIZATION_LOG.md` | 目录调整与名称同步记录 |
| `STRATEGY_BASELINES.md` | 六个正式基准的统一编号和关键结果 |
| `BASELINE_NAME_MAP.json` | 新旧编号、中文名和技术路径的机器可读映射 |
| `BASELINE_LOCAL_COMPARISON.md` | 六个基准统一口径本地回测集合表 |
| `BASELINE_LOCAL_COMPARISON.csv` | 六个基准集合表的机器可读数据 |
| `BASELINE_LOCAL_COMPARISON_DETAILED.md` | 原五个基准三种回测口径的历史集合表；基准3-1待补扩展口径 |
| `../../supermind_baselines/` | 六个基准按规范编号命名的SuperMind平台交付代码 |
| `../platform_audits/baseline_1-2_2-2_joint_audit/` | 基准1-2与2-2平台交易联合审计、组合测试及原始导出归档 |
| `../optimization_studies/baseline_1-2_high_risk20_20260910/` | 基准1-2高风险收益最大化20方向研究 |
| `../optimization_studies/baseline_1-2_structural10_20260910/` | 阈值0.63高进攻候选的10个非调参结构研究 |
| `../optimization_studies/sharpe_frontier_20260911/` | 基准3-1与基准2-2的Sharpe优先组合及风险敞口研究 |
| `../optimization_studies/sharpe_public_structures_20260911/` | 公开思路启发的12个Sharpe优化结构及三段验证 |
| `../optimization_studies/normalized_return_sharpe_20260911/` | 年化收益与Sharpe归一化综合损失及全候选重排 |
| `../../tools/继续下载.cmd` | 行情断点续传入口 |
| `../../.gitignore` | 排除行情、虚拟环境、缓存和大体积临时输出 |

## 研究线1：暴涨前建仓识别

项目目录：`evening_accumulation/`

| 基准 | 技术目录 | 已归档内容 |
|---|---|---|
| 基准1-1 暴涨建仓 | `baselines/baseline_1/` | 冻结策略、本地回测、平台原始记录、关键文件校验 |
| 基准1-2 止损过滤 | `baselines/baseline_2/` | 冻结说明、止损风险模型、研究报告、比较结果 |
| 基准1-3 熊市分散 | `baselines/baseline_3/` | 本地验证、熊市模型、SuperMind单文件、平台静态测试、报告 |
| 基准3-1 强势延持 | `baselines/baseline_3_1_high_attack_adaptive_expiry/` | 冻结平台代码、十方向研究报告与机器可读结果 |

研究过程总记录：`evening_accumulation/OPTIMIZATION_LOG.md`。

`backtest_*.py`、`research_*.py`、`compare_*.py`、`run_*.py` 均保存在 `evening_accumulation/` 项目目录内，是可复现实验入口。根目录不再存放这类脚本。`outputs/` 为可再生成产物，不作为唯一档案。

## 研究线2：行业温度门控

项目目录：`star_industry_rotation/`

| 基准 | 技术目录 | 已归档内容 |
|---|---|---|
| 基准2-1 温度进攻 | `baselines/strategy_4_temperature_attack/` | SuperMind版本、统一口径本地回测、清单 |
| 基准2-2 升温防守 | `baselines/strategy_5_rising_defense/` | SuperMind版本、统一口径本地回测、清单 |

统一对比报告：`star_industry_rotation/baselines/LOCAL_BACKTEST_COMPARISON.md`。完整可再生成输出保存在 `star_industry_rotation/outputs/`。

## 数据与大文件

- `data/`、`evening_accumulation/data/`：本地行情数据，不移动、不重复复制。
- `evening_accumulation/inputs/`：SuperMind导出材料及清单。
- `quant_env/`、`__pycache__/`：运行环境和缓存，不属于研究档案。
- 模型二进制、Base64和平台单文件保存在对应基准目录或 `supermind/`，冻结版本以基准目录为准。
- `../platform_audits/baseline_1-2_2-2_joint_audit/raw_exports/`：基准1-2、2-2的6个SuperMind原始交易/持仓/日志文件；分析产物位于审计目录的 `outputs/`、`REPORT.md` 和工作簿。

## 维护规则

1. 新实验先写入项目研究目录或 `outputs/`，不得直接覆盖冻结基准。
2. 晋升为基准时，复制最终代码、模型、测试结果和说明到独立基准目录。
3. 所有对外讨论使用正式编号：基准1-1、1-2、1-3、2-1、2-2、3-1。
4. 原始平台导出只读保存；分析结果另建文件，避免污染原始证据。
5. 不删除旧技术路径；如需重构路径，先同步修改脚本并重新生成校验清单。
6. 根目录只保留 `README.md`、`requirements.txt`、`.gitignore` 和一级功能目录；新报告必须归入对应项目或 `archive/`。

## 名称同步状态

- README、研究报告、平台说明和校验清单均使用规范编号。
- 基准2-1、2-2的本地 CSV/JSON 记录已改用规范 `variant` 和完整中文名。
- 基准1研究线保留 `baseline1`、`strategy2` 等内部模型键；其展示字段已经同步。
- 文件名中的 `strategy4`、`strategy5` 以及目录 `baseline_1` 等属于兼容路径，不再解释为对外编号。
