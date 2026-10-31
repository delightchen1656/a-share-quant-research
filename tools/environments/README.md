# 模块依赖与多对话协作

各对话按项目模块分工，不依赖聊天窗口的名字或线程ID。目录归属见 `modules.json`；一个对话可负责多个模块，但不能默认修改其他模块的输入、模型或环境。

| 模块名 | 工作目录 | 共用边界 |
|---|---|---|
| hushen1 | 沪深1研究 | 公共沪深行情只读；研发只读已授权白名单 |
| hushen2 | 沪深2研究 | 模型研究与生产工作台部署分开 |
| kechuang1 | 科创1研究 | 公共科创行情只读；训练源码和模型原件保留 |
| direction1 | 研究尝试/方向1_超跌反弹 | 独立冻结输入；禁止跨模块读取后验反馈 |
| gold_research | 研究尝试/gold_trend_stock_trial | 独立研究包；不等于桌面gold项目 |
| viewer | K线看盘软件 | 只读行情与展示导出；不触发策略研发 |
| workbench | 沪深实盘工作台 | 自有代码、模型、两套受保护账本 |
| practice | 沪深2研究/K线练习 | 自有引擎、冻结题库、练习记录 |
| market | K线数据 | 唯一公共行情维护职责；统一更新器、事务检查仍有效 |

## 按模块运行

在仓库根目录执行，例如：

```powershell
& .\quant_env\Scripts\python.exe -B .\tools\module_runtime.py hushen1 --probe
& .\quant_env\Scripts\python.exe -B .\tools\module_runtime.py workbench -- 沪深实盘工作台/verify_package.py
& .\quant_env\Scripts\python.exe -B .\tools\module_runtime.py hushen2 -- tools/replay_hushen2_local.py --frozen-only
```

入口将 TEMP/TMP、Matplotlib字体缓存、通用缓存和pip缓存放入所属模块 `.local/`，禁用用户site-packages和继承的PYTHONPATH，保留原根目录工作目录。脚本自身显式指定的输出位置不会被改写；结果仍须写本模块，后验进入受限目录。`.local/` 中也可能有尚未结束的测试或下载，不能直接整目录删除。

默认使用现有 `quant_env`；如果本模块存在 `.venv/Scripts/python.exe` 则优先使用。现有软件快捷方式、自动任务和直接运行命令保持兼容，不会自动切换到本入口。这里提供的是环境和工作约定，不是文件系统沙箱，也不会阻止代码主动访问其他目录。

## 环境重建与独立试验

`requirements.lock.txt` 是当前已安装发行包的准确版本快照，`runtime.json` 记录Python与系统信息。根requirements中scikit-learn已纠正为实际安装版本；历史训练源的requirements原件不改。锁定文件不是离线安装包，也不证明不同系统上的数值结果完全一致。

共享 `quant_env` 保持稳定。需要新包时，在所属模块创建独立环境；不要在其他对话运行期间升级共享环境。以下示例需要联网安装，不会自动执行：

```powershell
# 基础Python仍须先安装；本机已验证为3.10.11。
& .\quant_env\Scripts\python.exe -B -m venv .\沪深1研究\.venv
& .\沪深1研究\.venv\Scripts\python.exe -B -m pip install -r .\tools\environments\requirements.lock.txt
& .\沪深1研究\.venv\Scripts\python.exe -B -m pip check
```

创建后先运行本模块校验，再执行研究；需要增删包时，将变更后的依赖快照保存在本模块。不要把试验环境当作生产模型部署。冻结模型加载的scikit-learn等版本变化可能影响结果，必须通过既有等价校验。

## 外部依赖如何处理

- Python基础安装、Edge、Windows、字体、Git保留系统安装；共享只读安装不等于共享研究状态。
- 报表Node目录联接依赖Codex工具链，保留外部目标并记录实际包版本；不宣称这些历史报表已能脱离Codex独立重建。
- 公共行情按正式事务提交读取；各研究保留已批准的冻结快照，不为独立性重复下载或改写数据。
- 外部附件的保全副本及原路径/哈希仅保存在受限历史目录。历史构建脚本原件保留，硬编码外部路径的旧脚本尚需显式适配后才能在新机器重建。
- Codex调度、Windows任务、桌面gold项目和登录凭据保持各自管理。本轮不更改其他对话任务的启停、提示或绑定。
- 原始截图、对话历史、公司行动响应、下载原始包、模型和账本不是缓存。未证实归属或用途的外部目录不清理。

维护审计位置：`project_memory/holdout_restricted/module_independence_20261031/`。隔离研发不得读取这个审计目录。
