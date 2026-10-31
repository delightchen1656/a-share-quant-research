# Kechuang Baseline 1 frozen-model replay

- Initial cash per run: CNY 500,000
- Latest audited trading day: 2026-10-26
- Development period: 2020-2024
- Frozen holdout period: 2025 onward
- Model retraining: no
- Parameter changes: no
- Frozen history through 2026-09-30; post-freeze signals reconstructed from daily transaction backups.

| Scope | Actual start | End | Final asset | Total return | CAGR | Max drawdown | Sharpe |
|---|---|---|---:|---:|---:|---:|---:|
| 2020 independent | 2020-01-02 | 2020-12-31 | 1,255,690.46 | 151.14% | 151.93% | -11.93% | 3.718 |
| 2021 independent | 2021-01-04 | 2021-12-31 | 1,094,463.44 | 118.89% | 120.92% | -14.36% | 3.369 |
| 2022 independent | 2022-01-04 | 2022-12-30 | 718,828.36 | 43.77% | 44.53% | -23.24% | 1.285 |
| 2023 independent | 2023-01-03 | 2023-12-29 | 958,896.77 | 91.78% | 93.61% | -10.91% | 3.016 |
| 2024 independent | 2024-01-02 | 2024-12-31 | 701,665.98 | 40.33% | 40.50% | -33.70% | 1.064 |
| 2025 independent | 2025-01-02 | 2025-12-31 | 1,036,416.99 | 107.28% | 108.22% | -5.60% | 3.592 |
| 2026 independent | 2026-01-05 | 2026-10-26 | 358,755.60 | -28.25% | -33.80% | -34.63% | -1.116 |
| 2020 continuous | 2020-01-02 | 2026-10-26 | 13,125,980.61 | 2,525.20% | 61.53% | -37.72% | 1.809 |
| 2025 continuous holdout | 2025-01-02 | 2026-10-26 | 896,452.38 | 79.29% | 38.01% | -30.92% | 1.366 |

The 2020 and 2025 continuous accounts exactly match the frozen reference equity and fees at 2026-09-30. Historical backtest results do not represent future returns.
