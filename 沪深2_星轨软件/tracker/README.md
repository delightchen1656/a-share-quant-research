# 星轨运行说明

本目录是根目录 `沪深2_星轨软件/` 的当前运行层。现行推荐规则只有一项附加过滤：原冻结每日前三之后保留 `ATR≥2.5%` 的候选；不递补、不重排，不使用P12规模代理或60日波动条件。

## 每晚流程

1. 读取已经由 `tools/daily_market_update.py` 成功提交的沪深日线与审计。
2. 用户补录实际成交并复核券商现金和总权益。
3. 使用本包冻结代码、模型和登记生成0—3只新推荐。
4. 用户人工接受或拒绝；软件不连接券商、不自动下单。
5. 持仓止盈、止损和到期退出均由软件提示、用户实际执行并回填。

`data/ledger.sqlite3`、`data/backups/`、历史信号缓存和观察记录是软件历史，不是缓存。新包首次接管前后不得同时运行旧路径和新路径的两个后台，以免产生两份账本分支。

## 运行

```powershell
& .\沪深2_星轨软件\tracker\install.ps1
& .\quant_env\Scripts\python.exe -B .\沪深2_星轨软件\tracker\app.py
```

服务只监听 `127.0.0.1:18762`。安装脚本创建桌面快捷方式并登记18:30任务。

## 验证

```powershell
& .\quant_env\Scripts\python.exe -B .\沪深2_星轨软件\verify_package.py
& .\quant_env\Scripts\python.exe -B -m unittest discover -s .\沪深2_星轨软件\tracker -p 'test_*.py'
```

P12部署、ATR回退、历史资金初始化和旧全量对照脚本已移入 `../history/source/`，不属于当前运行入口。
