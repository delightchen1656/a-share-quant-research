"""Fetch the explicitly identified Shanghai Composite price index for Batch 006."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import akshare as ak
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "沪深智能1" / "results" / "batch_006_pre2025_active_objectives" / "inputs"
DATA = OUT / "sh000001_eastmoney_pre2025.parquet"
META = OUT / "sh000001_eastmoney_pre2025.metadata.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = ak.stock_zh_index_daily_em(
        symbol="sh000001", start_date="20190101", end_date="20241231"
    )
    if frame.empty:
        raise RuntimeError("Empty Shanghai Composite response")
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    required = {"date", "open", "close", "high", "low", "volume", "amount"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"Unexpected index columns: {frame.columns.tolist()}")
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    frame = frame[frame.date <= pd.Timestamp("2024-12-31")].copy()
    if frame.date.min() > pd.Timestamp("2019-01-02") or frame.date.max() < pd.Timestamp("2024-12-31"):
        raise RuntimeError("Insufficient pre-2025 Shanghai Composite coverage")
    frame.to_parquet(DATA, index=False)
    metadata = {
        "instrument_name": "上证综合指数（价格指数）",
        "instrument_code": "000001.SH",
        "provider_request_symbol": "sh000001",
        "provider": "Eastmoney via AkShare stock_zh_index_daily_em",
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "requested_start": "2019-01-01",
        "requested_end": "2024-12-31",
        "actual_start": str(frame.date.min().date()),
        "actual_end": str(frame.date.max().date()),
        "rows": int(len(frame)),
        "columns": frame.columns.tolist(),
        "data_sha256": sha256(DATA),
        "boundary": "pre2025 only",
        "return_type": "close-to-close price return; dividends are not included",
    }
    META.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
