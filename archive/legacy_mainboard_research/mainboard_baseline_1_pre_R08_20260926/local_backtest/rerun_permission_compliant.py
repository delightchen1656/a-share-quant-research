"""沪深基准1 V2：普通A股权限白名单复核回测。"""
from pathlib import Path
import json

import pandas as pd

import supermind_aligned_backtest as bt


OUT = Path(__file__).resolve().parent / "outputs" / "permission_compliant_v2_20200102_20260911"
OLD_CURVES = (Path(__file__).resolve().parent / "outputs" /
              "return_optimization_round_4_micro30" / "daily_curves.parquet")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    factors = bt.build_factor_cache()
    ranks = bt.ranked_months(factors, (.25, .20, .55), (.50, .25, .25), 120)
    curve, trades = bt.simulate(ranks, bt.ACTIVE_VOLUME_LIMIT, 20, 40, 1.0, 1.5)
    result = bt.metrics(curve, bt.INITIAL_CASH)

    forbidden = ~trades.symbol.map(bt.is_ordinary_mainboard_a) if len(trades) else pd.Series(dtype=bool)
    result["universe_count"] = len(bt.load_universe())
    result["forbidden_trade_rows"] = int(forbidden.sum()) if len(forbidden) else 0

    comparison = None
    if OLD_CURVES.exists():
        old = pd.read_parquet(OLD_CURVES)
        old = old[old.name == "v2_reference"].copy()
        old_result = bt.metrics(old, bt.INITIAL_CASH)
        comparison = {
            "old_final_equity": old_result["final_equity"],
            "new_final_equity": result["final_equity"],
            "final_equity_change": result["final_equity"] - old_result["final_equity"],
            "old_annualized_return": old_result["annualized_return"],
            "new_annualized_return": result["annualized_return"],
            "old_max_drawdown": old_result["max_drawdown"],
            "new_max_drawdown": result["max_drawdown"],
        }

    curve.to_csv(OUT / "daily_equity.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(OUT / "trades.csv", index=False, encoding="utf-8-sig")
    payload = {"metrics": result, "comparison_with_pre_filter_v2": comparison}
    (OUT / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
