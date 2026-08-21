"""Download the STAR 50 benchmark from Eastmoney's free history endpoint."""
from pathlib import Path
import time

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
base_params = {
    "secid": "1.000688", "klt": "101", "fqt": "0",
    "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
}
session = requests.Session()
session.trust_env = False
columns = ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "pctChg", "change", "turnover"]
frames = []
# The index was launched in 2020. Short yearly requests are more reliable than
# one oversized request and make this downloader naturally resumable.
for year in range(2019, 2027):
    params = dict(base_params, beg=f"{year}0101", end=f"{year}1231" if year < 2026 else "20260731")
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(
                url, params=params,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            rows = [line.split(",") for line in data.get("klines", [])]
            if rows:
                frames.append(pd.DataFrame(rows, columns=columns))
            print(year, len(rows))
            break
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f"Failed to download {year} after 3 attempts: {last_error}")
frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
if frame.empty:
    raise RuntimeError("Eastmoney returned no STAR 50 data")
frame["date"] = pd.to_datetime(frame["date"])
frame[columns[1:]] = frame[columns[1:]].apply(pd.to_numeric, errors="coerce")
frame = frame.drop_duplicates("date").sort_values("date")
target = ROOT / "data" / "benchmark" / "000688.SH.parquet"
target.parent.mkdir(parents=True, exist_ok=True)
frame.to_parquet(target, index=False)
print(target, len(frame), frame.date.min(), frame.date.max())
