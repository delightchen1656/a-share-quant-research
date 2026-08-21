# Notebook 说明

| 文件 | 用途 |
| --- | --- |
| `CSI100_data_export.ipynb` | 从 SuperMind 获取并检查中证 100 成分股、行情与基本面数据 |
| `CSI100_strategy_comparison.ipynb` | 多因子、机器学习策略、基准和独立测试的主要研究 Notebook |
| `CSI100_strategy_comparison_legacy.ipynb` | 从原 `data/` 目录保留的旧版研究，不覆盖主版本 |

建议按“数据导出 → 主策略比较”的顺序运行。旧版 Notebook 仅用于追溯，不应作为最新结论来源。

Notebook 中依赖 `get_price`、`get_index_stocks` 等 SuperMind API 的单元格必须在 SuperMind 研究环境运行。本地运行前需要改为读取已导出的 CSV 或 Parquet。

