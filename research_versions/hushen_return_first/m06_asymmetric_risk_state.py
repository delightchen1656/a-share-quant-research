"""Decouple Q3 stock selection cadence from point-in-time risk review cadence."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(HERE))
from m2_simple_baselines import metrics, ONE_WAY_COST  # noqa
from m4_residual_reversal import prepare  # noqa
from m5_opportunity_quality_gates import quality_table  # noqa

OUT = STUDY / "reports" / "m6_asymmetric_risk_state"


def desired_exposure(mode, danger, previous, safe_count):
    if danger:
        return .35, 0
    safe_count += 1
    if mode == "binary":
        return 1.0, safe_count
    if mode == "staged_fast":
        return (0.70 if safe_count == 1 else 1.0), safe_count
    if mode == "staged_slow":
        return ({1: .55, 2: .75}.get(safe_count, 1.0)), safe_count
    if mode == "hysteresis":
        # One safe observation restores most capital; two restore all.
        return (0.80 if safe_count == 1 else 1.0), safe_count
    raise KeyError(mode)


def simulate(x, quality, cuts, review_days, mode, select_days=40, top_n=80, buffer_n=240):
    z = x[x.date.between("2018-01-01", "2026-08-31")]
    dates = sorted(pd.to_datetime(z.date.unique()))
    days = {date: a.set_index("symbol") for date, a in z.groupby("date")}
    current = {}; selected = []; pending = None; exposure = 1.; safe_count = 99
    gross = net = 1.; rows = []
    for i, date in enumerate(dates):
        d = days[date]
        r = sum(w * float(d.at[s, "ret1"]) for s, w in current.items()
                if s in d.index and np.isfinite(d.at[s, "ret1"]))
        gross *= 1 + r; net *= 1 + r; turnover = 0
        if pending is not None:
            target = {s: w for s, w in pending.items() if s in d.index and bool(d.at[s, "tradable"])
                      and not bool(d.at[s, "one_price_up"])}
            for s, w in current.items():
                blocked = s in d.index and (not bool(d.at[s, "tradable"]) or bool(d.at[s, "one_price_down"]))
                if s not in target and blocked:
                    target[s] = w
            if sum(target.values()) > 1:
                target = {s: w / sum(target.values()) for s, w in target.items()}
            turnover = sum(abs(target.get(s, 0) - current.get(s, 0)) for s in set(target) | set(current))
            net *= max(0, 1 - turnover * ONE_WAY_COST); current = target; pending = None
        rows.append({"date": date, "gross_nav": gross, "net_nav": net, "turnover": turnover,
                     "exposure": sum(current.values()), "positions": len(current)})

        selection_due = i % select_days == select_days - 1
        review_due = i % review_days == review_days - 1
        if selection_due:
            ranked = d[d.Q3_trend_residual.notna()].sort_values("Q3_trend_residual", ascending=False)
            ranked_set = set(ranked.head(buffer_n).index)
            keep = [s for s in selected if s in ranked_set]
            selected = (keep + [s for s in ranked.index if s not in keep])[:top_n]
        if review_due:
            q = quality.loc[date]
            danger = (q.market_ret20 < cuts["market_ret20"][.35]
                      and q.residual_dispersion < cuts["residual_dispersion"][.35])
            exposure, safe_count = desired_exposure(mode, bool(danger), exposure, safe_count)
        if selection_due or review_due:
            pending = {s: exposure / top_n for s in selected}
    c = pd.DataFrame(rows); c["net_return"] = c.net_nav.pct_change().fillna(0)
    return c


def report_periods(curve):
    periods = [("设计期2018-2023", "2018-01-01", "2023-12-31"),
               ("验证期2024", "2024-01-01", "2024-12-31"),
               ("验证期2025-2026-08", "2025-01-01", "2026-08-31"),
               ("全周期", "2018-01-01", "2026-08-31")]
    result = []
    for period, start, end in periods:
        z = curve[curve.date.between(start, end)].copy()
        z["gross_nav"] = (1 + z.gross_nav.pct_change().fillna(0)).cumprod()
        z["net_nav"] = (1 + z.net_nav.pct_change().fillna(0)).cumprod()
        m = metrics(z); m["period"] = period; result.append(m)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    x, _, _ = prepare(); quality, cuts = quality_table(x)
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(x.date.unique())))
    quality = quality.reindex(all_dates).ffill()
    configs = [("M0_40日二元", 40, "binary"), ("M1_20日二元", 20, "binary"),
               ("M2_10日二元", 10, "binary"), ("M3_5日二元", 5, "binary"),
               ("M4_20日快速恢复", 20, "staged_fast"), ("M5_10日快速恢复", 10, "staged_fast"),
               ("M6_5日快速恢复", 5, "staged_fast"), ("M7_10日缓慢恢复", 10, "staged_slow"),
               ("M8_10日迟滞恢复", 10, "hysteresis")]
    rows = []
    for name, review, mode in configs:
        print(name, flush=True)
        c = simulate(x, quality, cuts, review, mode)
        c.to_parquet(OUT / f"{name}_curve.parquet", index=False)
        for m in report_periods(c):
            m.update({"strategy": name, "review_days": review, "recovery": mode}); rows.append(m)
    result = pd.DataFrame(rows); result.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    result.pivot(index="strategy", columns="period", values=["annualized_return", "max_drawdown", "sharpe"]).to_csv(
        OUT / "comparison.csv", encoding="utf-8-sig")
    print(result[result.period == "全周期"].sort_values("annualized_return", ascending=False).to_string(index=False))
    print("\nPERIOD RETURNS\n", result.pivot(index="strategy", columns="period", values="annualized_return").to_string())


if __name__ == "__main__": main()
