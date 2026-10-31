# Batch 004 pre-2025 factor tuning

This was a preregistered 151-run sequential development batch. All 2020-2024 results, including 2022-2024, are development results rather than blind or holdout evidence. No grid was expanded and no production selection was changed.

## Audited champion

- Candidate: `P4_OUTER_030_030_040`
- M internal weights (utility, pen025, pen100): `[0.25, 0.75, 0.0]`
- T internal weights (+mom120, +close/high60, +mom20, -vol60): `[0.5, 0.25, 0.25, 0.0]`
- H internal weights (-size, -vol60, +overnight, -intraday): `[0.25, 0.25, 0.25, 0.25]`
- Outer weights (M, T, H): `[0.3, 0.3, 0.4]`
- CAGR: 31.1624%
- Final equity: 388192.48
- Worst annual return: 11.7787%
- Profitable years: 5
- Completed trades: 1025
- 2022-2024 development CAGR: 23.2871%
- Grid-boundary flags (reported only; no expansion): `{'M_internal': True, 'T_internal': True, 'H_internal': False, 'outer': False}`

| Development year | Audited return | Completed trades |
|---:|---:|---:|
| 2020 | 40.0228% | 222 |
| 2021 | 47.9434% | 205 |
| 2022 | 38.3915% | 220 |
| 2023 | 21.1390% | 191 |
| 2024 | 11.7787% | 187 |

The audit used raw unadjusted OHLC for fills/exits and applied the existing pre-2025 corporate-action and delisting records. The 2% daily-volume full-fill approximation, fees, slippage, T+1 rule, stop-first double-touch rule, seven-calendar-day buy lifetime, and 30-calendar-day holding horizon remained unchanged.
