"""Incrementally extend the frozen STAR universe through 2026-08-21."""
from __future__ import annotations

import time
from pathlib import Path

import baostock as bs
import pandas as pd

from src.data import _download_symbol


ROOT = Path(__file__).resolve().parent
START = "2026-01-01"
END = "2026-08-21"


def merge_atomic(target: Path, fresh: pd.DataFrame) -> None:
    old = pd.read_parquet(target)
    fresh_start = fresh["date"].min()
    merged = pd.concat([old[old["date"] < fresh_start], fresh], ignore_index=True)
    merged = merged.drop_duplicates(["date", "symbol"], keep="last").sort_values("date")
    temporary = target.with_suffix(".parquet.updating")
    merged.to_parquet(temporary, index=False)
    temporary.replace(target)


def main() -> None:
    raw_dir = ROOT / "data" / "classified" / "SH" / "star" / "raw"
    qfq_dir = ROOT / "data" / "classified" / "SH" / "star" / "qfq"
    symbols = sorted(p.stem for p in raw_dir.glob("688*.SH.parquet"))
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    failures: list[tuple[str, str]] = []
    started = time.monotonic()
    try:
        for index, symbol in enumerate(symbols, 1):
            code = "sh." + symbol[:6]
            try:
                raw = _download_symbol(code, START, END, "3")
                qfq = _download_symbol(code, START, END, "2")
                if raw.empty or qfq.empty:
                    raise RuntimeError("empty response")
                merge_atomic(raw_dir / f"{symbol}.parquet", raw)
                merge_atomic(qfq_dir / f"{symbol}.parquet", qfq)
                status = "UPDATED"
            except Exception as exc:
                failures.append((symbol, str(exc)))
                status = "FAILED"
            elapsed = max(time.monotonic() - started, 0.001)
            rate = index / elapsed * 3600
            eta = (len(symbols) - index) / rate if rate else 0
            print(
                f"[{index:3d}/{len(symbols)}] {index/len(symbols):6.2%} "
                f"[{status:7s}] {symbol}  {rate:,.0f}只/小时  剩余{eta:.2f}小时  "
                f"失败{len(failures)}",
                flush=True,
            )
    finally:
        bs.logout()
    if failures:
        raise RuntimeError(f"更新失败 {len(failures)} 只: {failures[:5]}")


if __name__ == "__main__":
    main()
