"""Capital-scale comparison from each yearly start through 2026-07-31."""
import argparse
import gc
import pandas as pd

from research_baseline2 import END, OUT, prepare, simulate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", type=float, required=True)
    args = parser.parse_args()
    prep, _ = prepare()
    rows = []
    initial_cash = args.capital
    for year in range(2020, 2027):
        start = pd.Timestamp(f"{year}-01-01")
        for variant, modes in (
            ("baseline1", set()),
            ("baseline2", {"stop_risk_filter"}),
        ):
            summary, curve, trades = simulate(
                prep, modes, start=start, end=END, initial_cash=initial_cash
            )
            rows.append({
                    "initial_cash": initial_cash,
                    "start_year": year,
                    "end": summary["end"],
                    "variant": variant,
                    "final_equity": summary["final_equity"],
                    "total_return": summary["total_return"],
                    "annualized_return": summary["annualized_return"],
                    "max_drawdown": summary["max_drawdown"],
                    "closed_trades": summary["closed_trades"],
                    "win_rate": summary["win_rate"],
            })
            del curve, trades
            gc.collect()
    result = pd.DataFrame(rows)
    label = "10w" if initial_cash == 100_000 else "1000w"
    target = OUT / f"capital_{label}_start_year_to_20260731.csv"
    result.to_csv(target, index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))
    print(target)


if __name__ == "__main__":
    main()
