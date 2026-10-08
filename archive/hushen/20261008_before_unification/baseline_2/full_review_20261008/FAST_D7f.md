# D7f按需行情提速

入口：supermind_baseline2_D7f_fast_daily.py。平台选择每日、100000元、独立空仓账户，完整替换代码。本版以D7c兼容版为基础，原文件均保留。

瓶颈：D7c非调仓日虽不算排名，仍每天查询历史证券池、增量下载并合并全市场行情。

D7f只修改_before_trading：调仓日仍取得5个历史评分日期的证券池并更新全市场；非调仓日仅更新持仓及目标股票的行情，继续计算量能/ST、处理送转后的目标数量、保留未成交目标。全市场游标仅在全市场更新完成后推进；持仓逐股按自身缓存末日补齐，防止把持仓更新误认为全市场已更新。下次调仓统一补齐间隔内历史，不缩小选股池、不更改四因子、持股数、周期、限价、费用或下单逻辑。

首次全市场初始化仍耗时；调仓日请求跨度比原每日增量大。收益目标是维持D7c逻辑，不承诺平台耗时倍数或完全逐笔一致；数据接口如追溯修订历史，分批获取时点不同可能产生差异。

验证：verify_fast_D7f.py运行真实盘前/执行/盘后函数，未绕过历史请求直接塞排名。180只合成股票、70交易日，包含上市、退市、ST、停牌、拒单重试，逐日排名/目标/订单/持仓/现金一致；除盘前函数外全部函数AST一致。本地模拟历史接口下17.01秒降至6.18秒（约2.75倍），不是SuperMind服务器测速。另可运行 --real 验证本地180只真实行情子集，同样使用模拟撮合；详细结果见fast_D7f_real_validation.json，不代表全市场收益回测。

复核命令：
```
.\quant_env\Scripts\python.exe strategies/hushen/baseline_2/full_review_20261008/verify_fast_D7f.py
.\quant_env\Scripts\python.exe strategies/hushen/baseline_2/full_review_20261008/verify_fast_D7f.py --real
```

原D7研究结果不重标为D7f平台实测。D7c暂时移除的高级回报审计能力仍未恢复，见COMPATIBILITY_D7c.md。旧run_all.py不会覆盖本提速入口。
