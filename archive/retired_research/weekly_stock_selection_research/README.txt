本目录为用户新建的独立股票筛选研究，不恢复旧策略。
研究规则、进度、完整结果与限制见 audits/holdout_restricted/research_v1/REPORT.txt。
原行情只读；本目录白名单与来源保留，不是可随意删除的缓存。
不下单、不部署、不修改生产基线。

信号均值诊断入口：audits/holdout_restricted/signal_average_v3/REPORT.txt。
因子优化开发报告入口：audits/holdout_restricted/monday_factor_v4/DEVELOPMENT_REPORT.txt。
冻结包入口：audits/holdout_restricted/monday_factor_v4/frozen_candidate_v1/FREEZE_MANIFEST.json。
单向审计协议：audits/holdout_restricted/monday_factor_v4/ONE_WAY_AUDIT_POLICY.json。
优化端不得读取审计结果目录；审计成绩只能直接交付用户，不得回流调参或替换候选。
第二轮因子开发入口：audits/holdout_restricted/monday_factor_v5/REPORT.txt；本轮仅在开发白名单内比较，不读取或重复验收后验窗口。
选股配套的研究买卖规则入口：audits/holdout_restricted/monday_trading_rules_v1/RULES.txt；结构化参数见同目录RULES.json。规则定义不代表账户回测验收或实盘部署。
买卖规则的开发账户回测入口：audits/holdout_restricted/monday_account_backtest_v1/REPORT.txt；冻结引擎见同目录frozen_engine_v1。账户后验报告保持单向交付，优化端只接收状态与路径。
账簿修复V1.1入口：audits/holdout_restricted/monday_account_backtest_v1_1/REPORT.txt。该版分离真实股东权益和除权参考口径，模型及交易规则不变；V1及其失败审计保留。
