"""Validate Strategy2 versus Strategy3 bear-probability + downside-diversification candidate."""
import pandas as pd

from research_strategy3 import END, INITIAL_CASH, OUT, prepare, simulate


VERSIONS = {
    "strategy2": set(),
    "strategy3_candidate": {"bear_probability", "downside_diversify"},
}


def row_from(summary, variant, period):
    return {
        "variant": variant, "period": period, "initial_cash": INITIAL_CASH,
        "final_equity": summary["final_equity"], "total_return": summary["total_return"],
        "annualized_return": summary["annualized_return"],
        "max_drawdown": summary["max_drawdown"], "closed_trades": summary["closed_trades"],
        "win_rate": summary["win_rate"],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prep, _ = prepare()
    yearly, starts = [], []
    for year in range(2020, 2027):
        year_end = pd.Timestamp(f"{year}-12-31") if year < 2026 else END
        for variant, modes in VERSIONS.items():
            result, _, _ = simulate(prep, modes, pd.Timestamp(f"{year}-01-01"), year_end)
            yearly.append(row_from(result, variant, str(year)))
            result, _, _ = simulate(prep, modes, pd.Timestamp(f"{year}-01-01"), END)
            starts.append(row_from(result, variant, str(year)))
    pd.DataFrame(yearly).to_csv(OUT / "independent_yearly.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(starts).to_csv(OUT / "start_year_to_20260731.csv", index=False, encoding="utf-8-sig")
    print(pd.DataFrame(starts).to_string(index=False))


if __name__ == "__main__":
    main()
