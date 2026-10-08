# 项目数据与环境迁移包

生成日期：2026-10-06。

本目录是2026-10-06生成的离线迁移包，现归档于 `archive/packages/20261006_data_environment_bundle/`。它包含行情数据、数据来源与修正记录、SuperMind/Python安装包、本地Python环境清单，以及一个专用于迁移验收的基础均线示例。生成时的正式策略、研究候选、模型、历史回测报告、账户资料和交易凭证均未包含。

## 内容

| 文件或目录 | 用途 |
|---|---|
| `01_hushen_data.zip` | 沪深行情库：raw、qfq、证券池、行业映射、交易日历、更新元数据；13,588 个文件 |
| `02_kechuang_data.zip` | 科创行情库：raw、qfq、证券池、交易日历、更新元数据；2,487 个文件 |
| `03_data_provenance_and_backups.zip` | 2026-10-04 更新前备份、供应商数据修正前原件、审计和恢复记录。排除了 `staged/` 临时区，因为它是正式数据/备份的重复工作副本 |
| `*.manifest.json` | 每个压缩包内逐文件的大小和 SHA-256，可用于核对传输完整性 |
| `data_summary.json` | 三个压缩包的文件数、源文件总大小和压缩包 SHA-256 |
| `installers/` | SuperMind 量化版客户端和 Python 3.10.11 64 位安装包，以及来源和哈希 |
| `environment/` | 当前电脑的完整包版本锁、原始项目依赖及系统环境快照 |
| `verify_bundle.ps1` | 在新电脑核验压缩包与安装包哈希，并测试 ZIP 结构 |
| `restore_data.ps1` | 在新电脑将两个正式行情包恢复到原目录结构 |
| `create_environment.ps1` | 创建 Python 3.10 虚拟环境并安装项目所需核心依赖 |
| `basic_backtest_example/` | 同一简单均线策略的本地回测版、SuperMind版、现金分红快照、测试与运行说明 |

## 新电脑建议顺序

首次使用双击根目录的 `一键环境安装.bat`。它会依次校验文件，将沪深和科创正式行情解压到 `local_project/`，安装精确的Python 3.10.11、创建隔离环境、安装依赖、运行测试和示例回测、生成SuperMind源码，最后打开SuperMind安装程序等待用户完成界面安装。脚本可以重复运行，已经完成的解压和安装步骤会跳过。新电脑已有的Python 3.13会保留，但本项目不会使用它，避免卸载3.13影响其他软件。审计和更新前备份 `03_data_provenance_and_backups.zip` 默认保持压缩保存，本地回测不依赖它。

环境安装完成后，双击 `一键本地回测.bat` 即可使用 `默认策略.py` 运行完整本地回测。结束后会自动打开结果目录。

安装完成后，本地默认因子位于 `basic_backtest_example/默认策略.py`，可直接复制到平台的版本为 `basic_backtest_example/默认SuperMind策略.py`。

以下是手工安装步骤，供一键脚本失败时排查：

1. 将整个 `20261006_data_environment_bundle` 目录复制到新电脑，复制完成后运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\verify_bundle.ps1
   ```

2. 安装 `installers/python-3.10.11-amd64.exe`。安装时勾选 **Add Python to PATH**。当前项目环境来自 Python 3.10.11 x64；为复现旧环境保留该版本。Python 官方已将 3.10.11 标记为停止安全维护，因此这只用于复现，联网日常使用宜后续单独测试升级。

3. 在准备好的项目空目录中恢复行情。下面的目标路径只是示例：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\restore_data.ps1 -Destination 'D:\quant'
   ```

   恢复后得到：

   - `D:\quant\sh_sz_market_research\data_pipeline\data\...`
   - `D:\quant\evening_accumulation\data\...`

4. 创建本地研究环境（需要互联网访问 PyPI）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\create_environment.ps1 -Destination 'D:\quant'
   ```

   核心环境包括 numpy、pandas、matplotlib、Jupyter、scikit-learn、LightGBM、BaoStock、AkShare、PyArrow、SciPy、openpyxl 和 xlrd。`environment/requirements.lock.txt` 是当前电脑全部已安装包的精确版本，仅在需要完全复刻时使用。

5. 安装 `installers/SuperMind_TYB_v8.18.1.9791.exe`。这是与旧电脑 `C:\Users\22241\SuperMindTYB` 注册信息一致的官方SuperMind体验版8.18.1.9791，来源为官方体验版下载入口 `https://download.10jqka.com.cn/index/download/id/709`。安装后使用原同花顺/SuperMind账号登录；账号和平台权限不能靠复制文件迁移。

6. 需要确认数据和环境可运行时，按 `basic_backtest_example/README.md` 执行最小本地回测；对应的SuperMind代码也在同一目录。它是迁移验收示例，不是正式策略。

## 数据边界

- 沪深：3,396 只历史股票；科创：621 只历史股票。raw 与 qfq 均已包含。
- 正式行情更新至 2026-09-30（当时最新已收盘交易日）；退市股票只保留到最后有效日期。
- 沪深仍有 11 只股票的历史前复权衔接异常，完整清单与日期在第三个压缩包的 `data_updates/20261004/audit.json`，不能把它们视为已修复。
- `03_data_provenance_and_backups.zip` 不是运行行情所必需，但它保存了恢复来源、更新前版本与修正证据，建议作为冷备份一同转移。

## 另外需要手工迁移的内容

- SuperMind/同花顺账号、券商账号和授权：只需记住账号并在新电脑重新登录，不要把密码写进迁移包。
- 如果旧电脑浏览器或客户端中有未同步的自定义研究文件、Notebook、自定义数据、策略或云端文件，请在平台中另行导出。本迁移包按要求没有收录策略。
- 若新电脑需要继续更新 BaoStock 行情，还要保证能联网；依赖已经列入环境脚本。
- 建议把整个迁移目录再复制到移动硬盘或另一块磁盘。仅保留一份仍不算备份。

SuperMind 官方入口：<https://quant.10jqka.com.cn/>；官方客户端下载页：<https://www.forfunds.cn/platform/pcweb/softwareDownload/>。
