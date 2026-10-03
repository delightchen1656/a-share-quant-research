"""Ten walk-forward research variants around STAR related-group rotation.

This is a fast, adjusted-price research screen. It uses monthly rebalancing,
point-in-time liquidity/listing filters and explicit turnover costs. The winner
must subsequently pass the detailed raw-price execution engine.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

from backtest import QFQ_DIR, load_panel


OUT = Path(__file__).resolve().parent / "outputs" / "variants"
START, END = "2020-01-01", "2026-07-31"
VARIANTS = {
    "v01_low_recovery": "低位转强：区间分位较低、短期动量转正",
    "v02_industry_momentum": "行业动量：过去6个月最强关联组",
    "v03_dual_momentum": "双重动量：绝对趋势与相对市场趋势同时为正",
    "v04_residual_momentum": "残差动量：选择显著跑赢科创板等权基准的组",
    "v05_low_vol_trend": "低波趋势：正趋势组中优先低波动",
    "v06_vol_scaled_momentum": "波动调整动量：按收益/波动排序",
    "v07_breadth_confirmation": "宽度确认：多数成分股站上中期均线",
    "v08_drawdown_recovery": "回撤修复：中度回撤后出现短期反转",
    "v09_multi_factor_ensemble": "多因子集成：动量、低位、宽度、低波综合",
    "v10_risk_parity_groups": "组间风险平价：正趋势组按逆波动配置",
}


def balanced_groups(ret: pd.DataFrame, eligible: list[str], k: int = 10) -> pd.Series:
    x = ret[eligible].tail(252)
    names = list(x.notna().sum()[lambda s: s >= 160].index)
    if len(names) < k * 2:
        return pd.Series(dtype=int)
    corr = x[names].corr(min_periods=80).fillna(0).clip(-1, 1)
    z = PCA(n_components=min(8, len(names) - 1), random_state=42).fit_transform(corr.values)
    labels = KMeans(n_clusters=k, random_state=42, n_init=20).fit_predict(z) + 1
    return pd.Series(labels, index=names)


def zrank(s: pd.Series, ascending: bool = True) -> pd.Series:
    return s.rank(pct=True, ascending=ascending).fillna(0.5)


def group_table(date: pd.Timestamp, prices: pd.DataFrame, ret: pd.DataFrame,
                labels: pd.Series, market_ret: pd.Series) -> tuple[pd.DataFrame, dict[int, list[str]]]:
    rows, members_by_group = [], {}
    market126 = (1 + market_ret.loc[:date].tail(126)).prod() - 1
    market63 = (1 + market_ret.loc[:date].tail(63)).prod() - 1
    for label in sorted(labels.unique()):
        members = list(labels[labels == label].index)
        if len(members) < 4:
            continue
        members_by_group[int(label)] = members
        rr = ret.loc[:date, members].mean(axis=1).fillna(0)
        idx = (1 + rr.tail(520)).cumprod()
        if len(idx) < 180:
            continue
        mom = {n: (1 + rr.tail(n)).prod() - 1 for n in [21, 63, 126, 252]}
        vol = rr.tail(60).std() * math.sqrt(252)
        peak = idx.cummax()
        dd = idx.iloc[-1] / peak.iloc[-1] - 1
        percentile = (idx.iloc[-1] - idx.min()) / max(idx.max() - idx.min(), 1e-12)
        pp = prices.loc[:date, members]
        breadth = float((pp.iloc[-1] > pp.tail(120).mean()).mean())
        rows.append([label, len(members), percentile, mom[21], mom[63], mom[126], mom[252],
                     vol, dd, breadth, mom[126] - market126, market63, market126])
    cols = ["group", "members", "percentile", "mom21", "mom63", "mom126", "mom252",
            "vol60", "drawdown", "breadth", "residual126", "market63", "market126"]
    return pd.DataFrame(rows, columns=cols).set_index("group"), members_by_group


def choose_groups(name: str, g: pd.DataFrame) -> tuple[list[int], pd.Series]:
    if g.empty:
        return [], pd.Series(dtype=float)
    score = pd.Series(-np.inf, index=g.index, dtype=float)
    if name == "v01_low_recovery":
        ok = (g.percentile < .65) & (g.mom63 > 0)
        score[ok] = .5 * (1 - g.percentile[ok]) + .5 * zrank(g.mom63[ok])
    elif name == "v02_industry_momentum":
        ok = g.mom126 > 0
        score[ok] = g.mom126[ok]
    elif name == "v03_dual_momentum":
        ok = (g.mom126 > 0) & (g.residual126 > 0) & (g.mom21 > -.05) & (g.market126 > 0)
        score[ok] = g.mom126[ok] + g.residual126[ok]
    elif name == "v04_residual_momentum":
        ok = (g.residual126 > 0) & (g.mom63 > 0)
        score[ok] = g.residual126[ok]
    elif name == "v05_low_vol_trend":
        ok = (g.mom126 > 0) & (g.mom21 > -.05) & (g.market63 > 0)
        score[ok] = -g.vol60[ok]
    elif name == "v06_vol_scaled_momentum":
        ok = g.mom126 > 0
        score[ok] = g.mom126[ok] / g.vol60[ok].clip(lower=.05)
    elif name == "v07_breadth_confirmation":
        ok = (g.breadth >= .60) & (g.mom63 > 0) & (g.market63 > 0)
        score[ok] = g.breadth[ok] + g.mom63[ok]
    elif name == "v08_drawdown_recovery":
        ok = g.drawdown.between(-.45, -.08) & (g.mom21 > 0) & (g.mom63 > -.10)
        score[ok] = g.mom21[ok] - abs(g.drawdown[ok] + .20)
    elif name == "v09_multi_factor_ensemble":
        ok = (g.mom63 > 0) & (g.mom126 > 0) & (g.market126 > 0)
        score[ok] = (zrank(g.mom126[ok]) + zrank(g.breadth[ok]) +
                     zrank(-g.vol60[ok]) + zrank(-g.percentile[ok])) / 4
    else:
        ok = (g.mom126 > 0) & (g.mom21 > -.08) & (g.market126 > 0)
        score[ok] = 1 / g.vol60[ok].clip(lower=.05)
    n = 4 if name == "v10_risk_parity_groups" else 3
    chosen = list(score.replace(-np.inf, np.nan).dropna().nlargest(n).index)
    weights = score.loc[chosen].copy()
    if name == "v10_risk_parity_groups" and chosen:
        weights = 1 / g.loc[chosen, "vol60"].clip(lower=.05)
    elif chosen:
        weights[:] = 1
    return chosen, weights / weights.sum() if len(weights) else weights


def stock_weights(name: str, date: pd.Timestamp, members: list[str], prices: pd.DataFrame,
                  amount: pd.DataFrame, group_weight: float) -> pd.Series:
    p = prices.loc[:date, members]
    r = p.pct_change(fill_method=None)
    mom63 = p.iloc[-1] / p.shift(63).iloc[-1] - 1
    mom126 = p.iloc[-1] / p.shift(126).iloc[-1] - 1
    vol = r.tail(60).std() * math.sqrt(252)
    liq = amount.loc[:date, members].tail(20).mean()
    valid = (liq >= 50_000_000) & mom126.notna() & vol.notna()
    if name in {"v05_low_vol_trend", "v10_risk_parity_groups"}:
        score = -vol
    elif name == "v08_drawdown_recovery":
        score = mom63 - .25 * vol
    elif name == "v09_multi_factor_ensemble":
        score = zrank(mom126) + zrank(-vol) + zrank(np.log(liq.clip(lower=1)))
    else:
        score = mom126 - .25 * vol
    chosen = list(score[valid].nlargest(4).index)
    if not chosen:
        return pd.Series(dtype=float)
    if name in {"v05_low_vol_trend", "v10_risk_parity_groups"}:
        w = 1 / vol[chosen].clip(lower=.10)
        return w / w.sum() * group_weight
    return pd.Series(group_weight / len(chosen), index=chosen)


def main() -> None:
    prices = load_panel(QFQ_DIR, "close", END)
    amount = load_panel(QFQ_DIR, "amount", END)
    ret = prices.pct_change(fill_method=None)
    listing = prices.notna().cumsum()
    liquid = amount.rolling(20, min_periods=20).mean() >= 50_000_000
    eligible_mask = (listing >= 120) & liquid
    market_ret = ret.where(eligible_mask).mean(axis=1).fillna(0)
    dates = prices.index[(prices.index >= START) & (prices.index <= END)]
    rebals = list(pd.Series(dates, index=dates).groupby(dates.to_period("M")).first())
    target_history: dict[str, dict[pd.Timestamp, pd.Series]] = {v: {} for v in VARIANTS}
    group_audit = []
    for date in rebals:
        if prices.index.get_loc(date) < 260:
            continue
        eligible = list(eligible_mask.loc[date][eligible_mask.loc[date]].index)
        labels = balanced_groups(ret.loc[:date], eligible)
        g, members = group_table(date, prices, ret, labels, market_ret)
        if not g.empty:
            group_audit.append([date, len(g), int(g.members.min()), int(g.members.max()), len(labels)])
        for name in VARIANTS:
            chosen, gw = choose_groups(name, g)
            pieces = [stock_weights(name, date, members[x], prices, amount, float(gw.loc[x])) for x in chosen]
            target_history[name][date] = pd.concat(pieces).groupby(level=0).sum() if pieces else pd.Series(dtype=float)

    OUT.mkdir(parents=True, exist_ok=True)
    summaries, curves = [], {}
    for name, targets in target_history.items():
        nav, current = 1.0, pd.Series(dtype=float)
        rows, turnover_sum = [], 0.0
        for i, date in enumerate(dates):
            if i:
                daily = ret.loc[date, current.index].fillna(0) if len(current) else pd.Series(dtype=float)
                nav *= 1 + float((current * daily).sum())
            if date in targets:
                new = targets[date]
                union = current.index.union(new.index)
                turnover = float((current.reindex(union, fill_value=0) - new.reindex(union, fill_value=0)).abs().sum())
                # Approximate one-way all-in cost: 10bp slippage + commission,
                # transfer fee and average sell tax contribution.
                nav *= max(0, 1 - turnover * 0.00155)
                turnover_sum += turnover
                current = new
            rows.append([date, nav, float(current.sum()), len(current)])
        curve = pd.DataFrame(rows, columns=["date", "nav", "exposure", "holdings"]).set_index("date")
        curves[name] = curve.nav
        years = (curve.index[-1] - curve.index[0]).days / 365.25
        dd = curve.nav / curve.nav.cummax() - 1
        rr = curve.nav.pct_change().fillna(0)
        summaries.append({"variant": name, "description": VARIANTS[name], "total_return": curve.nav.iloc[-1] - 1,
                          "cagr": curve.nav.iloc[-1] ** (1 / years) - 1, "max_drawdown": dd.min(),
                          "sharpe": rr.mean() / rr.std() * math.sqrt(252) if rr.std() else 0,
                          "turnover": turnover_sum, "avg_exposure": curve.exposure.mean(),
                          "avg_holdings": curve.holdings.mean()})
    benchmark = (1 + market_ret.loc[dates]).cumprod()
    curves["star_equal_weight"] = benchmark
    summary = pd.DataFrame(summaries).sort_values(["sharpe", "cagr"], ascending=False)
    summary.to_csv(OUT / "variants_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(curves).to_csv(OUT / "variant_equity.csv", encoding="utf-8-sig")
    pd.DataFrame(group_audit, columns=["date", "groups", "min_size", "max_size", "stocks"]).to_csv(OUT / "group_audit.csv", index=False)
    meta = {"start": str(dates[0].date()), "end": str(dates[-1].date()), "variants": VARIANTS,
            "benchmark_return": float(benchmark.iloc[-1] - 1),
            "benchmark_max_drawdown": float((benchmark / benchmark.cummax() - 1).min())}
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
