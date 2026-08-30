from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "comparison_2023_10m"


def period(curve, start, end):
    x = curve[pd.to_datetime(curve.date).between(start, end)].copy()
    peak = x.equity.cummax()
    total = x.equity.iloc[-1] / x.equity.iloc[0] - 1
    return {"start_asset": float(x.equity.iloc[0]), "end_asset": float(x.equity.iloc[-1]),
            "return": float(total), "max_drawdown": float((x.equity / peak - 1).min())}


def platform_curve():
    source = ROOT / "inputs/supermind_exports/run123_20260822/dailyposition3"
    raw = pd.read_csv(source, encoding="utf-8-sig")
    raw.columns = [str(c).strip() for c in raw.columns]
    nav = raw[raw["日期"].notna()][["日期", "总资产"]].copy()
    nav.columns = ["date", "equity"]
    nav.date = pd.to_datetime(nav.date)
    return nav.sort_values("date")


def main():
    curves = {
        "supermind_report3": platform_curve(),
        "local_baseline": pd.read_csv(ROOT / "outputs/comparison_2023_10m_baseline/equity.csv"),
        "local_risk": pd.read_csv(ROOT / "outputs/comparison_2023_10m_risk/equity.csv"),
        "local_v5": pd.read_csv(ROOT / "outputs/comparison_2023_10m_v5/equity.csv"),
    }
    periods = {"full": ("2022-12-30", "2026-07-31"),
               "oos_2026": ("2026-01-01", "2026-07-31"),
               "drawdown_window": ("2026-04-16", "2026-07-30"),
               "july": ("2026-06-30", "2026-07-31")}
    result = {name: {label: period(curve, *dates) for label, dates in periods.items()}
              for name, curve in curves.items()}
    for name, folder in (("local_baseline", "comparison_2023_10m_baseline"),
                         ("local_risk", "comparison_2023_10m_risk")):
        summary = json.loads((ROOT / "outputs" / folder / "summary.json").read_text(encoding="utf-8"))
        result[name]["summary"] = summary
    summary = json.loads((ROOT / "outputs/comparison_2023_10m_v5/summary.json").read_text(encoding="utf-8"))
    result["local_v5"]["summary"] = summary
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
