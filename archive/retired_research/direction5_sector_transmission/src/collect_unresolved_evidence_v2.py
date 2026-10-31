"""Archive bounded issuer notices for the frozen input-audit exception list."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))
OUT = ROOT / "sources/action_evidence_v2"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def jobs():
    old = ROOT / "datasets/corporate_actions_reconciled_v1"
    unresolved = pd.read_parquet(old / "unresolved_event_fields.parquet")
    windows = pd.read_parquet(old / "reference_windows_needing_investigation.parquet")
    values = []
    for row in unresolved.itertuples():
        values.append({"symbol": row.symbol, "event_date": str(row.ex_date.date()), "kind": "dividend_fields",
                       "start": str((row.ex_date - pd.Timedelta(days=80)).date())})
    for row in windows.loc[windows.status.eq("no_known_dividend_or_rights_event")].itertuples():
        values.append({"symbol": row.symbol, "event_date": str(row.reference_date.date()), "kind": "unknown_reference",
                       "start": str((row.previous_active_date - pd.Timedelta(days=45)).date())})
    return values


def fetch(job):
    import pdfplumber
    directory = OUT / (job["symbol"] + "_" + job["event_date"])
    directory.mkdir(parents=True, exist_ok=True)
    announcements, query_files, seen_pages = [], [], set()
    for page in range(1, 21):
        path = directory / f"query_{page:02d}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = {"pageNum": page, "pageSize": 100, "column": "sse" if job["symbol"].endswith("SH") else "szse",
                       "tabName": "fulltext", "searchkey": job["symbol"][:6],
                       "seDate": job["start"] + "~" + job["event_date"],
                       "sortName": "time", "sortType": "asc", "isHLtitle": "false"}
            response = requests.post("https://www.cninfo.com.cn/new/hisAnnouncement/query", data=payload,
                                     headers=HEADERS, timeout=(10, 30))
            response.raise_for_status()
            result = response.json()
            save(path, result)
        query_files.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        signature = tuple(r.get("announcementId") for r in result.get("announcements") or [])
        if signature in seen_pages and signature:
            raise RuntimeError("Repeated announcement page; refuse to call pagination complete.")
        seen_pages.add(signature)
        announcements.extend(r for r in result.get("announcements") or [] if r.get("secCode") == job["symbol"][:6])
        if not result.get("hasMore"):
            break
    else:
        raise RuntimeError("Announcement pagination exceeded bounded limit: " + str(job))
    selected = []
    for item in {r["announcementId"]: r for r in announcements}.values():
        title = re.sub(r"<[^>]+>", "", item["announcementTitle"])
        match = re.search(r"权益分派.*实施|分红.*实施|派息.*实施|利润分配.*实施|除权|除息|资本公积.*转增.*实施|重整.*转增|重整.*执行完毕|复牌", title)
        if not match:
            continue
        if job["kind"] == "dividend_fields" and not re.search(r"权益分派.*实施|分红.*实施|派息.*实施|利润分配.*实施|除权|除息", title):
            continue
        url = "https://static.cninfo.com.cn/" + item["adjunctUrl"]
        match_date = re.search(r"finalpage/(\d{4}-\d{2}-\d{2})/", url)
        if not match_date:
            continue
        published = match_date.group(1)
        if published > min(job["event_date"], "2024-12-31"):
            raise RuntimeError("Future evidence in historical event query.")
        file = directory / (item["announcementId"] + ".pdf")
        if not file.exists():
            response = requests.get(url, headers=HEADERS, timeout=(10, 40))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError("Expected PDF: " + url)
            file.write_bytes(response.content)
        with pdfplumber.open(file) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text_file = file.with_suffix(".txt")
        text_file.write_text("\n".join(f"--- PAGE {i+1} ---\n{t}" for i,t in enumerate(pages)), encoding="utf-8")
        selected.append({"title": title, "url": url, "published_date": published,
                         "pdf": str(file.relative_to(ROOT)), "text": str(text_file.relative_to(ROOT)),
                         "sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "pages": len(pages)})
    value = {**job, "query_files": query_files, "exact_code_announcements": len(announcements),
             "documents": selected, "no_document_is_not_no_event_proof": True,
             "fields_verified": False}
    save(directory / "catalog.json", value)
    return value


def main():
    outcomes = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, job): job for job in jobs()}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            try:
                value = future.result()
                outcomes.append(value)
                print(json.dumps({"symbol": job["symbol"], "date": job["event_date"], "documents": len(value["documents"])}), flush=True)
            except Exception as exc:
                outcomes.append({**job, "error": repr(exc)})
                print(json.dumps({"symbol": job["symbol"], "error": repr(exc)}), flush=True)
            save(OUT / "catalog.json", sorted(outcomes, key=lambda r: (r["symbol"], r["event_date"])))
    print(json.dumps({"jobs": len(outcomes), "failed": sum("error" in r for r in outcomes),
                      "documents": sum(len(r.get("documents", [])) for r in outcomes)}))


if __name__ == "__main__":
    main()
