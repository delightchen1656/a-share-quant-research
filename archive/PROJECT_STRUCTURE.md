# 工程结构与维护边界

更新时间：2026-09-15。

## 一级目录

| 目录 | 职责 | Git策略 |
|---|---|---|
| `evening_accumulation/` | 科创板事件识别研究、冻结基准和 SuperMind 转换 | 源码、基准和小型证据入库；数据与普通输出排除 |
| `star_industry_rotation/` | 科创板行业温度研究 | 源码与冻结基准入库；可再生成输出排除 |
| `sh_sz_market_research/` | 沪深主板数据工程、研究实验和平台验证 | 源码、报告、汇总入库；行情、派生数据、模型和曲线排除 |
| `supermind_baselines/` | 对外使用的规范命名平台单文件 | 入库，必须与对应基准记录一致 |
| `archive/` | 稳定结论、迁移研究、优化记录和平台审计 | 入库，只读维护 |
| `notebooks/` | CSI100 探索性研究 | 入库，不存 Notebook 缓存 |
| `tools/` | 环境检查和本地控制台入口 | 入库 |
| `data/` | 根级本地研究数据 | 不入库 |

## 研究目录约定

```text
project/
├── README.md
├── baselines/       # 冻结版本；禁止直接覆盖
├── studies/         # 当前研究源码与结论
├── platform/        # 平台适配和静态测试
├── data_pipeline/   # 可选：下载、清洗、质量审计
└── outputs/         # 可再生成产物，不作为唯一证据
```

研究结论保留 `REPORT.md`、必要的 CSV/JSON 汇总和参数；逐日曲线、全量特征、缓存、临时模型及 partial 文件不归档。外部项目只记录 URL、版本和复现结论，不嵌套提交第三方 Git 仓库。

## 正式入口

- 项目总览：`README.md`
- 正式基准登记：`archive/baseline_registry/STRATEGY_BASELINES.md`
- 科创板平台交付：`supermind_baselines/`
- 沪深研究入口：`sh_sz_market_research/README.md`
- 环境验证：`tools/main.py`
- 下载入口：`tools/继续下载.cmd`、`tools/启动沪深主板下载控制台.cmd`

## 晋升与归档流程

1. 实验先进入对应 `studies/`，输出写入被忽略的工作目录。
2. 达到阶段结论后保留报告、参数、汇总指标和复现入口。
3. 晋升基准时复制必要代码与模型到独立 `baselines/`，生成 MANIFEST 或校验值。
4. 平台原始证据进入 `archive/platform_audits/`，不得改写原件。
5. 已停止任务只归档目标、完成范围、停止原因和结论，删除执行残留。
6. 根目录只保留标准文件和一级功能目录。
