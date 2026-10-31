# Dynamic model-health layer (pre-2025 isolated development)

This directory is an isolated development product. It reads only the verified `inputs_pre2025` snapshot and never trains either frozen model.

The two candidate structures and every threshold are declared in `engine.py` before evaluation. Data from 2020-2022 is the construction report, 2023 alone selects one structure, and 2024 is run once as a second-stage confirmation after the candidate configuration is frozen. The 2024 result remains development data and must not be described as post-boundary evidence.

Health at each signal close uses only event signals whose full twenty-session horizon has matured and trades already completed by that close. Orders execute at the next open. The dynamic layer changes only event-probability admission, stop-risk admission, position fraction, maximum concurrent positions and post-exit cooldown. The 7% stop, half sale at +15%, remaining sale at +30%, and twenty-session time exit are invariant.

An independent audit supplies a module defining `load_panels(start_date, end_date) -> (raw, qfq)` and runs `frozen_candidate/validate_frozen.py`. The entry point requests data from the frozen feature-warmup start through the audit end, then starts portfolio and health replay at the separately frozen history start. This reproduces features, matured-signal, completed-trade and open-position state causally. Returned data is not bundled into or learned by the candidate.

The first complete run exposed 2024 before a methodological bug was found: health state had been reset at each reporting-year boundary. A later frozen-entry smoke test also found that the adapter contract omitted feature warmup before the health-history start. Superseded artifacts are retained for audit. Neither correction changed either predefined candidate structure or any threshold. The corrected 2024 result remains development data and is not post-boundary evidence.
