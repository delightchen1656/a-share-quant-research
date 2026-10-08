"""Local A-share reproduction of RiskParity-Momentum-ETF at sector level.

The source project rotates listed ETFs.  Our local main-board database does not
contain a point-in-time ETF universe, so this implementation constructs twelve
tradable, point-in-time style/industry-proxy groups from trailing stock features.
At each rebalance it applies the public structure: low correlation -> momentum
resonance -> overheat rejection -> inverse-volatility allocation -> risk gates.

Signals use T-close data.  Targets are applied on T+1 subject to tradability and
one-price limit checks.  A conservative 30 bp one-way turnover cost is charged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
EXPERIMENTS = PROJECT / "studies" / "return_first_research" / "experiments"
sys.path.insert(0, str(EXPERIMENTS))
from m2_simple_baselines import ONE_WAY_COST, load_features, metrics  # noqa: E402

OUT = HERE / "outputs"
START = pd.Timestamp("2020-01-02")
END = pd.Timestamp("2026-07-31")
REBALANCE_DAYS = 20
N_CLUSTERS = 12
N_LOW_CORR = 5
N_GROUPS = 3
STOCKS_PER_GROUP = 10
TRAIL_DD = -0.10
TRAIL_RECOVERY = 0.04
DEFENSIVE_EXPOSURE = 0.25
RANDOM_STATE = 20260914


def slope_r2_score(series: pd.Series, window: int = 20) -> float:
    y = np.log1p(series.dropna().clip(lower=-0.95)).cumsum().tail(window).to_numpy()
    if len(y) < window:
        return np.nan
    t = np.arange(len(y), dtype=float)
    slope = np.polyfit(t, y, 1)[0]
    fitted = slope * t + (y.mean() - slope * t.mean())
    denom = ((y - y.mean()) ** 2).sum()
    r2 = 0.0 if denom <= 1e-12 else 1 - ((y - fitted) ** 2).sum() / denom
    annual = np.expm1(slope * 252)
    return float(annual * max(0.0, r2))


def make_target(history: pd.DataFrame, today: pd.DataFrame) -> tuple[dict[str, float], dict]:
    q = today[today.eligible].dropna(subset=["ret20", "ret60", "ret120", "vol60", "amount20"]).copy()
    if len(q) < 300:
        return {}, {"reason": "too_few_eligible"}

    # Clusters are rebuilt only from information available at the signal close.
    q["log_amount"] = np.log(q.amount20.clip(lower=1))
    feats = ["ret20", "ret60", "ret120", "vol60", "log_amount"]
    z = (q[feats] - q[feats].median()) / q[feats].std().replace(0, 1)
    z = z.replace([np.inf, -np.inf], np.nan).dropna()
    q = q.loc[z.index].copy()
    q["cluster"] = KMeans(n_clusters=N_CLUSTERS, n_init=10, random_state=RANDOM_STATE).fit_predict(z)

    lookback = history[history.symbol.isin(q.symbol)].merge(q[["symbol", "cluster"]], on="symbol", how="inner")
    group_ret = lookback.pivot_table(index="date", columns="cluster", values="ret1", aggfunc="median").tail(500)
    valid = [c for c in group_ret if group_ret[c].count() >= 120]
    if len(valid) < N_GROUPS:
        return {}, {"reason": "too_few_groups"}
    corr = group_ret[valid].tail(250).corr().abs()
    mean_corr = (corr.sum() - 1) / (corr.count() - 1).clip(lower=1)
    low_corr = list(mean_corr.nsmallest(min(N_LOW_CORR, len(mean_corr))).index)

    group_stats = []
    for c in low_corr:
        s = group_ret[c]
        mom = slope_r2_score(s, 20)
        vol = float(s.tail(60).std() * np.sqrt(252))
        nav20 = (1 + s.tail(20).fillna(0)).cumprod()
        bias20 = float(nav20.iloc[-1] / nav20.mean() - 1) if len(nav20) else np.nan
        group_stats.append((c, mom, vol, bias20, float(mean_corr[c])))
    gs = pd.DataFrame(group_stats, columns=["cluster", "momentum", "vol", "bias20", "mean_abs_corr"])
    # Public strategy rejects overheated candidates.  A 12% synthetic-index bias
    # is deliberately broad to avoid tuning this reproduction to our sample.
    gs = gs[(gs.momentum > 0) & (gs.bias20 < 0.12)].sort_values("momentum", ascending=False).head(N_GROUPS)
    if gs.empty:
        return {}, {"reason": "no_positive_non_overheated_group"}

    inv = 1 / gs.vol.clip(lower=0.05)
    group_weights = dict(zip(gs.cluster.astype(int), (inv / inv.sum()).astype(float)))
    target: dict[str, float] = {}
    selected = []
    for cluster, group_weight in group_weights.items():
        members = q[q.cluster == cluster].copy()
        members = members[(members.ret60 > 0) & (members.ret20 < 0.30)]
        members["stock_score"] = (
            0.45 * members.ret60.rank(pct=True)
            + 0.25 * members.ret20.rank(pct=True)
            + 0.20 * (1 - members.vol60.rank(pct=True))
            + 0.10 * members.amount20.rank(pct=True)
        )
        members = members.nlargest(STOCKS_PER_GROUP, "stock_score")
        if members.empty:
            continue
        stock_inv = 1 / members.vol60.clip(lower=0.004)
        stock_w = stock_inv / stock_inv.sum() * group_weight
        for symbol, weight in zip(members.symbol, stock_w):
            target[str(symbol)] = float(weight)
        selected.append({"cluster": int(cluster), "weight": float(group_weight),
                         "momentum": float(gs.loc[gs.cluster == cluster, "momentum"].iloc[0]),
                         "members": int(len(members))})
    total = sum(target.values())
    if total > 0:
        target = {s: w / total for s, w in target.items()}
    return target, {"reason": "risk_on", "groups": selected}


def run() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    x = load_features().sort_values(["date", "symbol"])
    x = x[x.date.between("2018-01-01", END)]
    dates = sorted(d for d in x.date.unique() if d >= START)
    all_days = {d: a for d, a in x.groupby("date", sort=False)}
    sim_days = {d: all_days[d].set_index("symbol") for d in dates}
    full_dates = sorted(all_days)
    date_pos = {d: i for i, d in enumerate(full_dates)}
    schedule = set(dates[REBALANCE_DAYS - 1::REBALANCE_DAYS])

    current: dict[str, float] = {}
    pending = None
    gross = net = 1.0
    peak = 1.0
    trailing = False
    rows, decisions = [], []
    for date in dates:
        d = sim_days[date]
        port_ret = sum(w * float(d.at[s, "ret1"]) for s, w in current.items()
                       if s in d.index and np.isfinite(d.at[s, "ret1"]))
        gross *= 1 + port_ret
        net *= 1 + port_ret
        turnover = 0.0
        if pending is not None:
            target = {s: w for s, w in pending.items() if s in d.index and bool(d.at[s, "tradable"])
                      and not bool(d.at[s, "one_price_up"])}
            for s, w in current.items():
                if s not in target and (s not in d.index or not bool(d.at[s, "tradable"])
                                        or bool(d.at[s, "one_price_down"])):
                    target[s] = w
            total = sum(target.values())
            if total > 1:
                target = {s: w / total for s, w in target.items()}
            turnover = sum(abs(target.get(s, 0) - current.get(s, 0)) for s in set(target) | set(current))
            net *= max(0.0, 1 - turnover * ONE_WAY_COST)
            current, pending = target, None

        peak = max(peak, net)
        dd = net / peak - 1
        if dd <= TRAIL_DD:
            trailing = True
        elif trailing and net / peak - 1 >= TRAIL_DD + TRAIL_RECOVERY:
            trailing = False
        rows.append({"date": date, "gross_nav": gross, "net_nav": net, "turnover": turnover,
                     "exposure": sum(current.values()), "positions": len(current),
                     "drawdown": dd, "trailing_gate": trailing})

        if date in schedule:
            pos = date_pos[date]
            hist_dates = full_dates[max(0, pos - 520):pos + 1]
            hist = pd.concat([all_days[h][["date", "symbol", "ret1"]] for h in hist_dates], ignore_index=True)
            raw_target, detail = make_target(hist, all_days[date])
            # Market breadth gate and trailing drawdown gate replace the source
            # project's defensive ETF basket, which is outside this stock pool.
            eligible = all_days[date][all_days[date].eligible]
            breadth = float((eligible.ret60 > 0).mean()) if len(eligible) else 0.0
            exposure = DEFENSIVE_EXPOSURE if trailing or breadth < 0.35 else 1.0
            pending = {s: w * exposure for s, w in raw_target.items()}
            decisions.append({"date": date, "breadth60": breadth, "target_exposure": exposure,
                              "target_positions": len(pending), "detail": json.dumps(detail, ensure_ascii=False)})

    curve = pd.DataFrame(rows)
    curve["net_return"] = curve.net_nav.pct_change().fillna(0)
    result = metrics(curve)
    result.update({"start": str(curve.date.iloc[0].date()), "end": str(curve.date.iloc[-1].date()),
                   "one_way_cost": ONE_WAY_COST, "rebalance_days": REBALANCE_DAYS,
                   "n_clusters": N_CLUSTERS})
    return curve, pd.DataFrame(decisions), result


def period_metrics(curve: pd.DataFrame) -> pd.DataFrame:
    periods = [("2020-2023开发观察", "2020-01-02", "2023-12-31"),
               ("2024验证观察", "2024-01-01", "2024-12-31"),
               ("2025-2026-07锁定观察", "2025-01-01", "2026-07-31"),
               ("2020-2026-07全期", "2020-01-02", "2026-07-31")]
    out = []
    for name, start, end in periods:
        z = curve[curve.date.between(start, end)].copy()
        if z.empty:
            continue
        z["gross_nav"] = (1 + z.gross_nav.pct_change().fillna(0)).cumprod()
        z["net_nav"] = (1 + z.net_nav.pct_change().fillna(0)).cumprod()
        z["net_return"] = z.net_nav.pct_change().fillna(0)
        m = metrics(z)
        m["period"] = name
        out.append(m)
    return pd.DataFrame(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    curve, decisions, result = run()
    periods = period_metrics(curve)
    curve.to_parquet(OUT / "daily_curve.parquet", index=False)
    decisions.to_csv(OUT / "rebalance_decisions.csv", index=False, encoding="utf-8-sig")
    periods.to_csv(OUT / "period_metrics.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(periods.to_string(index=False))


if __name__ == "__main__":
    main()
