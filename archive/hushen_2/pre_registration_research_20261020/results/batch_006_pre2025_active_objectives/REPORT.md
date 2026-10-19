# Batch 006 pre-2025 active-return objectives

This preregistered batch ran two independent four-stage paths of 151 candidates each (302 total). All 2020-2024 results are development evidence, not blind or holdout evidence. No grid expansion or production change occurred.

The benchmark is the Eastmoney/AkShare `sh000001` Shanghai Composite ordinary price index (`000001.SH`). Its annual return is the final trading close of each calendar year divided by the prior calendar year's final trading close minus one. The price index excludes dividends, while the audited strategy account includes corporate-action cash dividends; active returns therefore have that comparison limitation.

The prior unidentified `strategies/hushen/backtest/data/benchmark.parquet` was rejected because its fields and parquet metadata did not establish instrument identity and it was not used to calculate returns.

The two champions were audited independently because their effective specifications differed. Audit results did not trigger reselection.

## defense_maximin

- Screening champion: `DEF_P4_OUTER_060_000_040`
- M internal (utility, pen025, pen100): `[0.5, 0.5, 0.0]`
- T internal (+mom120, +close/high60, +mom20, -vol60): `[0.5, 0.0, 0.5, 0.0]`
- H internal (-size, -vol60, +overnight, -intraday): `[0.25, 0.25, 0.5, 0.0]`
- Outer (M, T, H): `[0.6, 0.0, 0.4]`
- Screening active min / mean / std(ddof=0): 13.7499% / 19.9760% / 6.3628%
- Audited active min / mean / std(ddof=0): 11.6957% / 20.9429% / 10.6758%
- Audited active variance check: 0.0113973194 (recorded only; never selected on variance)
- Audited CAGR / final equity: 22.1711% / 272170.84
- Positive active years: 5
- Boundary flags: `{'M_internal': True, 'T_internal': True, 'H_internal': True, 'outer': True}`
- Signal frequency: `{'2020': {'signals': 723, 'signal_days': 241, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2021': {'signals': 729, 'signal_days': 243, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2022': {'signals': 726, 'signal_days': 242, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2023': {'signals': 726, 'signal_days': 242, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2024': {'signals': 645, 'signal_days': 215, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}}`

| Development year | Strategy return | Shanghai Composite price return | Active return | Completed trades |
|---:|---:|---:|---:|---:|
| 2020 | 29.3755% | 13.8667% | 15.5089% | 207 |
| 2021 | 45.7864% | 4.8001% | 40.9863% | 209 |
| 2022 | -1.2627% | -15.1251% | 13.8624% | 231 |
| 2023 | 7.9948% | -3.7009% | 11.6957% | 193 |
| 2024 | 35.3282% | 12.6669% | 22.6613% | 204 |

## stability_min_std

- Screening champion: `STAB_P4_OUTER_020_030_050`
- M internal (utility, pen025, pen100): `[0.5, 0.5, 0.0]`
- T internal (+mom120, +close/high60, +mom20, -vol60): `[0.5, 0.0, 0.25, 0.25]`
- H internal (-size, -vol60, +overnight, -intraday): `[0.0, 1.0, 0.0, 0.0]`
- Outer (M, T, H): `[0.2, 0.3, 0.5]`
- Screening active min / mean / std(ddof=0): -0.0708% / 2.6520% / 1.8123%
- Audited active min / mean / std(ddof=0): 2.2895% / 4.3599% / 1.9400%
- Audited active variance check: 0.0003763631 (recorded only; never selected on variance)
- Audited CAGR / final equity: 6.1679% / 134886.06
- Positive active years: 5
- Boundary flags: `{'M_internal': True, 'T_internal': True, 'H_internal': True, 'outer': False}`
- Signal frequency: `{'2020': {'signals': 723, 'signal_days': 241, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2021': {'signals': 729, 'signal_days': 243, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2022': {'signals': 726, 'signal_days': 242, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2023': {'signals': 726, 'signal_days': 242, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}, '2024': {'signals': 645, 'signal_days': 215, 'maximum_signals_in_a_day': 3, 'mean_signals_per_signal_day': 3.0}}`

| Development year | Strategy return | Shanghai Composite price return | Active return | Completed trades |
|---:|---:|---:|---:|---:|
| 2020 | 16.8489% | 13.8667% | 2.9822% | 194 |
| 2021 | 12.3062% | 4.8001% | 7.5061% | 208 |
| 2022 | -12.8356% | -15.1251% | 2.2895% | 194 |
| 2023 | -0.3497% | -3.7009% | 3.3512% | 180 |
| 2024 | 18.3372% | 12.6669% | 5.6703% | 190 |
