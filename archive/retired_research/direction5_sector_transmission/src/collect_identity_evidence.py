"""Archive pre-boundary issuer notices supporting security-identity diagnostics."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))


def main():
    import pdfplumber
    import pypdfium2 as pdfium
    output = ROOT / "sources/security_identity_v1"
    output.mkdir(parents=True, exist_ok=True)
    jobs = [
        {"id": "000033_delisting_notice", "published_date": "2017-07-07", "page": 0,
         "url": "https://disc.static.szse.cn/disc/disk01/finalpage/2017-07-07/f4f799b7-4f94-4f48-a8f3-950e14e116f3.PDF",
         "symbols": ["000033.SZ"], "event_date": "2017-07-07", "event": "delisted_before_research_start"},
        {"id": "000916_merger_notice", "published_date": "2017-12-21", "page": 0,
         "url": "https://static.cninfo.com.cn/finalpage/2017-12-21/1204242423.PDF",
         "symbols": ["000916.SZ"], "event_date": "2017-12-25", "event": "merger_delisting_before_research_start"},
        {"id": "601313_code_change_notice", "published_date": "2018-02-13", "page": 0,
         "url": "https://static.cninfo.com.cn/finalpage/2018-02-13/1204419027.PDF",
         "symbols": ["601313.SH", "601360.SH"], "event_date": "2018-02-28", "event": "announced_code_change_and_suspension"},
        {"id": "601360_code_change_confirmation", "published_date": "2018-04-27", "page": 6,
         "url": "https://static.cninfo.com.cn/finalpage/2018-04-27/1204804713.PDF",
         "symbols": ["601313.SH", "601360.SH"], "event_date": "2018-02-28", "event": "quarter_report_confirms_code_change"}
    ]
    records = []
    for job in jobs:
        assert pd.Timestamp(job["published_date"]) <= pd.Timestamp("2024-12-31")
        path = output / (job["id"] + ".pdf")
        if not path.exists():
            response = requests.get(job["url"], timeout=(10, 30))
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise RuntimeError("Issuer source is not a PDF.")
            path.write_bytes(response.content)
        with pdfplumber.open(path) as doc:
            text = doc.pages[job["page"]].extract_text() or ""
        for symbol in job["symbols"]:
            if symbol[:6] not in text:
                raise RuntimeError(f"Expected identity code not found on selected source page: {job['id']}")
        (output / (job["id"] + ".txt")).write_text(text, encoding="utf-8")
        preview_dir = ROOT / "audits/semantics_v1/identity_preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        doc = pdfium.PdfDocument(str(path))
        doc[job["page"]].render(scale=1.0).to_pil().save(preview_dir / (job["id"] + ".png"))
        doc.close()
        records.append({**job, "source_page_1based": job["page"] + 1,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "document": str(path.relative_to(ROOT)), "point_in_time_usage": "not_before_publication",
                        "no_price_or_membership_snapshot_modified": True})
    data = pd.read_parquet(ROOT / "inputs_pre2025/kline_v1/601360.SH.parquet", columns=["date", "code", "tradestatus"])
    prior = data[data.date.lt("2018-02-28")]
    report = {"issuer_notices": records,
              "observed_storage_alias": {"file": "601360.SH.parquet", "stored_code": "sh.601360",
                                         "rows_before_actual_code_change": len(prior),
                                         "active_rows_before_actual_code_change": int(prior.tradestatus.astype(str).eq("1").sum())},
              "finding": "Provider storage identifiers can be retrospectively renamed; historical trading code and stable storage identity must be separate.",
              "resolution": {"000033.SZ": "documented_2017_event_outside_research_period",
                             "000916.SZ": "documented_2017_event_outside_research_period",
                             "601313.SH": "code_change_to_601360_requires_explicit_historical_identifier_sidecar"},
              "scope": "three flagged publication identifiers only; not a complete securities-master audit",
              "action": "retain_frozen_inputs_and_registration; any identity-resolution input requires a separately versioned data layer",
              "historical_universe_complete": False, "economic_labels_ready": False}
    (output / "sources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "audits/semantics_v1/security_identity_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"archived_issuer_notices": len(records), "pre_code_change_rows_under_new_storage_id": len(prior),
                      "frozen_inputs_modified": False}))


if __name__ == "__main__":
    main()
