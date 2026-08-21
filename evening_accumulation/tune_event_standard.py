"""Coordinate tuning around event-standard with the user-defined weighted score."""
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, portfolio_backtest

ROOT = Path(__file__).resolve().parent
HOLD60 = "--hold60" in sys.argv
CENTERS = {"threshold": .739688, "stop_loss": .06, "take_profit_half": .20,
           "take_profit_all": .30, "max_holding_days": 60 if HOLD60 else 30}
STEPS = {"threshold": .01, "stop_loss": .005, "take_profit_half": .01,
         "take_profit_all": .01, "max_holding_days": 3}
PARAMS = list(CENTERS) if not HOLD60 else ["threshold", "stop_loss", "take_profit_half", "take_profit_all"]


def grid(name, center):
    step = STEPS[name]
    values = [center + i * step for i in range(-5, 6)]
    if name == "max_holding_days": return sorted(set(int(round(x)) for x in values if x >= 5))
    return sorted(set(round(x, 6) for x in values if x > 0))


def main():
    cfg0 = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs" / "event_recognition_v2" / "event_model.joblib")
    ds = features(qfq, cfg0); ds = ds[eligible(ds, cfg0)].dropna(subset=FEATURES)
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    cache = {}; evaluations = []

    def evaluate(params):
        key = tuple(params[x] for x in PARAMS)
        if key in cache: return cache[key]
        if params["take_profit_half"] >= params["take_profit_all"]: return None
        cfg = dict(cfg0); cfg.update({k: params[k] for k in PARAMS if k != "threshold"})
        trial = Trial("tune", params["threshold"], 15, .04, 300, 3, 8, 14)
        annual = {}
        for year in range(2020, 2025):
            stats, _, _ = portfolio_backtest(raw, ds, cfg, trial, None, f"{year}-01-01", f"{year}-12-31")
            annual[str(year)] = float(stats.get("annualized_return", 0.)) if stats else 0.
        recent, _, _ = portfolio_backtest(raw, ds, cfg, trial, None, "2025-01-01", "2026-07-31")
        recent_ann = float(recent.get("annualized_return", 0.)) if recent else 0.
        score = .1 * sum(annual.values()) + .5 * recent_ann
        row = {**params, **{"ann_" + k: v for k, v in annual.items()},
               "ann_2025_202607": recent_ann, "composite_score": score,
               "recent_total_return": recent.get("total_return", 0.) if recent else 0.,
               "recent_max_drawdown": recent.get("max_drawdown", 0.) if recent else 0.,
               "recent_trades": recent.get("trades", 0) if recent else 0.}
        cache[key] = row; evaluations.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    current = dict(CENTERS); baseline = evaluate(current); trace = [{"pass": 0, "parameter": "baseline", **baseline}]
    # Strict one-way coordinate pass: optimize one parameter, freeze it, then move on.
    for pass_no in (1,):
        changed = False
        for name in PARAMS:
            candidates = []
            # Every pass stays inside the original user-requested center +/- five steps.
            for value in grid(name, CENTERS[name]):
                candidate = dict(current); candidate[name] = value
                result = evaluate(candidate)
                if result is not None: candidates.append(result)
            best = max(candidates, key=lambda r: r["composite_score"])
            old = current[name]
            for key in PARAMS:
                current[key] = best[key]
            changed |= current[name] != old
            trace.append({"pass": pass_no, "parameter": name, **best})
            print("BEST", pass_no, name, current[name], best["composite_score"], flush=True)
        if not changed: break
    final = evaluate(current)
    out_name = "event_standard_tuning_60d" if HOLD60 else "event_standard_tuning"
    out = ROOT / "outputs" / out_name; out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(evaluations).sort_values("composite_score", ascending=False).to_csv(
        out / "all_evaluations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(trace).to_csv(out / "coordinate_trace.csv", index=False, encoding="utf-8-sig")
    (out / "best.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FINAL\n" + json.dumps(final, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
