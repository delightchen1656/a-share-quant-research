# Baseline2归档清单

正式名称：基准1-2止损过滤（旧称：策略2低风控版本1）。状态：冻结，只读基准；基准1-3另建目录研究。

- `strategy/research_baseline2.py`：十方向与Baseline2本地回测实现。
- `model/stop_risk_model.joblib`：先止损概率模型，训练截止2024-12-31。
- `platform/supermind_baseline_1_2_stop_filter_single.py`：基准1-2独立SuperMind自包含单文件。
- `platform/build_supermind_baseline_1_2.py`：平台单文件生成器。
- `platform/README.md`：平台设置和策略差异说明。
- `research/REPORT.md`：研究结论与方向排名。
- `research/direction_ranking.csv`：全方向完整指标。
- `research/independent_yearly.csv`：每年100万元独立入场结果。
- `research/continuous_annual.csv`：2020年开始连续复利的年度切片。
- `research/baseline2_trades.csv`：三方向叠加候选的交易明细（已否决，仅供审计）。
- `research/trades_stop_risk_filter.csv`：正式Baseline2交易明细。
- `research/start_year_to_20260731.csv`：不同年度投入100万元并持续到2026-07-31的对比。
- `research/capital_10w_start_year_to_20260731.csv`：10万元资金规模测试。
- `research/capital_1000w_start_year_to_20260731.csv`：1000万元资金规模测试（未做容量冲击压力测试）。
