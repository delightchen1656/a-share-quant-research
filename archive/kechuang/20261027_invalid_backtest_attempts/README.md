# Invalid intermediate replays

These two runs are retained only as audit evidence and must not be reported as
Kechuang Baseline 1 results.

- `invalid_live_qfq`: recalculated all historical signals from the latest
  forward-adjusted files, so later ex-rights rebasing changed frozen history.
- `invalid_non_point_in_time`: preserved frozen history but calculated all
  October signals from one later snapshot instead of each day's committed
  point-in-time data state.

The accepted result is
`strategies/kechuang/results/q1_yearly_continuous_to_20261026/`.
