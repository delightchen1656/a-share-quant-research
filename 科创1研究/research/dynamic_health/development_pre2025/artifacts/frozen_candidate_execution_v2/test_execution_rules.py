from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from engine import (
    BASE_RULES,
    STAR_BUY_SHARE_UNIT,
    STAR_MIN_BUY_SHARES,
    _affordable_buy_shares,
    _base_execution_eligible,
    simulate,
)


def scheme(position_fraction: float = 0.20) -> dict:
    state = {
        "event_add": 0.0,
        "stop_risk_cap": 1.0,
        "position_fraction": position_fraction,
        "max_positions": 1,
        "cooldown_sessions": 0,
    }
    return {
        "health": {
            "min_matured": 12,
            "event_window": 30,
            "trade_window": 8,
            "stress_event_rate": 0.15,
            "healthy_event_rate": 0.25,
            "stress_trade_mean": -0.02,
            "healthy_trade_mean": 0.0,
        },
        "states": {"healthy": state.copy(), "caution": state.copy(), "stressed": state.copy()},
    }


def panel(overrides: dict[int, dict] | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=10)
    rows = []
    for i, date in enumerate(dates):
        row = {
            "date": date,
            "symbol": "688001.SH",
            "open": 10.0,
            "high": 10.2,
            "low": 9.8,
            "close": 10.0,
            "preclose": 10.0,
            "volume": 10000,
            "amount": 100000.0,
            "tradestatus": "1",
        }
        row.update((overrides or {}).get(i, {}))
        rows.append(row)
    return pd.DataFrame(rows)


def signals(*indices: int) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=10)
    return pd.DataFrame(
        {
            "date": [dates[i] for i in indices],
            "symbol": ["688001.SH"] * len(indices),
            "event_probability": [0.9] * len(indices),
            "stop_risk_probability": [0.1] * len(indices),
            "maturity_date": [pd.NaT] * len(indices),
            "event_hit": [float("nan")] * len(indices),
        }
    )


def run(raw: pd.DataFrame, scored: pd.DataFrame, custom_scheme: dict | None = None):
    dates = pd.bdate_range("2024-01-02", periods=10)
    return simulate(raw, scored, 0.5, custom_scheme or scheme(), str(dates[5].date()), str(dates[9].date()))


def main() -> None:
    checks: dict[str, bool] = {}

    entry = 10.0 * (1 + BASE_RULES["slippage_each_side"])
    shares, paid = _affordable_buy_shares(2500.0, 2500.0, entry)
    checks["integer_shares"] = isinstance(shares, int)
    checks["star_minimum_and_unit"] = shares >= STAR_MIN_BUY_SHARES and shares % STAR_BUY_SHARE_UNIT == 0
    checks["all_in_cost_within_cash"] = paid <= 2500.0 and 2500.0 - paid >= -1e-8
    too_small, _ = _affordable_buy_shares(1999.0, 1999.0, 10.0)
    checks["subminimum_buy_rejected"] = too_small == 0

    # Signal on session 6, buy on session 7.  A stop on the buy date must wait
    # until session 8 because A shares are T+1.
    raw = panel({6: {"low": 8.0}, 7: {"low": 8.0}})
    equity, trades, _ = run(raw, signals(5))
    checks["t_plus_one"] = len(trades) == 1 and pd.Timestamp(trades.iloc[0].exit_date) > pd.Timestamp(trades.iloc[0].entry_date)
    checks["simulated_shares_are_integer"] = len(trades) == 1 and int(trades.iloc[0].initial_shares) == trades.iloc[0].initial_shares
    checks["cash_never_negative"] = bool((equity.cash >= -1e-8).all())

    # Session 7 opens exactly at the rounded 20% upper limit: no purchase.
    upper = panel({6: {"open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0}})
    upper_equity, upper_trades, _ = run(upper, signals(5))
    checks["open_limit_up_buy_blocked"] = upper_trades.empty and int(upper_equity.positions.max()) == 0

    # Buy on session 7.  Session 8 opens at the lower limit and cannot sell;
    # the still-open stop executes on session 9.
    lower = panel({7: {"open": 8.0, "high": 8.0, "low": 8.0, "close": 8.0}, 8: {"low": 8.0}})
    _, lower_trades, _ = run(lower, signals(5))
    dates = pd.bdate_range("2024-01-02", periods=10)
    checks["open_limit_down_sell_blocked"] = len(lower_trades) == 1 and pd.Timestamp(lower_trades.iloc[0].exit_date) == dates[8]

    halted_row = panel({6: {"tradestatus": "0"}}).iloc[6]
    zero_volume_row = panel({6: {"volume": 0, "amount": 0.0}}).iloc[6]
    checks["suspension_blocked"] = not _base_execution_eligible(halted_row)
    checks["zero_volume_blocked"] = not _base_execution_eligible(zero_volume_row)

    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"execution checks failed: {failed}")
    result = {"status": "passed", "checks": {name: bool(passed) for name, passed in checks.items()}}
    out = Path(__file__).resolve().parent / "execution_rule_tests.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
