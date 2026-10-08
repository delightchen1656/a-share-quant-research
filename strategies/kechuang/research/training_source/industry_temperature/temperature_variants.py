from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import QFQ_DIR, load_panel


HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs" / "temperature_variants"
START, END = "2020-01-01", "2026-07-31"
NAMES = {
    "t01_cold_recovery": "低温复苏",
    "t02_warm_acceleration": "中温加速",
    "t03_breadth_diffusion": "宽度扩散",
    "t04_leader_follow": "龙头带动",
    "t05_volume_ignition": "量能点火",
    "t06_correlation_breakout": "联动突破",
    "t07_low_position_trend": "低位趋势确认",
    "t08_heat_persistence": "温度持续上升",
    "t09_state_machine": "温度状态机",
    "t10_ensemble_risk": "温度集成与风险配置",
}


def sigmoid(x: pd.DataFrame, scale: float) -> pd.DataFrame:
    return 100 / (1 + np.exp(-x.clip(-5 * scale, 5 * scale) / scale))


def build_temperature(prices: pd.DataFrame, amount: pd.DataFrame, industries: pd.Series):
    ret = prices.pct_change(fill_method=None)
    listing = prices.notna().cumsum()
    eligible = (listing >= 120) & (amount.rolling(20, min_periods=20).mean() >= 50_000_000)
    groups = sorted(x for x in industries.dropna().unique() if (industries == x).sum() >= 4)
    gr, breadth, volratio, linkage, leader = {}, {}, {}, {}, {}
    for industry in groups:
        members = list(industries[industries == industry].index.intersection(prices.columns))
        mask = eligible[members]
        rr = ret[members].where(mask)
        gr[industry] = rr.mean(axis=1)
        ma60 = prices[members].rolling(60, min_periods=40).mean()
        breadth[industry] = (prices[members] > ma60).where(mask).mean(axis=1)
        a20 = amount[members].rolling(20, min_periods=10).mean().where(mask).sum(axis=1)
        a60 = amount[members].rolling(60, min_periods=30).mean().where(mask).sum(axis=1)
        volratio[industry] = (a20 / a60.replace(0, np.nan)).clip(0, 3)
        group_r = rr.mean(axis=1)
        dispersion = rr.sub(group_r, axis=0).pow(2).mean(axis=1).pow(.5).rolling(20).mean()
        group_vol = group_r.rolling(20).std()
        linkage[industry] = (1 - dispersion / (dispersion + group_vol)).clip(0, 1)
        leader[industry] = ret[members].rolling(21).apply(lambda x: np.prod(1 + x) - 1, raw=True).where(mask).max(axis=1)
    gr = pd.DataFrame(gr).fillna(0)
    breadth, volratio, linkage, leader = map(pd.DataFrame, (breadth, volratio, linkage, leader))
    index = (1 + gr).cumprod()
    low, high = index.rolling(252, min_periods=120).min(), index.rolling(252, min_periods=120).max()
    position = ((index - low) / (high - low).replace(0, np.nan) * 100).clip(0, 100)
    mom21 = index / index.shift(21) - 1
    mom63 = index / index.shift(63) - 1
    trend = sigmoid(mom63, .12)
    breadth_score = breadth * 100
    volume_score = sigmoid(volratio - 1, .30)
    linkage_score = linkage * 100
    leader_score = sigmoid(leader, .15)
    heat = (.20 * position + .25 * trend + .20 * breadth_score + .12 * volume_score +
            .10 * linkage_score + .13 * leader_score).clip(0, 100)
    return {"ret": ret, "eligible": eligible, "group_ret": gr, "index": index, "position": position,
            "mom21": mom21, "mom63": mom63, "trend": trend, "breadth": breadth_score,
            "volume": volume_score, "linkage": linkage_score, "leader": leader_score,
            "heat": heat, "delta": heat - heat.shift(10)}, groups


