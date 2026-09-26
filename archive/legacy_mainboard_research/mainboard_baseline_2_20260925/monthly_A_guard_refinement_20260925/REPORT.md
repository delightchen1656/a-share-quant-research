# 净值回撤冷静期小范围追加研究

本轮根据上一轮D4结果追加12组，存在额外多重测试与反复用历史问题，不视作独立验证。仅使用前一交易日净值触发，下个交易日尝试退出；停牌/跌停等约束仍适用。冷静期后等月度调仓恢复，不自动在冷静期结束当日追买。

|版本|规则|开发年化中位数|最差回撤|Sharpe中位数|
|---|---|---:|---:|---:|
|BASE|无 power=0.5|16.89%|18.51%|0.899|
|F1|[0.08, 20] power=0.0|0.95%|27.25%|-0.071|
|F2|[0.08, 20] power=0.5|1.05%|25.45%|-0.065|
|F3|[0.08, 40] power=0.0|4.74%|18.88%|0.189|
|F4|[0.08, 40] power=0.5|3.53%|19.03%|0.111|
|F5|[0.1, 20] power=0.0|15.42%|18.03%|0.899|
|F6|[0.1, 20] power=0.5|15.01%|15.31%|0.912|
|F7|[0.1, 40] power=0.0|10.01%|19.41%|0.583|
|F8|[0.1, 40] power=0.5|12.35%|15.47%|0.711|
|F9|[0.12, 20] power=0.0|16.85%|16.88%|0.935|
|F10|[0.12, 20] power=0.5|16.32%|18.43%|0.886|
|F11|[0.12, 40] power=0.0|11.89%|19.18%|0.667|
|F12|[0.12, 40] power=0.5|12.68%|20.45%|0.704|

验证：{"BASE": {"audit": {"count": 24, "median": 0.185414542378876, "p10": 0.14304242481490828, "worst": 0.11710619615290652, "drawdown": -0.14148285275014905, "sharpe": 0.9656236974597103, "fees": 2519.535}, "stress": {"count": 24, "median": 0.1524655550104873, "p10": 0.11125697902628821, "worst": 0.07679912604309824, "drawdown": -0.1542978947237148, "sharpe": 0.7678168541042703, "fees": 3511.2650000000003}}, "F6": {"audit": {"count": 24, "median": 0.18951803467640127, "p10": 0.08563348978711077, "worst": 0.040064401539745775, "drawdown": -0.2510537847202674, "sharpe": 1.0268724237373894, "fees": 2406.73}, "stress": {"count": 24, "median": 0.16279676340053073, "p10": 0.04210390675603728, "worst": 0.02550527735135555, "drawdown": -0.2541076047009714, "sharpe": 0.8735726864335179, "fees": 3365.46}}, "F10": {"audit": {"count": 24, "median": 0.11596606343211968, "p10": 0.07318528850678889, "worst": 0.04403503512531559, "drawdown": -0.23623101275626734, "sharpe": 0.5943807586049923, "fees": 2307.78}, "stress": {"count": 24, "median": 0.07308554519416732, "p10": 0.03561157216311786, "worst": 0.011152752561971235, "drawdown": -0.248006199723939, "sharpe": 0.380531167522833, "fees": 3148.915}}}
全期：{"BASE": {"final_equity": 245749.27000000002, "total_return": 1.4574927, "trading_days": 1624, "annualized": 0.14845166342678184, "volatility": 0.17001702901776874, "drawdown": -0.16437104462564045, "risk_free_annual": 0.02, "sharpe": 0.7555223389614529, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 11518.33, "orders": 672, "unresolved_actions": 0, "guard_triggers": 0}, "F6": {"final_equity": 259418.41999999998, "total_return": 1.5941842, "trading_days": 1624, "annualized": 0.15806157501279872, "volatility": 0.1607192119568047, "drawdown": -0.16152016143882786, "risk_free_annual": 0.02, "sharpe": 0.8590234691413526, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 11542.77, "orders": 661, "unresolved_actions": 0, "guard_triggers": 6}, "F10": {"final_equity": 186256.47000000003, "total_return": 0.8625647000000003, "trading_days": 1624, "annualized": 0.10047754035792122, "volatility": 0.15643999406370265, "drawdown": -0.23582275743326153, "risk_free_annual": 0.02, "sharpe": 0.5144307300673421, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 10147.65, "orders": 642, "unresolved_actions": 0, "guard_triggers": 6}}
目标检查：{"F6": {"checks": {"full_sharpe": false, "audit_sharpe": true, "return_floor": true, "drawdown": false, "stress": true}, "passed": false}, "F10": {"checks": {"full_sharpe": false, "audit_sharpe": false, "return_floor": false, "drawdown": false, "stress": false}, "passed": false}}
10万元，平台公式Rf暂按2%；全期2020-01-02至2026-09-11；24开发和24验证起点各24个月，压力佣金/最低费用/滑点翻倍。已使用历史不是独立样本外，分钟撮合和历史覆盖误差仍存在。原策略未覆盖。
