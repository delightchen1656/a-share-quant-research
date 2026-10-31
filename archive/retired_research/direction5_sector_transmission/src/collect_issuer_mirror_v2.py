"""Archive issuer-authored disclosures from a second public distribution mirror."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

from collect_unresolved_evidence_v2 import jobs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))
OUT = ROOT / "sources/action_issuer_mirror_v2"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def content_pages(directory, article):
    values, evidence, seen = [], [], set()
    pages = 1
    for number in range(1, 101):
        file = directory / (article + ("_content.json" if number == 1 else f"_content_{number:02d}.json"))
        if not file.exists():
            time.sleep(2)
            response = requests.get("https://np-cnotice-stock.eastmoney.com/api/content/ann",
                                    params={"art_code": article, "client_source": "web", "page_index": number},
                                    headers={"User-Agent": "Mozilla/5.0"}, timeout=(10, 40))
            response.raise_for_status()
            save(file, response.json())
        value = json.loads(file.read_text(encoding="utf-8"))
        assert value["success"] == 1
        body = value["data"]
        assert body["art_code"] == article and body["is_ai_summary"] == 0
        text = body["notice_content"]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in seen and text:
            raise RuntimeError("Repeated notice content page; completeness not established.")
        seen.add(digest)
        values.append(text)
        evidence.append({"path": str(file.relative_to(ROOT)), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        pages = int(body["page_size"])
        if number >= pages:
            return "\n".join(values), body, evidence
    raise RuntimeError("Notice content exceeded bounded pagination limit.")


def fetch(job):
    import pdfplumber
    directory = OUT / (job["symbol"] + "_" + job["event_date"])
    directory.mkdir(parents=True, exist_ok=True)
    announcements, query_files, seen = [], [], set()
    for page in range(1, 21):
        params = {"sr": -1, "page_size": 100, "page_index": page, "ann_type": "A",
                  "stock_list": job["symbol"][:6], "begin_time": job["start"], "end_time": job["event_date"]}
        path = directory / f"query_{page:02d}.json"
        if path.exists():
            response = json.loads(path.read_text(encoding="utf-8"))
        else:
            time.sleep(0.6)
            result = requests.get("https://np-anotice-stock.eastmoney.com/api/security/ann", params=params,
                                  headers={"User-Agent": "Mozilla/5.0"}, timeout=(10, 30))
            result.raise_for_status()
            response = result.json()
            save(path, response)
        assert response["success"] == 1
        data = response["data"]
        signature = tuple(r["art_code"] for r in data["list"])
        if signature in seen and signature:
            raise RuntimeError("Repeated source page.")
        seen.add(signature)
        query_files.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "request": params})
        for row in data["list"]:
            if not job["start"] <= row["notice_date"][:10] <= min(job["event_date"], "2024-12-31"):
                raise RuntimeError("Source did not honor historical query dates.")
            if job["symbol"][:6] not in {r["stock_code"] for r in row["codes"]}:
                raise RuntimeError("Source returned a different security.")
            announcements.append(row)
        if page * int(data["page_size"]) >= int(data["total_hits"]):
            break
    else:
        raise RuntimeError("Source pagination limit.")
    selected = []
    for row in {r["art_code"]: r for r in announcements}.values():
        title = row["title"]
        dividend = re.search(r"权益分派.*实施|分红.*实施|派息.*实施|利润分配.*实施|除权|除息", title)
        special = re.search(r"资本公积.*转增.*实施|重整.*转增|重整.*执行完毕|复牌|转增.*登记", title)
        if not dividend and not (job["kind"] == "unknown_reference" and special):
            continue
        url = "https://np-cnotice-stock.eastmoney.com/api/content/ann"
        text, body, pages = content_pages(directory, row["art_code"])
        assert body["notice_date"][:10] == row["notice_date"][:10]
        text_file = directory / (row["art_code"] + ".txt")
        text_file.write_text(text, encoding="utf-8")
        selected.append({"title": title, "url": url, "published_date": row["notice_date"][:10],
                         "raw_response": pages[0]["path"], "text": str(text_file.relative_to(ROOT)),
                         "sha256": pages[0]["sha256"], "content_pages": pages,
                         "article_code": row["art_code"], "original_pdf_link": body["attach_url"],
                         "pdf_available_and_visually_reviewed": False,
                         "source_role": "issuer_authored_notice_text_distributed_by_eastmoney_mirror_not_AI_summary"})
    result = {**job, "query_files": query_files, "announcement_count": len(announcements), "documents": selected,
              "fields_verified": False, "no_document_is_not_no_event_proof": True}
    save(directory / "catalog_text.json", result)
    return result


def main():
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        futures = {pool.submit(fetch, job): job for job in jobs()}
        for future in concurrent.futures.as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
                records.append(result)
                print(json.dumps({"symbol": job["symbol"], "date": job["event_date"], "documents": len(result["documents"])}), flush=True)
            except Exception as exc:
                records.append({**job, "error": repr(exc)})
                print(json.dumps({"symbol": job["symbol"], "error": repr(exc)}), flush=True)
            save(OUT / "catalog_text.json", sorted(records, key=lambda r: (r["symbol"], r["event_date"])))
    print(json.dumps({"jobs": len(records), "failed": sum("error" in r for r in records),
                      "documents": sum(len(r.get("documents", [])) for r in records)}))


if __name__ == "__main__":
    main()
