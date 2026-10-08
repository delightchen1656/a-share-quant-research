from __future__ import annotations

import html
import re
import time
from pathlib import Path

import pandas as pd
import requests


BASE = "https://www.zhunshangshi.com/stock/{page}?market=%E7%A7%91%E5%88%9B%E6%9D%BF"
OUT = Path(__file__).resolve().parent / "industry_map.csv"


def clean(cell: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()


rows = []
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"
for page_no in range(1, 32):
    page = "" if page_no == 1 else f"p_{page_no}/"
    last = None
    for attempt in range(6):
        try:
            response = session.get(BASE.format(page=page), timeout=30)
            response.raise_for_status()
            text = response.content.decode("utf-8")
            trs = re.findall(r"<tr>(.*?)</tr>", text, flags=re.S)
            parsed = [[clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)] for tr in trs]
            parsed = [x for x in parsed if len(x) == 7 and re.fullmatch(r"688\d{3}\.SH", x[1])]
            if not parsed and page_no > 1:
                last = None
                break
            if not parsed:
                raise RuntimeError("empty first page")
            rows.extend(parsed)
            print(page_no, len(parsed))
            break
        except Exception as exc:
            last = exc
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f"page {page_no} failed: {last}")
    if last is None and not parsed:
        break

frame = pd.DataFrame(rows, columns=["name", "symbol", "market", "industry", "ipo_date", "region", "connect"])
frame = frame.drop_duplicates("symbol").sort_values("symbol")
frame.to_csv(OUT, index=False, encoding="utf-8-sig")
print(OUT, len(frame), frame.industry.nunique())
