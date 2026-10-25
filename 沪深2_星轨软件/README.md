# 星轨 · 沪深2独立软件包

本目录是沪深2晚间工作台的独立运行副本。代码、三份模型、当前登记、运行时、风险复算依赖、UI、测试以及本地账本历史都保存在本目录；行情只读访问仓库公共沪深日线库和 `data_updates/` 审计。

当前策略血缘为：原 `C04_NEW` → ATR≥2.5% → P12 → 撤销P12的规模/波动条件并回到ATR-only。现行软件只执行原每日前三之后的 `ATR≥0.025` 过滤，不递补、不重排，不重训模型。P12代码和登记只保存在 `history/source/`，不参与运行。

## 目录

- `CURRENT_SELECTION.json`：当前唯一登记。
- `runtime/`：冻结构建器和ATR-only过滤。
- `model/`：utility、pen025、pen100冻结模型及来源清单。
- `tracker/`：本地服务、UI、账本、测试和安装脚本。
- `tracker/data/`：实际软件历史、SQLite账本、缓存和备份；不得作为缓存删除。
- `backtest/`、`results/`：登记自检所需的最小风险复算依赖。
- `history/`：ATR、P12及回退过程的历史源码副本，不参与当前运行。
- `reference/`：当前单元测试所需的三份原始冻结构建函数副本，不从仓库归档导入。

## 验证与运行

```powershell
& .\quant_env\Scripts\python.exe -B .\沪深2_星轨软件\verify_package.py
& .\quant_env\Scripts\python.exe -B -m unittest discover -s .\沪深2_星轨软件\tracker -p 'test_*.py'
& .\沪深2_星轨软件\tracker\install.ps1
```

安装脚本会把桌面“沪深2 星轨”快捷方式和 `Hushen2_Orbit_1830` 任务切换到本目录。软件不连接券商，也不自动下单。
