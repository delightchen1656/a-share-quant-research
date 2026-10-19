# Batch 005 pre-2025 signal filters

This was the preregistered 13-run development batch defined by `protocol/BATCH_005.json`. The count-only and threshold-only experiments were selected independently and were never cross-combined. All 2020-2024 results are development results, not blind or holdout evidence. No production selection was changed.

## Frozen inputs and execution

- M internal `(utility, pen025, pen100)`: `(0.25, 0.75, 0.00)`
- T internal `(+mom120, +close/high60, +mom20, -vol60)`: `(0.50, 0.25, 0.25, 0.00)`
- H internal `(-size, -vol60, +overnight, -intraday)`: `(0.25, 0.25, 0.25, 0.25)`
- Outer `(M, T, H)`: `(0.30, 0.30, 0.40)`
- Execution: 30 calendar days, entry 0 ATR, take 4 ATR, stop 1.5 ATR, CNY 100,000, 10 slots, seven-calendar-day buy lifetime, T+1, stop-first double touch, fees/slippage, 2% daily-volume capacity, and corporate actions.

## Count-only experiment

The unique winner was `COUNT_ONLY_K3`; no score threshold was applied. Its signals are exactly identical to the frozen Batch004 champion signals.

Raw-price and corporate-action audited results:

| Metric | Value |
|---|---:|
| CAGR | 31.1624% |
| Worst annual return | 11.7787% |
| Profitable years | 5 |
| Completed trades | 1,025 |
| Trade-count CV | 0.0701 |

| Year | Audited return | Completed trades | Signals |
|---:|---:|---:|---:|
| 2020 | 40.0228% | 222 | 723 |
| 2021 | 47.9434% | 205 | 729 |
| 2022 | 38.3915% | 220 | 726 |
| 2023 | 21.1390% | 191 | 726 |
| 2024 | 11.7787% | 187 | 645 |

Overall frequency was 3,549 signals on 1,183/1,183 active signal sessions, exactly 3.000 signals per session.

## Threshold-only experiment

The unique eligible winner was `THRESHOLD_ONLY_Q50_K3`: K remained fixed at three, and a signal was emitted only when its frozen factor score was at least the shifted 252-session rolling median of prior daily maximum scores. The current session was excluded; 2018-2019 warmup supplied the causal history for 2020.

Raw-price and corporate-action audited results:

| Metric | Value |
|---|---:|
| CAGR | 11.5961% |
| Worst annual return | 3.6260% |
| Profitable years | 5 |
| Completed trades | 448 |
| Trade-count CV | 0.2464 |

| Year | Audited return | Completed trades | Signals | Active days / sessions |
|---:|---:|---:|---:|---:|
| 2020 | 13.8963% | 66 | 160 | 103 / 241 |
| 2021 | 9.3543% | 110 | 227 | 138 / 243 |
| 2022 | 3.6260% | 111 | 276 | 146 / 242 |
| 2023 | 9.1625% | 101 | 281 | 140 / 242 |
| 2024 | 22.8451% | 60 | 129 | 74 / 215 |

Overall frequency was 1,073 signals on 601/1,183 active signal sessions, averaging 0.9070 signals per session. Quantiles 0.75 and above failed the minimum-20-completed-trades-in-every-year eligibility rule; no grid was expanded.

## Audit assertions

- Both independently selected champions passed the per-year completed-trade and minimum-three-profitable-years rules.
- Corporate-action coverage is complete; all positions were closed by the end of the test.
- Maximum signal date: `2024-11-22`.
- Maximum raw execution date: `2024-12-31`.
- `post_2024_access=false`, `grid_expanded=false`, `production_change=false`.
