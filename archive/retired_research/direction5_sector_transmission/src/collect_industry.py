"""Collect official historical industry publications, preserving publication lag."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STORE = (ROOT / CONFIG["industry_store"]).resolve() / "official_history_v1"
CUTOFF = pd.Timestamp(CONFIG["research_cutoff"])
if CUTOFF > pd.Timestamp("2024-12-31"):
    raise RuntimeError("Research date boundary cannot be widened by config alone.")
CSRC = "https://www.csrc.gov.cn/csrc/c100103/common_list.shtml"
CAPCO = "https://www.capco.org.cn/pub/zgssgsxh/xhgg/hyfl/hyfljg/index.html"


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def get(url):
    response = requests.get(url, timeout=(10, 35), headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response


def html(url):
    response = get(url)
    response.encoding = "utf-8"
    return response.text


def discover():
    STORE.mkdir(parents=True, exist_ok=True)
    candidates, errors = [], []
    for provider, url in (("CSRC", CSRC), ("CAPCO", CAPCO)):
        try:
            content = html(url)
            (STORE / f"{provider.lower()}_index.html").write_text(content, encoding="utf-8")
            soup = BeautifulSoup(content, "lxml")
            for anchor in soup.find_all("a", href=True):
                title = anchor.get_text("", strip=True)
                match = re.search(r"(20\d{2})年.*上市公司行业分类结果", title)
                if match and 2017 <= int(match.group(1)) <= 2024:
                    candidates.append({"provider": provider, "title": title,
                                       "page_url": urljoin(url, anchor["href"])})
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)})
    candidates = list({c["page_url"]: c for c in candidates}.values())
    # The association migrated its archive to a static-data Vue site. Parse its
    # published metadata as text; never execute downloaded JavaScript.
    try:
        bundle_path = STORE / "capco_root_bundle.js"
        if not bundle_path.exists():
            home = BeautifulSoup(html("https://www.capco.org.cn/"), "lxml")
            script = home.find("script", src=re.compile(r"index-.*\.js"))
            bundle_url = urljoin("https://www.capco.org.cn/", script["src"])
            bundle_path.write_text(html(bundle_url), encoding="utf-8")
        bundle = bundle_path.read_text(encoding="utf-8")
        pattern = r'\{title:"([^"]+)",articleUrl:"(zsxfb/hyfl/hyfljg/[^"]+)",date:"([^"]+)"'
        for title, path, date in re.findall(pattern, bundle):
            year = re.match(r"(20\d{2})年", title)
            if year and 2023 <= int(year.group(1)) <= 2024 and pd.Timestamp(date) <= CUTOFF:
                candidates.append({"provider": "CAPCO", "title": title,
                                   "page_url": "https://www.capco.org.cn/dataFile/" + path,
                                   "index_published_date": date,
                                   "metadata_source": "https://www.capco.org.cn/"})
    except Exception as exc:
        errors.append({"url": "CAPCO static historical index", "error": str(exc)})
    save_json(STORE / "discovery.json", {"candidates": candidates, "errors": errors})
    print(json.dumps({"discovered": len(candidates), "errors": errors}, ensure_ascii=False), flush=True)
    return candidates


def collect_one(item):
    key = digest(item["page_url"].encode())[:12]
    target = STORE / "publications" / key
    target.mkdir(parents=True, exist_ok=True)
    record = dict(item, id=key, approved_for_research=False)
    try:
        cached_source = target / "source.json"
        if cached_source.exists():
            cached = json.loads(cached_source.read_text(encoding="utf-8"))
            attachment = Path(cached.get("attachment_file", "__missing__"))
            if cached.get("status") == "downloaded_needs_parse_audit" and attachment.is_file():
                if digest(attachment.read_bytes()) == cached["attachment_sha256"]:
                    return cached
        content = html(item["page_url"])
        if item["page_url"].endswith(".js"):
            (target / "article_source.js").write_text(content, encoding="utf-8")
            match = re.search(r"export\s+const\s+allData\s*=\s*(\{[\s\S]*\})", content)
            if not match:
                raise ValueError("Official static article has unexpected data format.")
            payload = json.loads(match.group(1))
            article_text = payload["text"].replace('\\"', '"').replace("\\r\\n", "")
            dates = [payload["date"]]
            if dates[0] != item["index_published_date"] or payload["title"] != item["title"]:
                raise ValueError("Official article and index publication metadata disagree.")
            soup = BeautifulSoup(article_text, "lxml")
        else:
            (target / "page.html").write_text(content, encoding="utf-8")
            soup = BeautifulSoup(content, "lxml")
            dates = []
        text = soup.get_text(" ", strip=True)
        dates = dates or re.findall(r"(?:日期[：:]|发布时间[：:]|发布日期[：:])\s*(\d{4}-\d{2}-\d{2})", text)
        if not dates:
            for meta in soup.find_all("meta"):
                if any(x in str(meta.get("name", "")).lower() for x in ("pubdate", "publishdate", "date")):
                    date = re.search(r"\d{4}-\d{2}-\d{2}", meta.get("content", ""))
                    if date:
                        dates.append(date.group())
        if not dates:
            raise ValueError("No verified publication date on official page.")
        record["published_date"] = dates[0]
        if pd.Timestamp(dates[0]) > CUTOFF:
            record["status"] = "excluded_publication_after_cutoff"
            save_json(target / "source.json", record)
            return record
        links = []
        for anchor in soup.find_all("a", href=True):
            url = urljoin(item["page_url"], anchor["href"].strip())
            if re.search(r"\.(pdf|xlsx?|csv)(?:\?|$)", url, flags=re.I):
                links.append((anchor.get_text("", strip=True), url))
        if not links:
            raise ValueError("No downloadable classification attachment found.")
        # Prefer code-sorted tables when the publisher supplies both layouts.
        links.sort(key=lambda x: ("股票代码" not in x[0], ".pdf" not in x[1].lower()))
        label, url = links[0]
        suffix = re.search(r"\.(pdf|xlsx?|csv)(?:\?|$)", url, re.I).group(1).lower()
        try:
            response = get(url)
        except requests.RequestException:
            # Retain the older publisher-owned attachment archive if a migrated
            # nonstandard-port link is unavailable. Verify the actual PDF below.
            archive_url = "https://capcofile.oss-cn-beijing.aliyuncs.com/2024/file/GwFj/" + label
            response = get(archive_url)
            record["migrated_attachment_url"] = url
            url = archive_url
        data = response.content
        if suffix == "pdf" and not data.startswith(b"%PDF"):
            raise ValueError("Attachment response is not a PDF.")
        path = target / f"classification.{suffix}"
        path.write_bytes(data)
        record.update(attachment_url=url, attachment_label=label, attachment_file=str(path),
                      attachment_sha256=digest(data), page_sha256=digest(content.encode()),
                      earliest_usable_date=str((pd.Timestamp(dates[0]) + pd.Timedelta(days=1)).date()),
                      timing_rule="strictly after official publication date; next observed trading day",
                      status="downloaded_needs_parse_audit")
    except Exception as exc:
        record.update(status="failed", error=str(exc))
    save_json(target / "source.json", record)
    return record


def clean(value):
    return re.sub(r"\s+", "", str(value or ""))


def parse_pdf(path, record):
    import pdfplumber
    rows, codes_seen_in_text = [], set()
    category, major, major_name = None, None, None
    layout_examples = []
    with pdfplumber.open(path) as doc:
        pages = len(doc.pages)
        for page_number, page in enumerate(doc.pages, 1):
            text = page.extract_text() or ""
            codes_seen_in_text.update(re.findall(r"(?<!\d)\d{6}(?!\d)", text))
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    cells = [clean(v) for v in row]
                    if len(cells) < 5:
                        continue
                    # Official layouts: 5 columns (CSRC), 6 columns (CAPCO by industry),
                    # 8 columns (CAPCO by stock code).
                    if re.fullmatch(r"\d{6}", cells[0]) and len(cells) >= 8:
                        stock, name = cells[0:2]
                        cat, maj, maj_name = cells[2], cells[6], cells[7]
                    elif re.fullmatch(r"\d{6}", cells[-2]):
                        stock, name = cells[-2:]
                        cat_text = cells[0]
                        cat_match = re.search(r"[（(]([A-S])[）)]", cat_text)
                        if cat_match:
                            category = cat_match.group(1)
                        if re.fullmatch(r"\d{2}", cells[-4]):
                            major, major_name = cells[-4], cells[-3]
                        cat, maj, maj_name = category, major, major_name
                    else:
                        continue
                    if not cat or not re.fullmatch(r"[A-S]", cat) or not maj or not re.fullmatch(r"\d{2}", maj):
                        raise ValueError(f"Unresolved industry hierarchy at page {page_number}, stock {stock}")
                    rows.append({"stock_code": stock, "stock_name": name, "industry_code": cat + maj,
                                 "industry_name": maj_name, "category_code": cat,
                                 "source_id": record["id"], "source_page": page_number,
                                 "published_date": record["published_date"],
                                 "earliest_usable_date": record["earliest_usable_date"],
                                 "classification_system": "CSRC2012" if record["provider"] == "CSRC" else "CAPCO2023"})
                    if len(layout_examples) < 5:
                        layout_examples.append(cells)
    df = pd.DataFrame(rows)
    if df.empty or df["stock_code"].duplicated().any():
        raise ValueError("Empty extraction or duplicate stock codes.")
    extracted = set(df["stock_code"])
    missing = sorted(codes_seen_in_text - extracted)
    extra = sorted(extracted - codes_seen_in_text)
    if missing or extra:
        raise ValueError(f"Text/table stock-code mismatch: missing={missing[:12]}, extra={extra[:12]}")
    return df, {"pages": pages, "rows_all_exchanges_and_share_classes": len(df),
                "text_stock_codes": len(codes_seen_in_text), "text_table_codes_match": True,
                "industries": int(df["industry_code"].nunique()), "layout_examples": layout_examples}


def main():
    candidates = discover()
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for record in pool.map(collect_one, candidates):
            records.append(record)
            print(json.dumps({"title": record["title"], "status": record["status"]}, ensure_ascii=False), flush=True)
    save_json(STORE / "sources.json", records)
    parsed, audits = [], []
    previous_audits_path = STORE / "parse_audit.json"
    previous_audits = {r["id"]: r for r in json.loads(previous_audits_path.read_text(encoding="utf-8"))} if previous_audits_path.exists() else {}
    for record in records:
        if record["status"] != "downloaded_needs_parse_audit":
            continue
        try:
            path = Path(record["attachment_file"])
            dest = path.parent / "membership.csv"
            previous = previous_audits.get(record["id"], {})
            if dest.exists() and previous.get("membership_sha256") == digest(dest.read_bytes()):
                df = pd.read_csv(dest, dtype=str)
                parsed.append(df)
                audits.append(previous)
                continue
            if path.suffix != ".pdf":
                raise ValueError("Non-PDF layout requires a separately verified parser.")
            df, audit = parse_pdf(path, record)
            df.to_csv(dest, index=False, encoding="utf-8-sig")
            audit.update(id=record["id"], title=record["title"], published_date=record["published_date"],
                         membership_sha256=digest(dest.read_bytes()), status="parsed_needs_visual_audit")
            parsed.append(df)
        except Exception as exc:
            audit = {"id": record["id"], "title": record["title"], "status": "parse_failed", "error": str(exc)}
        audits.append(audit)
        save_json(STORE / "parse_audit.json", audits)
        print(json.dumps({k: v for k, v in audit.items() if k != "layout_examples"}, ensure_ascii=False), flush=True)
    if parsed:
        pd.concat(parsed, ignore_index=True).to_csv(STORE / "membership_publication_history.csv", index=False, encoding="utf-8-sig")
    report = {"official_source_candidates": len(candidates), "downloaded": sum(r["status"] == "downloaded_needs_parse_audit" for r in records),
              "parsed": len(parsed), "source_store": str(STORE), "approved_for_research": False,
              "notes": ["Original publication dates preserved; never backdate to report period end.",
                        "New stocks without a published classification stay unclassified.",
                        "Classification schema revisions remain separate; no retrospective remapping.",
                        "Visual hierarchy audit and coverage audit still required before whitelist promotion."]}
    save_json(ROOT / "audits/official_industry_collection.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
