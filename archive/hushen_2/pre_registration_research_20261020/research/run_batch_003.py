from __future__ import annotations

import gc
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_002 as batch2  # noqa: E402


ROOT = core.ROOT
PROJECT = core.PROJECT
RESULTS = PROJECT / "results" / "batch_003"
PROTOCOL = PROJECT / "protocol" / "BATCH_003.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank_center(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame.groupby("date", sort=False)[columns].rank(pct=True, method="average") - 0.5


def build_component_panel() -> pd.DataFrame:
    """Build M/T/H on the already frozen pre-2025 Smart-1 eligible panel."""
    model = batch2.build_model_panel().copy()
    technical = core.build_feature_panel()[
        ["date", "symbol", "overnight20", "intraday20", "vol60", "turn20"]
    ].copy()
    panel = model.merge(technical, on=["date", "symbol"], how="inner", validate="one_to_one", suffixes=("", "_tech"))
    if panel.empty or panel.date.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Component panel is empty or crosses the registered boundary")

    # f_log_amount is log1p(amount); f_turn is the point-in-time turnover rate.
    # Their difference is monotone with amount/turn and therefore serves as the
    # Hushen-1 capitalization proxy inside this different eligible universe.
    panel["cap_proxy_log"] = panel["f_log_amount"] - np.log(panel["f_turn"].clip(lower=1e-6))
    h_rank = rank_center(panel, ["cap_proxy_log", "vol60_tech", "overnight20", "intraday20"])
    panel["H_raw"] = (
        -0.35 * h_rank.cap_proxy_log
        -0.20 * h_rank.vol60_tech
        +0.25 * h_rank.overnight20
        -0.20 * h_rank.intraday20
    )
    panel = panel.sort_values(["symbol", "date"])
    panel["H_smooth"] = panel.groupby("symbol", sort=False).H_raw.transform(
        lambda x: x.rolling(5, min_periods=3).mean()
    )
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

    import lightgbm as lgb

    predictions = {}
    for name in ["utility", "pen025", "pen100"]:
        booster = lgb.Booster(model_file=str(batch2.MODEL_DIR / f"{name}.txt"))
        if booster.feature_name() != batch2.MODEL_FEATURES:
            raise RuntimeError(f"Feature mismatch for {name}")
        predictions[name] = booster.predict(panel[batch2.MODEL_FEATURES], num_threads=4)
    for name, values in predictions.items():
        panel[name] = values
    panel["M_raw"] = panel[["utility", "pen025", "pen100"]].mean(axis=1)

    base_rank = rank_center(panel, ["mom120", "close_to_high60", "mom20", "vol60", "M_raw", "H_smooth"])
    panel["T_raw"] = (
        0.35 * base_rank.mom120
        + 0.25 * base_rank.close_to_high60
        + 0.20 * base_rank.mom20
        - 0.20 * base_rank.vol60
    )
    component_rank = rank_center(panel.assign(T_raw=panel.T_raw), ["M_raw", "T_raw", "H_smooth"])
    panel["M"] = component_rank.M_raw
    panel["T"] = component_rank.T_raw
    panel["H"] = component_rank.H_smooth
    return panel[["date", "symbol", "close", "atr_pct", "M", "T", "H"]].dropna().copy()


def weight_grid(step: float = 0.25) -> list[tuple[float, float, float]]:
    units = int(round(1.0 / step))
    return [(i / units, j / units, (units - i - j) / units) for i in range(units + 1) for j in range(units + 1 - i)]


def make_factor_signals(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, dict]]:
    chunks = []
    formulas = {}
    for wm, wt, wh in weight_grid():
        base = f"M{int(wm*100):03d}_T{int(wt*100):03d}_H{int(wh*100):03d}"
        scored = panel[["date", "symbol", "close", "atr_pct"]].copy()
        scored["score"] = wm * panel["M"] + wt * panel["T"] + wh * panel["H"]
        scored = scored.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")
        for topk in [1, 2, 3]:
            name = f"{base}_K{topk}"
            selected = scored.groupby("date", sort=False).head(topk).copy()
            selected["factor"] = name
            chunks.append(selected)
            formulas[name] = {"M": wm, "T": wt, "H": wh, "daily_top_k": topk}
    signals = pd.concat(chunks, ignore_index=True)
    signals = signals.sort_values(["date", "factor", "score", "symbol"], ascending=[True, True, False, True])
    RESULTS.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(RESULTS / "signals_factor_grid.parquet", index=False)
    (RESULTS / "factor_formulas.json").write_text(json.dumps(formulas, ensure_ascii=False, indent=2), encoding="utf-8")
    return signals, formulas


