# 净值回撤冷静期研究

仅使用前一交易日净值触发，下个交易日尝试退出；停牌/跌停等约束仍适用。冷静期后等月度调仓恢复，不自动在冷静期结束当日追买。

|版本|规则|开发年化中位数|最差回撤|Sharpe中位数|
|---|---|---:|---:|---:|
|BASE|无|16.89%|18.51%|0.899|
|D1|[0.06, 10]|6.94%|20.58%|0.323|
|D2|[0.06, 20]|7.26%|15.36%|0.376|
|D3|[0.1, 10]|12.72%|17.92%|0.704|
|D4|[0.1, 20]|15.01%|15.31%|0.912|
|D5|[0.14, 10]|17.36%|22.76%|0.921|
|D6|[0.14, 20]|17.36%|18.69%|0.921|

验证：{"BASE": {"audit": {"count": 24, "median": 0.185414542378876, "p10": 0.14304242481490828, "worst": 0.11710619615290652, "drawdown": -0.14148285275014905, "sharpe": 0.9656236974597103, "fees": 2519.535}, "stress": {"count": 24, "median": 0.1524655550104873, "p10": 0.11125697902628821, "worst": 0.07679912604309824, "drawdown": -0.1542978947237148, "sharpe": 0.7678168541042703, "fees": 3511.2650000000003}}, "D6": {"audit": {"count": 24, "median": 0.185414542378876, "p10": 0.14304242481490828, "worst": 0.08701421504022555, "drawdown": -0.14349002504581887, "sharpe": 0.9656236974597103, "fees": 2519.535}, "stress": {"count": 24, "median": 0.1524655550104873, "p10": 0.08905029398719747, "worst": 0.06386134207133054, "drawdown": -0.17622454443877567, "sharpe": 0.7678168541042703, "fees": 3472.925}}, "D4": {"audit": {"count": 24, "median": 0.18951803467640127, "p10": 0.08563348978711077, "worst": 0.040064401539745775, "drawdown": -0.2510537847202674, "sharpe": 1.0268724237373894, "fees": 2406.73}, "stress": {"count": 24, "median": 0.16279676340053073, "p10": 0.04210390675603728, "worst": 0.02550527735135555, "drawdown": -0.2541076047009714, "sharpe": 0.8735726864335179, "fees": 3365.46}}}
全期：{"BASE": {"final_equity": 245749.27000000002, "total_return": 1.4574927, "trading_days": 1624, "annualized": 0.14845166342678184, "volatility": 0.17001702901776874, "drawdown": -0.16437104462564045, "risk_free_annual": 0.02, "sharpe": 0.7555223389614529, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 11518.33, "orders": 672, "unresolved_actions": 0, "guard_triggers": 0}, "D6": {"final_equity": 248146.35999999996, "total_return": 1.4814635999999997, "trading_days": 1624, "annualized": 0.15016907264583867, "volatility": 0.16889443078115762, "drawdown": -0.159535149146374, "risk_free_annual": 0.02, "sharpe": 0.7707126401018117, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 11603.960000000001, "orders": 673, "unresolved_actions": 0, "guard_triggers": 1}, "D4": {"final_equity": 259418.41999999998, "total_return": 1.5941842, "trading_days": 1624, "annualized": 0.15806157501279872, "volatility": 0.1607192119568047, "drawdown": -0.16152016143882786, "risk_free_annual": 0.02, "sharpe": 0.8590234691413526, "sharpe_status": "formula_applied_with_supplied_rf", "start": "2020-01-02", "end": "2026-09-11", "fees": 11542.77, "orders": 661, "unresolved_actions": 0, "guard_triggers": 6}}
目标检查：{"D6": {"checks": {"full_sharpe": false, "audit_sharpe": false, "return_floor": true, "drawdown": true, "stress": true}, "passed": false}, "D4": {"checks": {"full_sharpe": false, "audit_sharpe": true, "return_floor": true, "drawdown": false, "stress": true}, "passed": false}}
10万元，平台公式Rf暂按2%；全期2020-01-02至2026-09-11；24开发和24验证起点各24个月，压力佣金/最低费用/滑点翻倍。已使用历史不是独立样本外，分钟撮合和历史覆盖误差仍存在。原策略未覆盖。
