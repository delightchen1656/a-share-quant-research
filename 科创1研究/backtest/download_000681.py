"""Download and validate the STAR Market Composite Price Index (000681.SH)."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests


ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
OUTPUT = ROOT / "archive/legacy_layout/strategies" / "kechuang" / "backtest" / "data" / "benchmark"
INDEX_CODE = "000681.SH"
VENDOR_CODE = "sh000681"
START = "2019-12-20"


def latest_committed_market_date() -> str:
    audits = sorted((ROOT / "K线数据/更新备份与审计").glob("*/audit.json"), reverse=True)
    for audit_path in audits:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("status") == "ok":
            validation = audit.get("validation", {})
            value = validation.get("active_symbol_latest_date") or audit.get("target")
            if value:
                return str(value)
    raise RuntimeError("No successful market-data audit was found")


def download(end: str) -> tuple[bytes, dict, str]:
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={VENDOR_CODE},day,{START},{end},2000,qfq"
    )
    session = requests.Session()
    session.trust_env = False
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = session.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://stockapp.finance.qq.com/",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("data", {}).get(VENDOR_CODE, {}).get("day"):
                return response.content, payload, url
            raise RuntimeError(f"Provider returned no daily rows: {payload}")
        except Exception as exc:  # retry network/provider failures
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Index download failed after retries: {last_error}")


def parse_and_validate(payload: dict, expected_end: str) -> pd.DataFrame:
    columns = ["date", "open", "close", "high", "low", "volume"]
    frame = pd.DataFrame(payload["data"][VENDOR_CODE]["day"], columns=columns)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    if frame.empty:
        raise AssertionError("Empty index history")
    if frame["date"].duplicated().any():
        raise AssertionError("Duplicate index dates")
    if frame[columns].isna().any().any():
        raise AssertionError("Null index fields")
    if not (frame[["open", "close", "high", "low"]] > 0).all().all():
        raise AssertionError("Non-positive index price")
    if not (frame["high"] >= frame[["open", "close", "low"]].max(axis=1)).all():
        raise AssertionError("Invalid daily high")
    if not (frame["low"] <= frame[["open", "close", "high"]].min(axis=1)).all():
        raise AssertionError("Invalid daily low")
    if frame["date"].max() != pd.Timestamp(expected_end):
        raise AssertionError(
            f"Latest provider row {frame['date'].max().date()} != committed market date {expected_end}"
        )
    return frame


def main() -> None:
    end = latest_committed_market_date()
    raw, payload, url = download(end)
    frame = parse_and_validate(payload, end)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    raw_path = OUTPUT / f"{INDEX_CODE}.tencent.json"
    parquet_path = OUTPUT / f"{INDEX_CODE}.parquet"
    provenance_path = OUTPUT / f"{INDEX_CODE}.provenance.json"
    raw_path.write_bytes(raw)
    frame.to_parquet(parquet_path, index=False)

    provenance = {
        "name_cn": "上证科创板综合价格指数",
        "short_name_cn": "科创价格",
        "code": INDEX_CODE,
        "index_kind": "price_index",
        "price_source": "Tencent historical kline API",
        "source_url": url,
        "official_reference": "https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20250108_10767835.shtml",
        "downloaded_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "market_data_commit": end,
        "rows": int(len(frame)),
        "first_date": str(frame["date"].min().date()),
        "last_date": str(frame["date"].max().date()),
        "columns": list(frame.columns),
        "raw_sha256": sha256(raw).hexdigest(),
        "parquet_sha256": sha256(parquet_path.read_bytes()).hexdigest(),
        "notes": "The provider history begins on the index publication date; the 2019-12-31 base date is not a published daily observation in this feed.",
    }
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(provenance, ensure_ascii=False, indent=2))
    print(frame.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
