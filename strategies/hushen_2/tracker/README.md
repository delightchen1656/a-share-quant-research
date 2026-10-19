# 星轨 · 沪深2晚间工作台

桌面双击 **沪深2 星轨** 即可打开独立窗口。代码位于本目录；后台仅监听本机 `127.0.0.1:18762`。

## 当前交付状态

实际账户、每日任务、录入窗口、接受/拒绝、复制国金参数、自动备份、冲正、恢复、CSV导出、桌面快捷方式及18:30任务已实现。

**原模型数值树已恢复并保存到 `../model/`。** 可执行文件哈希、原文件来源哈希分别保存在 `../model/manifest.json`；2,595,713条原预测和3,549条最终信号完全一致。2026-10-20已用成功提交的2026-10-19行情完成一次行情到三只候选的端到端只读验证，记录见 `../model/END_TO_END_VERIFICATION.json`；验证未写账户、未触发券商操作。

## 晚间流程

1. 18:30后台读取已提交行情和交易日历；不会启动第二个行情下载进程。
2. 19:00后至下一交易日开盘前，先录入当天实际成交、撤单、资金变化，再完成账户核对。
3. 根据持仓状态处理必要卖单。买入次日起可卖；以信号日固定ATR、实际成交均价计算4ATR止盈和1.5ATR止损。
4. 有空槽且数据与模型就绪时，处理原始前三信号。接受表示你已在国金设置买单；拒绝无需原因。
5. 点击今晚操作完成。保护单、到期退出、残留卖单、账户核对和数据异常未处理时会阻止完成。

有效挂单和持仓合计最多5槽，同股合并占槽。未处理推荐跨日自动拒绝；已接受的国金订单不会被软件自动撤销。成交一律来自人工录入。

买入部分成交后核对五档剩余数量是否撤销；卖出部分成交后，为剩余股份重新设置保护。记录税费输入券商实际全部税费。现金调整可登记入出金、分红和费用差异，并填写说明。

## 自动运行

Windows任务 `Hushen2_Orbit_1830` 每天18:30启动本地后台。电脑需开机并登录；错过后系统尽快补跑。窗口关闭后后台继续；重复启动不会产生第二个服务。

软件内可手动更新；模型或行情未就绪时显示具体原因，保留上次账本。未来交易日来自BaoStock交易日历，不按工作日猜测。尾盘到期退出需在国金设置定时单；若不支持，任务保持待处理。

日常不需要Codex。现有18:00行情更新任务仍由原行情流程负责；软件不改它的调度，也不重复下载。

## 账户保存

初始100000元空仓。`data/ledger.sqlite3`保存实际记录，`data/backups/`保存自动备份，均被Git忽略。每条记录可冲正，存在后续依赖时先处理后续记录。恢复备份前自动保存当前账本副本。

## 维护命令

```powershell
& .\quant_env\Scripts\python.exe -B strategies\hushen_2\tracker\test_ledger.py
& .\quant_env\Scripts\python.exe -B strategies\hushen_2\tracker\test_pipeline.py
& .\quant_env\Scripts\python.exe -B strategies\hushen_2\tracker\verify_pipeline.py
& .\quant_env\Scripts\python.exe -B strategies\hushen_2\tracker\smoke_integration.py
& .\strategies\hushen_2\tracker\install.ps1
```

`verify_pipeline.py`是耗时的全量独立源实现比对；`smoke_integration.py`要求本地工作台已经运行，只调用本机更新接口，不执行接受、拒绝、买卖或券商操作。`install.ps1`创建桌面快捷方式和独立Windows任务，可重新运行。

## 全流程一致性核验

2026-10-20进一步完成独立原研究源码对照：同一份已提交的2026-10-19本地行情，3,889,665条有效面板记录的股票池、模型分数、ATR及全部因子逐项一致，4,926条最终信号的日期、股票、顺序及分数一致，最大误差为0。实际本机服务生成的3条当日候选同样匹配，适用于2026-10-20；交易触发价核对为未复权收盘价。

证据保存在本机私有目录：`data/pipeline_verification.json`、`data/integration_smoke.json`，未提交真实账户数据。该核验是相同输入上的实现一致性检查，不是新的收益回测或独立盲测；不把当前前复权历史修订当作原先冻结输入。

已修复原模型特征与技术特征有效样本的交集条件，并取消H因子历史的90自然日截断。日常运行不导入归档研究代码，只有维护核验脚本需要它。

生成信号前后检查行情更新进程、暂存事务、审计与metadata refresh、提交清单、活跃证券最新日期、模型/代码指纹及文件清单稳定性。冻结信号含来源指纹和内容哈希；重复更新复用原件，不覆盖。来源变化或内容损坏则阻断，不能自动覆盖历史。18:30未就绪时，后台每5分钟重试；次日行情未就绪时不开放新推荐。

维护测试（仓库根目录）：

```powershell
.\quant_env\Scripts\python.exe -B -m unittest discover -s strategies/hushen_2/tracker -p 'test_*.py'
.\quant_env\Scripts\python.exe -B strategies/hushen_2/tracker/verify_pipeline.py
.\quant_env\Scripts\python.exe -B strategies/hushen_2/tracker/smoke_integration.py
```

独立全量核验会读取多年全市场数据，耗时及内存高于日常查看；无需每天手动运行。
