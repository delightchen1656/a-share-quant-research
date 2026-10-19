# 历史与离线资产归档

当前可运行策略只在 `strategies/`。本目录保存退出当前范围的完整研究树、历史源码及离线迁移包，不作为日常策略入口。

| 路径 | 内容 | Git策略 |
|---|---|---|
| `kechuang/20261009_before_unification/` | 科创统一前完整旧树 | 源码、文档、结果摘要和模型进入Git；大型历史Parquet留本地，双清单记录迁移前后哈希 |
| `hushen/20261008_before_unification/` | 沪深统一前完整旧树 | 源码、文档、结果摘要和模型进入Git；大型历史Parquet留本地 |
| `hushen/research_versions/` | 九类沪深历史研究源码 | 进入Git |
| `hushen_2/` | 沪深2登记前研究、输入、比较表和审计来源 | 当前登记不在此处；大体积输入及Parquet按本地研究资产保存 |
| `screening/` | 一次性筛选脚本与输出 | 仅供溯源，不是当前基线或自动任务 |
| `packages/20261006_data_environment_bundle/` | 行情与环境离线迁移包 | 说明、清单和恢复脚本进入Git；ZIP及安装程序留在本地/移动硬盘 |

科创归档清单：

- `kechuang/20261009_manifest_before.json`：清理前6288个文件；
- `kechuang/20261009_manifest_after_cache_cleanup.json`：删除8个可重建字节码后6280个文件；
- `kechuang/20261009_cache_cleanup.json`：全仓缓存清理结果；
- `kechuang/20261009_cache_cleanup_pending_before.json`：清理前待办原始记录。

2026-10-20目录整理另见 `CACHE_CLEANUP_20261020.md`。

普通GitHub克隆保存三条当前基线的登记、代码和必要复现依赖，但不会下载历史大体积Parquet、离线ZIP或安装程序。需要完整冷归档时，应同时保留本机归档和迁移包，并按清单核验。

2026-10-09另删除沪深旧全流程目录中一份可重建的114.6 MB因子缓存，来源哈希及保留边界见 `hushen/20261009_cache_cleanup.json`；策略源码、协议、排名、报告和结果均保留。
