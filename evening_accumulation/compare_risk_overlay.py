from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent


def metrics(frame: pd.DataFrame, start: str, end: str) -> dict:
    x = frame[pd.to_datetime(frame.date).between(start, end)].copy()
    if x.empty:
        return {}
    peak = x.equity.cummax()
    dd = x.equity / peak - 1.0
    years = max((pd.to_datetime(x.date.iloc[-1]) - pd.to_datetime(x.date.iloc[0])).days / 365.2425, 1 / 252)
    total = x.equity.iloc[-1] / x.equity.iloc[0] - 1.0
    return {
        "start": str(pd.to_datetime(x.date.iloc[0]).date()),
        "end": str(pd.to_datetime(x.date.iloc[-1]).date()),
        "start_equity": float(x.equity.iloc[0]), "end_equity": float(x.equity.iloc[-1]),
        "return": float(total), "annualized": float((1 + total) ** (1 / years) - 1),
        "max_drawdown": float(dd.min()),
    }


def turnover(folder: str, start: str, end: str, curve: pd.DataFrame) -> float:
    fills = pd.read_csv(ROOT / "outputs" / folder / "fills.csv", encoding="utf-8-sig")
    fills["date"] = pd.to_datetime(fills.date)
    selected = fills[fills.date.between(start, end)]
    nav = curve[pd.to_datetime(curve.date).between(start, end)].equity.mean()
    return float(selected.amount.abs().sum() / nav) if nav else 0.0


def main():
    folders = {"baseline": "live_realistic_daily", "risk_balanced": "risk_overlay_balanced",
               "risk_growth": "risk_overlay_growth"}
    periods = {
        "full": ("2020-01-01", "2026-07-31"),
        "validation_2025": ("2025-01-01", "2025-12-31"),
        "oos_2026": ("2026-01-01", "2026-07-31"),
        "drawdown_window": ("2026-04-16", "2026-07-30"),
        "extreme_july": ("2026-06-30", "2026-07-31"),
    }
    result = {}
    for name, folder in folders.items():
        curve = pd.read_csv(ROOT / "outputs" / folder / "equity.csv")
        result[name] = {key: metrics(curve, *period) for key, period in periods.items()}
        result[name]["full"]["gross_turnover"] = turnover(folder, *periods["full"], curve)
        if "risk_cap" in curve:
            curve.date = pd.to_datetime(curve.date)
            for key, period in periods.items():
                x = curve[curve.date.between(*period)]
                result[name][key]["mean_risk_cap"] = float(x.risk_cap.mean())
                result[name][key]["days_cap_50_or_less"] = int((x.risk_cap <= 0.50).sum())
    risk = pd.read_csv(ROOT / "outputs" / "risk_overlay_balanced" / "risk_features.csv")
    risk.date = pd.to_datetime(risk.date)
    threshold = json.loads((ROOT / "outputs/risk_overlay_balanced/summary.json").read_text())["risk_model"]["threshold"]
    test = risk[risk.date.between("2026-01-01", "2026-07-03")].dropna(subset=["future_20d_drawdown", "risk_probability"])
    actual = test.future_20d_drawdown <= -0.08
    predicted = test.risk_probability >= threshold
    result["oos_risk_detection"] = {
        "rows": int(len(test)), "actual_risk_days": int(actual.sum()),
        "recall": float((actual & predicted).sum() / actual.sum()) if actual.sum() else None,
        "precision": float((actual & predicted).sum() / predicted.sum()) if predicted.sum() else None,
        "warning_rate": float(predicted.mean()),
    }
    out = ROOT / "outputs" / "risk_overlay_balanced" / "comparison.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
