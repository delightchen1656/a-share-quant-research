# Batch012 审计路径

- 事前协议：`../../../protocol/BATCH_012_PRE2025_NEW_SLOT_GRID.json`
- 摘要冻结：`../SELECTION.json`
- 最终状态：`../FINAL_SELECTION.json`
- 审计结论：`FINAL_AUDIT.json`
- 原始输入清单与逐文件 pre-2025 哈希：`raw_pre2025_input_manifest.csv`
- 唯一候选原始逐笔成交：`selected_candidate_full_window_trades_raw.csv`
- 唯一候选原始逐年结果：`selected_candidate_annual_metrics_raw.csv`
- 唯一候选原始信号利用率：`selected_candidate_signal_utilization_raw.csv`
- 唯一候选原始共享 Q1 25 次运行：`selected_candidate_shared_q1_raw_25.csv`

`FINAL_AUDIT.json` 同时记录基础公司行动、Batch006/007/010 补充公司行动、退市元数据、协议、摘要冻结文件与运行器哈希。审计失败不触发重选。
