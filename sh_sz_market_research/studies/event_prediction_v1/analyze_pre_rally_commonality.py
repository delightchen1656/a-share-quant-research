"""Compare features before independent rallies with matched non-event dates."""
from __future__ import annotations

from pathlib import Path
import zlib

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
FEATURE_DIR = PROJECT / "data_pipeline" / "data" / "derived" / "features"
EVENT_FILE = PROJECT / "studies" / "rapid_rally_10d50" / "outputs" / "event_details.csv"
OUT = HERE / "outputs"
FEATURES = [
    "ret5", "ret20", "ret60", "range20", "range60", "dd20", "vol20", "vol60",
    "volume_ratio", "volume_cv", "up_volume_share", "pv_corr", "close_pos60", "turn20",
    "amount20", "breakout_gap", "rise_from_low60", "volume_spike",
]
START, END = pd.Timestamp("2018-01-01"), pd.Timestamp("2023-12-31")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(EVENT_FILE, parse_dates=["start_date", "end_date"])
    events = events[(events.start_date >= START) & (events.end_date <= END)]
    event_map = events.groupby("symbol").start_date.apply(set).to_dict()
    rows = []
    for n, path in enumerate(FEATURE_DIR.rglob("*.parquet"), 1):
        symbol = path.stem
        starts = event_map.get(symbol)
        if not starts:
            continue
        x = pd.read_parquet(path, columns=["date", "symbol"] + FEATURES)
        x["date"] = pd.to_datetime(x.date)
        x = x.sort_values("date").reset_index(drop=True)
        # Previous close is the last fully known bar before the event low day.
        anchors = x.index[x.date.isin(starts)] - 1
        anchors = anchors[anchors >= 60]
        positive_dates = set(x.loc[anchors, "date"])
        valid = x.index[(x.date >= START) & (x.date <= END) & x[FEATURES].notna().all(axis=1)]
        blocked = set()
        for idx in anchors:
            blocked.update(range(max(0, idx - 15), min(len(x), idx + 16)))
            r = x.loc[idx, ["date", "symbol"] + FEATURES].to_dict()
            r["label"] = 1
            rows.append(r)
        controls = [i for i in valid if i not in blocked and x.at[i, "date"] not in positive_dates]
        want = min(len(controls), len(anchors) * 3)
        if want:
            seed = zlib.crc32(symbol.encode()) & 0xFFFFFFFF
            rng = np.random.default_rng(seed)
            for idx in rng.choice(controls, size=want, replace=False):
                r = x.loc[idx, ["date", "symbol"] + FEATURES].to_dict()
                r["label"] = 0
                rows.append(r)
        if n % 500 == 0:
            print(f"[{n}]", flush=True)

    sample = pd.DataFrame(rows)
    sample.to_parquet(OUT / "pre_rally_matched_sample.parquet", index=False)
    stats = []
    for f in FEATURES:
        p = sample.loc[sample.label.eq(1), f].astype(float)
        c = sample.loc[sample.label.eq(0), f].astype(float)
        pooled = np.sqrt((p.var(ddof=1) + c.var(ddof=1)) / 2)
        stats.append({"feature": f, "positive_mean": p.mean(), "control_mean": c.mean(),
                      "standardized_difference": (p.mean() - c.mean()) / pooled if pooled else np.nan,
                      "positive_median": p.median(), "control_median": c.median()})
    result = pd.DataFrame(stats)
    result["abs_standardized_difference"] = result.standardized_difference.abs()
    result = result.sort_values("abs_standardized_difference", ascending=False)
    result.to_csv(OUT / "pre_rally_commonality.csv", index=False, encoding="utf-8-sig")
    print(f"samples={len(sample):,}, positives={int(sample.label.sum()):,}")
    print(result.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
