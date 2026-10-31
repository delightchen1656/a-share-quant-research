"""Get final issuer notices for preidentified data conflicts, not performance selection."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))
STORE = ROOT / "sources/corporate_action_exceptions"
JOBS = [
    {"symbol": "600025.SH", "name": "华能水电", "month": "2019-06", "ex_date": "2019-07-05", "public_cash": "0.178", "kind": "public_vs_restricted_cash"},
    {"symbol": "600025.SH", "name": "华能水电", "month": "2020-06", "ex_date": "2020-06-19", "public_cash": "0.18", "kind": "public_vs_restricted_cash"},
    {"symbol": "600989.SH", "name": "宝丰能源", "month": "2019-09", "ex_date": "2019-09-27", "public_cash": "0.32091", "kind": "public_vs_restricted_cash"},
    {"symbol": "600989.SH", "name": "宝丰能源", "month": "2020-05", "ex_date": "2020-06-04", "public_cash": "0.32091", "kind": "public_vs_restricted_cash"},
    {"symbol": "600720.SH", "name": "中交设计", "month": "2024-06", "ex_date": "2024-06-13", "public_cash": "0.3674", "kind": "combined_report_periods"},
    {"symbol": "601966.SH", "name": "玲珑轮胎", "month": "2024-06", "ex_date": "2024-06-14", "public_cash": "0.377", "kind": "combined_report_periods"},
]


def main():
    import pdfplumber
    import pypdfium2 as pdfium
    STORE.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for job in JOBS:
        stem = job["symbol"] + "_" + job["ex_date"]
        query_path = STORE / (stem + "_query.json")
        if query_path.exists():
            result = json.loads(query_path.read_text(encoding="utf-8"))
        else:
            start = pd.Timestamp(job["month"] + "-01")
            end = start + pd.offsets.MonthEnd(0)
            payload = {"pageNum": 1, "pageSize": 50, "column": "sse", "tabName": "fulltext", "stock": "", "plate": "",
                       "searchkey": job["name"], "seDate": f"{start.date()}~{end.date()}", "sortName": "time", "sortType": "asc", "isHLtitle": "true"}
            response = requests.post("https://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload,
                                     headers={"Referer": "https://www.cninfo.com.cn/", "User-Agent": "Mozilla/5.0"}, timeout=(10, 25))
            response.raise_for_status()
            result = response.json()
            query_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        matches = [r for r in result.get("announcements", []) if r.get("secCode") == job["symbol"][:6]
                   and "权益分派实施公告" in re.sub(r"<[^>]+>", "", r.get("announcementTitle", ""))]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one final implementation notice for {stem}; found {len(matches)}")
        item = matches[0]
        url = "https://static.cninfo.com.cn/" + item["adjunctUrl"]
        date = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", url).group(1)
        if date > "2024-12-31":
            raise RuntimeError("Issuer notice after research boundary.")
        path = STORE / (stem + ".pdf")
        if not path.exists():
            response = requests.get(url, timeout=(10, 25))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError("Expected issuer PDF.")
            path.write_bytes(response.content)
        with pdfplumber.open(path) as doc:
            texts = [p.extract_text() or "" for p in doc.pages]
        text = "\n".join(texts)
        if job["public_cash"] not in re.sub(r"\s+", "", text):
            raise RuntimeError("Expected public-shareholder cash amount absent from notice.")
        (STORE / (stem + ".txt")).write_text(text, encoding="utf-8")
        preview = ROOT / "audits/action_exception_previews"
        preview.mkdir(parents=True, exist_ok=True)
        pdf = pdfium.PdfDocument(str(path))
        pdf[0].render(scale=1.0).to_pil().save(preview / (stem + ".png"))
        pdf.close()
        outcomes.append({**job, "source_url": url, "published_date": date,
                         "source_file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "issuer_notice_token_check_passed": True, "manual_review_required": True,
                         "public_shareholder_category_only": True, "approved_override": False})
        (STORE / "exception_sources.json").write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"symbol": job["symbol"], "ex_date": job["ex_date"], "issuer_notice_archived": True}), flush=True)


if __name__ == "__main__":
    main()
