# A股量化研究仓库

当前维护两条入口：**科创基准1**与**沪深1**。这是个人量化研究与回测项目，不是已验证稳定盈利的实盘系统。

## 当前入口

| 名称 | 平台入口 | 本地回测 | 说明 |
|---|---|---|---|
| 科创基准1 | [supermind_kechuang_1.py](strategies/kechuang/supermind_kechuang_1.py) | [backtest/run.py](strategies/kechuang/backtest/run.py) | [科创说明](strategies/kechuang/README.md) |
| 沪深1 | [supermind_hushen_1.py](strategies/hushen/supermind_hushen_1.py) | [backtest/run.py](strategies/hushen/backtest/run.py) | [沪深说明](strategies/hushen/README.md) |

科创基准1为用户2026-10-09指定的旧动态基准三，动态10%—20%入场目标、现金不足整笔跳过，源码不变。本轮50万元、每日频率、独立空仓。内部120K标题仅为历史命名，不设置账户本金；不是固定10%标准3-1或现金缩量C版。

沪深1沿用已有独立版本、资金和交易设置，本次未修改。两条策略的设置和成绩不能混用。

## 工程结构

```text
quant/
├── strategies/
│   ├── kechuang/
│   │   ├── supermind_kechuang_1.py
│   │   ├── research/             # 训练源码、模型与来源记录
│   │   ├── backtest/             # 本地回测、冻结快照和必要数据
│   │   └── results/              # 当前回测报告与明细
│   └── hushen/                   # 同样采用research/backtest/results
├── archive/
│   ├── kechuang/20261009_before_unification/
│   ├── hushen/
│   └── packages/20261006_data_environment_bundle/ # 离线迁移包；大文件不进Git
├── research_versions/            # 历史研究源码，不是当前入口
├── evening_accumulation/data/    # 科创行情，保护资产
├── sh_sz_market_research/data_pipeline/data/ # 沪深行情，保护资产
├── data_updates/                 # 行情备份与审计，保护资产
├── reports/                      # 历史跨策略对比，不映射当前版本收益
├── 国金ptrade/                    # 独立研究线
├── 量化审查/
├── tools/
└── AGENTS.md
```

## 结果与历史

- [科创基准1当前本地结果](strategies/kechuang/results/report.html)：50万元，2020起每半年独立启动，截至2026-09-30。
- [沪深1当前结果](strategies/hushen/results/report.html)。
- [科创旧基准历史](archive/kechuang/20261009_before_unification/HISTORY.md)。原三基准、3-2及各派生版本均已归档。
- [原根目录说明与五基准历史表格](archive/kechuang/README_root_before_20261009.md)。历史名称与数值保留，不视为当前入口。
- [历史研究版本索引](research_versions/README.md)。

## 保存与使用边界

训练源码、特征、模型实物、原始行情、快照、历史结果和来源清单保留；Python字节码等可重建缓存可以清理。移动归档不等于允许删除核心资产。当前回测不依赖归档脚本；历史脚本可能需要恢复旧路径才能运行。

Git保存两条当前基准的完整复现依赖，包括科创冻结快照、模型、沪深基准日历、公司行动和当前结果。历史归档中的大体积Parquet、离线迁移ZIP及安装程序保留在本机/移动硬盘，并用清单核验，不进入普通Git历史。具体边界见 [archive/README.md](archive/README.md)。

此次名称晋升和重构不代表通过新的平台验证或盲测。科创旧版执行问题没有在本次悄然修复。本地日线撮合、税费与平台/真实账户存在近似差异，各策略README说明具体限制。

## 安装与完整性检查

```powershell
.\quant_env\Scripts\python.exe -m pip install -r requirements.txt
.\quant_env\Scripts\python.exe tools/main.py
.\quant_env\Scripts\python.exe tools/main.py --full-archive
```

普通检查会核对两个入口、当前模型与回测数据、1240份科创快照、结果和目录边界；`--full-archive` 进一步逐文件重算科创清理后6280文件归档哈希。
