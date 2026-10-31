"""Development-only adapter used to smoke-test the frozen validation entry point."""
from pathlib import Path

import pandas as pd


INPUTS = Path(__file__).resolve().parent.parent / "inputs_pre2025"


def load_panels(start_date: str, end_date: str):
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    def read(name: str):
        frames = [pd.read_parquet(p) for p in sorted((INPUTS / name).glob("*.parquet"))]
        x = pd.concat(frames, ignore_index=True)
        x["date"] = pd.to_datetime(x.date)
        return x[(x.date >= start) & (x.date <= end)].copy()
    return read("raw"), read("qfq")
