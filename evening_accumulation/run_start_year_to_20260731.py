"""Compare Baseline1 and Baseline2 from each yearly start through 2026-07-31."""
from pathlib import Path

import pandas as pd

from research_baseline2 import END, INITIAL_CASH, OUT, prepare, simulate


def main() -> None:
    prep, _ = prepare()
    rows = []
    for year in range(2020, 2027):
        start = pd.Timestamp(f"{year}-01-01")
        for variant, modes in (
            ("baseline1", set()),
            ("baseline2", {"stop_risk_filter"}),
        ):
            summary, _, _ = simulate(prep, modes, start=start, end=END, initial_cash=INITIAL_CASH)
            rows.append({
                "start_year": year,
                "start": summary["start"],
                "end": summary["end"],
                "variant": variant,
                "initial_cash": summary["initial_cash"],
                "final_equity": summary["final_equity"],
                "total_return": summary["total_return"],
                "annualized_return": summary["annualized_return"],
                "max_drawdown": summary["max_drawdown"],
                "closed_trades": summary["closed_trades"],
                "win_rate": summary["win_rate"],
            })
    result = pd.DataFrame(rows)
    target = OUT / "start_year_to_20260731.csv"
    result.to_csv(target, index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))
    print(target)


if __name__ == "__main__":
    main()
