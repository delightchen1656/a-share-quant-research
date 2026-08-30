# 科创板行业温度双基准（基准2-1—2-2）

- `strategy_4_temperature_attack/`：基准2-1，温度进攻（内部技术路径保留旧名）。
- `strategy_5_rising_defense/`：基准2-2，升温防守（内部技术路径保留旧名）。

两个目录均为冻结快照。共享实现位于上级目录的 `optimize_six_temperature.py`，共享行业映射为 `industry_map.csv`，每日温度为 `outputs/temperature_variants/daily_temperature.parquet`，冻结候选缓存为 `outputs/six_optimized/prepared_candidates.joblib`。