def select_groups(name: str, date: pd.Timestamp, f: dict[str, pd.DataFrame], market_ok: bool,
                  prior: list[str]) -> tuple[list[str], pd.Series]:
    x = pd.DataFrame({k: f[k].loc[date] for k in ["heat", "delta", "position", "mom21", "mom63",
                                                           "breadth", "volume", "linkage", "leader"]}).dropna().astype(float)
    if x.empty:
        return [], pd.Series(dtype=float)
    if name == "t01_cold_recovery":
        ok = x.heat.between(25, 55) & (x.delta > 3) & (x.mom21 > 0)
        score = x.delta + x.mom21 * 100
    elif name == "t02_warm_acceleration":
        ok = x.heat.between(45, 78) & (x.delta > 2) & (x.mom63 > 0)
        score = x.heat + x.delta
    elif name == "t03_breadth_diffusion":
        ok = (x.breadth > 62) & (x.delta > 0) & (x.heat < 85)
        score = x.breadth + x.delta
    elif name == "t04_leader_follow":
        ok = (x.leader > 65) & (x.breadth > 48) & (x.mom21 > 0)
        score = x.leader + .5 * x.breadth
    elif name == "t05_volume_ignition":
        ok = (x.volume > 62) & (x.delta > 2) & (x.mom21 > 0) & (x.heat < 85)
        score = x.volume + x.delta
    elif name == "t06_correlation_breakout":
        ok = (x.linkage > 50) & (x.breadth > 58) & (x.mom21 > 0)
        score = x.linkage + x.breadth + x.mom21 * 50
    elif name == "t07_low_position_trend":
        ok = (x.position < 60) & (x.mom63 > 0) & (x.delta > 0)
        score = (100 - x.position) + x.mom63 * 100
    elif name == "t08_heat_persistence":
        d20 = f["heat"].loc[date] - f["heat"].shift(20).loc[date]
        ok = x.heat.between(50, 82) & (x.delta > 0) & (d20 > 4)
        score = x.heat + x.delta + d20
    elif name == "t09_state_machine":
        keep = x.index.isin(prior) & (x.heat > 38) & ~((x.heat > 88) & (x.delta < 0))
        enter = x.heat.between(40, 72) & (x.delta > 3) & (x.mom63 > 0)
        ok = keep | enter
        score = x.heat + x.delta + x.mom63 * 50
    else:
        ok = (x.heat.between(42, 82) & (x.delta > 0) & (x.mom63 > 0) &
              (x.breadth > 52) & (x.linkage > 35))
        score = (.30 * x.heat + .20 * x.delta + .20 * x.breadth + .10 * x.linkage +
                 .10 * x.volume + .10 * x.leader)
    if name in {"t02_warm_acceleration", "t03_breadth_diffusion", "t04_leader_follow",
                "t06_correlation_breakout", "t08_heat_persistence", "t10_ensemble_risk"} and not market_ok:
        ok[:] = False
    n = 2 if name in {"t04_leader_follow", "t05_volume_ignition"} else 3
    score = pd.to_numeric(score, errors="coerce")
    chosen = list(score[ok].dropna().nlargest(n).index)
    if not chosen:
        return [], pd.Series(dtype=float)
    if name == "t10_ensemble_risk":
        vols = f["group_ret"].loc[:date, chosen].tail(60).std().clip(lower=.005)
        weights = (1 / vols) / (1 / vols).sum()
    else:
        weights = pd.Series(1 / len(chosen), index=chosen)
    return chosen, weights


def pick_stocks(name: str, date: pd.Timestamp, industry: str, iw: float, industries: pd.Series,
                prices: pd.DataFrame, amount: pd.DataFrame, f: dict[str, pd.DataFrame]) -> pd.Series:
    members = list(industries[industries == industry].index.intersection(prices.columns))
    valid = f["eligible"].loc[date, members]
    p = prices.loc[:date, members]
    r = f["ret"].loc[:date, members]
    mom21 = p.iloc[-1] / p.shift(21).iloc[-1] - 1
    mom63 = p.iloc[-1] / p.shift(63).iloc[-1] - 1
    mom126 = p.iloc[-1] / p.shift(126).iloc[-1] - 1
    vol60 = r.tail(60).std() * math.sqrt(252)
    rel = mom63 - float(f["mom63"].loc[date, industry])
    score = .35 * mom21.rank(pct=True) + .35 * mom63.rank(pct=True) + .15 * mom126.rank(pct=True) + .15 * (-vol60).rank(pct=True)
    if name == "t04_leader_follow":
        score = .55 * mom21.rank(pct=True) + .30 * mom63.rank(pct=True) + .15 * (-vol60).rank(pct=True)
    elif name in {"t03_breadth_diffusion", "t06_correlation_breakout"}:
        score = .45 * rel.rank(pct=True) + .30 * mom21.rank(pct=True) + .25 * (-vol60).rank(pct=True)
    chosen = list(score[valid & score.notna()].nlargest(4).index)
    if not chosen:
        return pd.Series(dtype=float)
    if name == "t10_ensemble_risk":
        inv = 1 / vol60[chosen].clip(lower=.15)
        return inv / inv.sum() * iw
    return pd.Series(iw / len(chosen), index=chosen)