def eligible_row(row: dict) -> dict:
    row["eligible_trade_count"] = bool(row["eligible"])
    row["eligible"] = bool(row["eligible"] and row["profitable_years"] >= 3)
    return row


def ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["eligible", "cagr", "worst_annual_return", "profitable_years", "annual_return_std", "trade_count_cv", "candidate"],
        ascending=[False, False, False, False, True, True, True],
    ).reset_index(drop=True)


def run_one(signals, bars, calendar, factor, entry, hold, take, stop, phase):
    exit_name = f"take{take:.2f}_stop{stop:.2f}"
    row, _ = core.simulate(signals, bars, calendar, factor, entry, hold, exit_name, take, stop)
    row["phase"] = phase
    return eligible_row(row)


def cross_time_metrics(row: pd.Series) -> dict:
    values = [float(row[f"return_{y}"]) for y in [2022, 2023, 2024]]
    growth = math.prod(1.0 + x for x in values)
    return {
        "cross_time_cumulative_2022_2024": growth - 1.0,
        "cross_time_cagr_2022_2024": growth ** (1.0 / 3.0) - 1.0,
        "cross_time_profitable_years": sum(x > 0 for x in values),
    }


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["total_screening_runs"] != 174 or not protocol["post_2024_forbidden"]:
        raise RuntimeError("Batch 003 protocol mismatch")
    panel = build_component_panel()
    signals, formulas = make_factor_signals(panel)
    del panel
    gc.collect()
    bars, calendar = core.load_execution_bars(set(signals.symbol), force=False)
    defaults = {
        7: {"entry": 0.25, "take": 2.0, "stop": 1.25},
        30: {"entry": 0.25, "take": 2.5, "stop": 1.5},
    }
    all_rows = []
    winners = {}
    completed = 0
    total = protocol["total_screening_runs"]
    for hold in [7, 30]:
        d = defaults[hold]
        phase1 = []
        for factor in sorted(formulas):
            row = run_one(signals, bars, calendar, factor, d["entry"], hold, d["take"], d["stop"], "factor_blend_and_daily_count")
            phase1.append(row); all_rows.append(row); completed += 1
            print(f"batch3 {completed}/{total} hold={hold} phase=factor {factor} cagr={row['cagr']:.4%}", flush=True)
        p1 = ordered(pd.DataFrame(phase1)); p1.to_csv(RESULTS / f"phase1_factor_{hold}cal.csv", index=False, encoding="utf-8-sig")
        factor = str(p1.iloc[0].factor)

        phase2 = []
        for entry in np.arange(0.0, 1.5001, 0.25):
            row = run_one(signals, bars, calendar, factor, float(entry), hold, d["take"], d["stop"], "entry_offset")
            phase2.append(row); all_rows.append(row); completed += 1
            print(f"batch3 {completed}/{total} hold={hold} phase=entry entry={entry:.2f} cagr={row['cagr']:.4%}", flush=True)
        p2 = ordered(pd.DataFrame(phase2)); p2.to_csv(RESULTS / f"phase2_entry_{hold}cal.csv", index=False, encoding="utf-8-sig")
        entry = float(p2.iloc[0].entry_offset_atr)

        phase3 = []
        for take in np.arange(1.0, 4.0001, 0.5):
            for stop in np.arange(0.5, 2.5001, 0.5):
                row = run_one(signals, bars, calendar, factor, entry, hold, float(take), float(stop), "exit_width")
                phase3.append(row); all_rows.append(row); completed += 1
                print(f"batch3 {completed}/{total} hold={hold} phase=exit take={take:.2f} stop={stop:.2f} cagr={row['cagr']:.4%}", flush=True)
        p3 = ordered(pd.DataFrame(phase3)); p3.to_csv(RESULTS / f"phase3_exit_{hold}cal.csv", index=False, encoding="utf-8-sig")
        winner = p3.iloc[0].to_dict()
        winner.update(cross_time_metrics(p3.iloc[0]))
        winner["formula"] = formulas[factor]
        winners[f"{hold}cal"] = winner

    if completed != total:
        raise RuntimeError(f"Expected {total} runs, got {completed}")
    grid = pd.DataFrame(all_rows)
    grid.to_csv(RESULTS / "all_sequential_runs.csv", index=False, encoding="utf-8-sig")
    output = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": digest(PROTOCOL),
        "runner_sha256": digest(Path(__file__)),
        "completed_screening_runs": completed,
        "selection_method": "sequential fixed-grid development; separate 7cal and 30cal winners",
        "winners": winners,
        "fit_period_note": "Frozen M models were trained on 2018-2021; 2020-2021 account results overlap fitting.",
        "cross_time_period": "2022-2024",
        "post_2024_access": False,
        "production_change": False,
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
