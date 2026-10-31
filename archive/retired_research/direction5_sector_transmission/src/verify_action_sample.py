"""Archive one final implementation notice to audit API action fields and tax ambiguity."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))


def main():
    import pdfplumber
    import pypdfium2 as pdfium
    output = ROOT / "sources/corporate_action_issuer_examples"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "000403_20200721.pdf"
    url = "https://disc.static.szse.cn/download/disc/disk02/finalpage/2020-07-21/43bfe8d4-9405-40c1-a1fb-4827c52afd03.PDF"
    if not path.exists():
        response = requests.get(url, timeout=(10, 30))
        response.raise_for_status()
        if not response.content.startswith(b"%PDF"):
            raise RuntimeError("Issuer implementation response is not PDF.")
        path.write_bytes(response.content)
    with pdfplumber.open(path) as doc:
        texts = [p.extract_text() or "" for p in doc.pages]
    text = "\n".join(texts)
    compact = re.sub(r"\s+", "", text)
    for expected in ("000403", "3.973831", "1.202083", "2020年7月24日", "2020年7月27日", "持股期限"):
        if expected not in compact:
            raise RuntimeError("Expected action implementation detail missing: " + expected)
    (output / "000403_20200721.txt").write_text(text, encoding="utf-8")
    previews = ROOT / "audits/semantics_v1/action_sample_preview"
    previews.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(path))
    for index in range(len(texts)):
        doc[index].render(scale=1.0).to_pil().save(previews / f"page_{index + 1}.png")
    doc.close()
    event = {
        "symbol": "000403.SZ", "published_date": "2020-07-21", "source_url": url,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "register_date": "2020-07-24", "ex_date": "2020-07-27",
        "cash_before_tax_per_share_from_final_plan": "0.1202083",
        "bonus_per_share_from_final_plan": "0.3973831",
        "transfer_per_share_from_final_plan": "0.3973831",
        "tax_condition": "holding-period dependent; includes taxable bonus shares; provider after-tax alternatives are not one universally applicable cash amount",
        "empty_provider_fields_are_not_implicitly_zero": True,
        "sample_scope": "one implementation example; not a complete action database",
        "visual_review_required": True, "approved_for_economic_labels": False
    }
    (output / "000403_20200721_source.json").write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"issuer_example_archived": True, "rendered_pages": len(texts), "complete_database": False}))


if __name__ == "__main__":
    main()
