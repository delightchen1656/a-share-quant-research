"""Point-in-time opportunity-quality gates for Q3 residual reversal."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(HERE))
from m2_simple_baselines import metrics, ONE_WAY_COST  # noqa
from m4_residual_reversal import prepare  # noqa

OUT = STUDY / "reports" / "m5_opportunity_quality_gates"
DESIGN_END = pd.Timestamp("2023-12-31")


def quality_table(x):
    e = x[x.eligible].copy()
    rows = []
    for date, d in e.groupby("date", sort=True):
        residual = d.residual20.dropna()
        scores = d.Q3_trend_residual.dropna()
        rows.append({
            "date": date,
            "trend_breadth": (d.ret120 > 0).mean(),
            "market_ret20": d.ret20.median(),
            "residual_median": residual.median(),
            "residual_dispersion": residual.quantile(.8) - residual.quantile(.2),
            "candidate_share": scores.size / max(len(d), 1),
            "score_dispersion": scores.quantile(.9) - scores.quantile(.1) if len(scores) else np.nan,
        })
    q = pd.DataFrame(rows).set_index("date")
    design = q.loc[:DESIGN_END]
    cuts = {col: {p: design[col].quantile(p) for p in (.2, .35, .65, .8)} for col in q.columns}
    return q, cuts


def exposure_for(name, row, cuts):
    c = cuts
    if name == "G0_无门控": return 1.0
    if name == "G1_趋势广度下限": return 0.50 if row.trend_breadth < c["trend_breadth"][.2] else 1.0
    if name == "G2_市场普跌降仓": return 0.50 if row.market_ret20 < c["market_ret20"][.2] else 1.0
    if name == "G3_残差系统下沉": return 0.50 if row.residual_median < c["residual_median"][.2] else 1.0
    if name == "G4_残差离散不足": return 0.50 if row.residual_dispersion < c["residual_dispersion"][.2] else 1.0
    if name == "G5_候选覆盖不足": return 0.50 if row.candidate_share < c["candidate_share"][.2] else 1.0
    if name == "G6_评分区分不足": return 0.50 if row.score_dispersion < c["score_dispersion"][.2] else 1.0
    if name == "G7_普跌且低离散":
        bad = row.market_ret20 < c["market_ret20"][.35] and row.residual_dispersion < c["residual_dispersion"][.35]
        return 0.35 if bad else 1.0
    if name == "G8_双质量确认":
        good = row.trend_breadth >= c["trend_breadth"][.35] and row.residual_dispersion >= c["residual_dispersion"][.35]
        return 1.0 if good else 0.60
    if name == "G9_三级机会仓位":
        good = sum([row.trend_breadth >= c["trend_breadth"][.65],
                    row.residual_dispersion >= c["residual_dispersion"][.65],
                    row.score_dispersion >= c["score_dispersion"][.65]])
        return {0: .45, 1: .70, 2: .85, 3: 1.0}[good]
    raise KeyError(name)


def simulate(x, quality, cuts, gate, top_n=80, buffer_n=240, rebalance=40):
    z = x[x.date.between("2018-01-01", "2026-08-31")]
    dates = sorted(z.date.unique())
    days = {date: a.set_index("symbol") for date, a in z.groupby("date")}
    current = {}; pending = None; gross = net = 1.; rows = []
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
        if i % rebalance == rebalance - 1:
            ranked = d[d.Q3_trend_residual.notna()].sort_values("Q3_trend_residual", ascending=False)
            ranked_set = set(ranked.head(buffer_n).index)
            keep = [s for s in current if s in ranked_set]
            names = (keep + [s for s in ranked.index if s not in keep])[:top_n]
            exp = exposure_for(gate, quality.loc[date], cuts)
            pending = {s: exp / top_n for s in names}
    curve = pd.DataFrame(rows)
    curve["net_return"] = curve.net_nav.pct_change().fillna(0)
    return curve


def period_metrics(curve):
    periods = [("设计期2018-2023", "2018-01-01", "2023-12-31"),
               ("验证期2024", "2024-01-01", "2024-12-31"),
               ("验证期2025-2026-08", "2025-01-01", "2026-08-31"),
               ("全周期", "2018-01-01", "2026-08-31")]
    out = []
    for name, start, end in periods:
        z = curve[curve.date.between(start, end)].copy()
        z["gross_nav"] = (1 + z.gross_nav.pct_change().fillna(0)).cumprod()
        z["net_nav"] = (1 + z.net_nav.pct_change().fillna(0)).cumprod()
        m = metrics(z); m["period"] = name; out.append(m)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    x, _, _ = prepare(); quality, cuts = quality_table(x)
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(x.date.unique())))
    quality = quality.reindex(all_dates).ffill()
    gates = [f"G{i}_{n}" for i, n in enumerate(["无门控", "趋势广度下限", "市场普跌降仓", "残差系统下沉",
            "残差离散不足", "候选覆盖不足", "评分区分不足", "普跌且低离散", "双质量确认", "三级机会仓位"])]
    rows = []
    for gate in gates:
        print(gate, flush=True)
        c = simulate(x, quality, cuts, gate)
        c.to_parquet(OUT / f"{gate}_curve.parquet", index=False)
        for m in period_metrics(c):
            m["gate"] = gate; rows.append(m)
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    quality.reset_index().to_parquet(OUT / "quality_features.parquet", index=False)
    result.pivot(index="gate", columns="period", values=["annualized_return", "max_drawdown", "sharpe"]).to_csv(
        OUT / "comparison.csv", encoding="utf-8-sig")
    print(result[result.period == "全周期"].sort_values("annualized_return", ascending=False).to_string(index=False))
    print("\nPERIOD RETURNS")
    print(result.pivot(index="gate", columns="period", values="annualized_return").to_string())


if __name__ == "__main__":
    main()