def main():
    prices = load_panel(QFQ_DIR, "close", END)
    amount = load_panel(QFQ_DIR, "amount", END)
    mapping = pd.read_csv(HERE / "industry_map.csv")
    industries = mapping.set_index("symbol").industry.reindex(prices.columns)
    f, groups = build_temperature(prices, amount, industries)
    dates = prices.index[(prices.index >= START) & (prices.index <= END)]
    check_dates = set(dates[::10])
    market_ret = f["ret"].where(f["eligible"]).mean(axis=1).fillna(0)
    market_idx = (1 + market_ret).cumprod()
    market_ok_series = (market_idx > market_idx.rolling(120, min_periods=60).mean()) & ((market_idx / market_idx.shift(63) - 1) > -.05)
    curves, summaries, selections = {}, [], []
    for name in NAMES:
        nav, current = 1.0, pd.Series(dtype=float)
        prior_groups, turnover_sum, rows = [], 0.0, []
        for i, date in enumerate(dates):
            if i and len(current):
                nav *= 1 + float((current * f["ret"].loc[date, current.index].fillna(0)).sum())
            if date in check_dates and date >= pd.Timestamp("2020-07-01"):
                chosen, iw = select_groups(name, date, f, bool(market_ok_series.loc[date]), prior_groups)
                pieces = [pick_stocks(name, date, g, float(iw.loc[g]), industries, prices, amount, f) for g in chosen]
                new = pd.concat(pieces).groupby(level=0).sum() if pieces else pd.Series(dtype=float)
                union = current.index.union(new.index)
                turnover = float((current.reindex(union, fill_value=0) - new.reindex(union, fill_value=0)).abs().sum())
                nav *= max(0, 1 - turnover * .00155)
                turnover_sum += turnover
                current, prior_groups = new, chosen
                selections.append([date, name, "|".join(chosen), len(new), float(new.sum()), turnover])
            rows.append([date, nav, float(current.sum()), len(current)])
        curve = pd.DataFrame(rows, columns=["date", "nav", "exposure", "holdings"]).set_index("date")
        curves[name] = curve.nav
        years = (curve.index[-1] - curve.index[0]).days / 365.25
        dd = curve.nav / curve.nav.cummax() - 1
        rr = curve.nav.pct_change().fillna(0)
        summaries.append({"variant": name, "description": NAMES[name], "total_return": curve.nav.iloc[-1] - 1,
                          "cagr": curve.nav.iloc[-1] ** (1 / years) - 1, "max_drawdown": dd.min(),
                          "sharpe": rr.mean() / rr.std() * math.sqrt(252) if rr.std() else 0,
                          "turnover": turnover_sum, "avg_exposure": curve.exposure.mean(), "avg_holdings": curve.holdings.mean()})
    benchmark = (1 + market_ret.loc[dates]).cumprod()
    curves["star_equal_weight"] = benchmark
    OUT.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(summaries).sort_values(["cagr", "sharpe"], ascending=False)
    summary.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(curves).to_csv(OUT / "equity.csv", encoding="utf-8-sig")
    pd.DataFrame(selections, columns=["date", "variant", "industries", "holdings", "exposure", "turnover"]).to_csv(OUT / "selections.csv", index=False, encoding="utf-8-sig")
    heat_long = f["heat"].loc[dates].stack().rename("temperature").reset_index()
    heat_long.columns = ["date", "industry", "temperature"]
    heat_long.to_parquet(OUT / "daily_temperature.parquet", index=False)
    meta = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "mapped": int(industries.notna().sum()),
            "industries": len(groups), "benchmark_return": float(benchmark.iloc[-1] - 1),
            "challenge_cagr": .465, "challenge_drawdown": -.2896}
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False)); print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
