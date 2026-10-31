"""Apply reviewed input corrections to a new staging version, preserving v1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/corporate_actions_reconciled_v2"


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def notice(symbol, event_date, article):
    directory = f"sources/action_issuer_mirror_v2/{symbol}_{event_date}"
    catalog = read(directory + "/catalog_text.json")
    record = next(r for r in catalog["documents"] if r["article_code"] == article)
    if "content_pages" not in record:
        response = read(record["raw_response"])
        assert response["data"]["is_ai_summary"] == 0 and int(response["data"]["page_size"]) == 1
        record["content_pages"] = [{"path": record["raw_response"], "sha256": record["sha256"]}]
    for page in record["content_pages"]:
        assert sha(page["path"]) == page["sha256"]
    text = (ROOT / record["text"]).read_text(encoding="utf-8")
    return {**record, "text_sha256": sha(record["text"]), "review_method": "issuer_notice_text_manually_checked",
            "source_text_not_pdf_visual_review": True}, re.sub(r"\s+", "", text)


def main():
    frozen = read("audits/data_revision_v2_registration.json")
    for record in frozen["files"]:
        assert sha(record["path"]) == record["sha256"], record["path"]
    OUT.mkdir(exist_ok=True)
    old = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v1/dividend_event_ledger_provisional.parquet")
    ledger = old.copy()
    ledger["v2_reviewed_fields"] = False
    ledger["v2_source_evidence"] = "[]"
    ledger["quote_cash_per_share"] = float("nan")
    ledger["quote_cash_evidence_verified"] = False
    ledger["identity_mapping_is_retrospective_audit_only"] = False
    corrections = [
        ("000819.SZ", "2021-06-25", "AN202106171498433202", "2021-06-24", "2021-06-25", "0.1", "0.01", None),
        ("000863.SZ", "2018-07-26", "AN201807181167910744", "2018-07-25", "2018-07-26", "2.015287", "0.2015287", None),
        ("001872.SZ", "2018-05-23", "AN201805161144498021", "2018-05-22", "2018-05-23", "13.19", "1.319", None),
        ("001914.SZ", "2018-06-06", "AN201805291150132802", "2018-06-05", "2018-06-06", "1元", "0.1", None),
        ("002016.SZ", "2024-04-19", "AN202404121630186785", "2024-04-18", "2024-04-19", "0.240000", "0.024", None),
        ("002227.SZ", "2018-06-01", "AN201805241148260417", "2018-05-31", "2018-06-01", "0.200000", "0.02", None),
        ("002349.SZ", "2021-06-30", "AN202106211499123815", "2021-06-29", "2021-06-30", "0.410000", "0.041", "0.039943"),
        ("002358.SZ", "2019-07-05", "AN201906281336797032", "2019-07-04", "2019-07-05", None, "0.1", None),
        ("002434.SZ", "2018-05-22", "AN201805151143902057", "2018-05-21", "2018-05-22", "1.502240", "0.150224", None),
        ("002435.SZ", "2021-06-18", "AN202106081496757858", "2021-06-17", "2021-06-18", "0.500000", "0.05", None),
        ("002601.SZ", "2018-10-25", "AN201810161214496778", "2018-10-24", "2018-10-25", "6.540279", "0.6540279", "0.65"),
        ("002649.SZ", "2018-06-07", "AN201805311151099274", "2018-06-06", "2018-06-07", "0.830873", "0.0830873", None),
        ("002792.SZ", "2018-06-29", "AN201806201157314293", "2018-06-28", "2018-06-29", "0.50", "0.05", None),
        ("002840.SZ", "2021-06-30", "AN202106211499171456", "2021-06-29", "2021-06-30", "0.319988", "0.0319988", None),
        ("002852.SZ", "2019-05-22", "AN201905151330186822", "2019-05-21", "2019-05-22", "4.089687", "0.4089687", "0.4"),
        ("600565.SH", "2021-06-04", "AN202105261494088908", "2021-06-03", "2021-06-04", "0.80", "0.08", None),
        ("600989.SH", "2021-05-20", "AN202105111491094056", "2021-05-19", "2021-05-20", "0.32091", "0.32091", "0.28"),
        ("601318.SH", "2018-09-06", "AN201808291184636064", "2018-09-05", "2018-09-06", "0.62", "0.62", None),
        ("601688.SH", "2024-10-25", "AN202410161640323608", "2024-10-24", "2024-10-25", "0.15", "0.15", None),
        ("601919.SH", "2024-10-10", "AN202409251640035312", "2024-10-09", "2024-10-10", "0.52", "0.52", None),
    ]
    reviews = []
    for symbol, exdate, article, reg, pay, token, cash, quote in corrections:
        evidence, text = notice(symbol, exdate, article)
        assert token is None or token in text
        mask = ledger.symbol.eq(symbol) & ledger.ex_date.eq(exdate)
        assert mask.sum() == 1
        sources = [evidence]
        if symbol == "002349.SZ":
            correction, compact = notice(symbol, exdate, "AN202106301500873464")
            assert "更正后" in compact and "0.039943" in compact
            sources.append(correction)
        if symbol == "002358.SZ":
            original, compact = notice(symbol, exdate, "AN201906271336645180")
            assert "1.000000" in compact
            sources.append(original)
        if symbol == "002852.SZ":
            formula, compact = notice(symbol, exdate, "AN201905151330186823")
            assert "收盘价-0.4元" in compact
            sources.append(formula)
        if symbol in ("001872.SZ", "001914.SZ"):
            original_code = "000022" if symbol == "001872.SZ" else "000043"
            assert original_code in text[:200]
            # Storage identity reconciliation is retrospective audit metadata only.
            # It does not backfill a later identity link into past industry features.
            sources.append({"historical_issuer_code": original_code, "storage_symbol": symbol,
                            "evidence_manifest": "sources/action_identity_evidence_v2/manifest.json",
                            "evidence_manifest_sha256": sha("sources/action_identity_evidence_v2/manifest.json"),
                            "not_approved_for_asof_industry_join": True})
            ledger.loc[mask, "identity_mapping_is_retrospective_audit_only"] = True
        for key, value in {"register_date": pd.Timestamp(reg), "cash_payment_date": pd.Timestamp(pay),
                           "cash_per_share": float(cash), "bonus_per_share": 0.0, "transfer_per_share": 0.0,
                           "event_fields_complete": True, "issues": "[]", "v2_reviewed_fields": True,
                           "v2_source_evidence": json.dumps(sources, ensure_ascii=False)}.items():
            ledger.loc[mask, key] = value
        if quote:
            ledger.loc[mask, "quote_cash_per_share"] = float(quote)
            ledger.loc[mask, "quote_cash_evidence_verified"] = True
        reviews.append({"symbol": symbol, "ex_date": exdate, "operation": "replace_reviewed_fields",
                        "cash_per_share": float(cash), "register_date": reg, "payment_date": pay,
                        "quote_cash_per_share": None if quote is None else float(quote), "sources": sources})
    removed = []
    for symbol, wrong, correct, article in [("000042.SZ", "2018-06-28", "2018-06-22", "AN201806131155478161"),
                                            ("002727.SZ", "2019-04-02", "2019-04-03", "AN201903251309328683")]:
        evidence, text = notice(symbol, wrong, article)
        assert (ledger.symbol.eq(symbol) & ledger.ex_date.eq(correct)).sum() == 1
        mask = ledger.symbol.eq(symbol) & ledger.ex_date.eq(wrong)
        assert mask.sum() == 1
        removed.append({"symbol": symbol, "rejected_source_ex_date": wrong, "canonical_ex_date": correct,
                        "reason": "misdated_duplicate_of_existing_correct_event", "evidence": evidence})
        ledger = ledger.loc[~mask].copy()
    # One issuer notice itself prints a payment before ex-date. Do not guess a replacement.
    conflict_catalog = read("sources/action_issuer_mirror_v2/002335.SZ_2018-05-16/catalog_text.json")
    conflict, compact = notice("002335.SZ", "2018-05-16", conflict_catalog["documents"][0]["article_code"])
    assert "现金红利将于2018年5月15日" in compact and "除权除息日为：2018年5月16日" in compact
    mask = ledger.symbol.eq("002335.SZ") & ledger.ex_date.eq("2018-05-16")
    ledger.loc[mask, "issues"] = json.dumps(["issuer_notice_payment_date_precedes_ex_date_unresolved"])
    ledger.loc[mask, "v2_source_evidence"] = json.dumps([conflict], ensure_ascii=False)
    additions = [
        ("000538.SZ", "2024-11-25", "2024-11-25", "2024-11-22", "1.213", "AN202411181640942649", "12.130000", None),
        ("000550.SZ", "2018-03-27", "2018-03-27", "2018-03-26", "2.317", "AN201803191106068749", "23.17", None),
        ("000756.SZ", "2018-02-14", "2018-01-26", "2018-01-25", "0.03", "AN201801191079657348", "0.30", None),
        ("002508.SZ", "2024-01-10", "2024-01-10", "2024-01-09", "0.5", "AN202401021615927958", "5.00", "0.497403"),
        ("002969.SZ", "2024-01-24", "2024-01-24", "2024-01-23", "0.23", "AN202401171617608494", "2.3000", None),
        ("600094.SH", "2024-09-11", "2024-09-11", "2024-09-10", "0.03", "AN202409031639713952", "0.03", None),
        ("600167.SH", "2024-12-27", "2024-12-27", "2024-12-26", "0.12", "AN202412191641362846", "0.12", "0.1167"),
        ("600482.SH", "2024-11-22", "2024-11-22", "2024-11-21", "0.03138", "AN202411141640887424", "0.03138", None),
        ("600519.SH", "2022-12-27", "2022-12-27", "2022-12-26", "21.91", "AN202212201581235627", "21.91", None),
        ("601985.SH", "2024-12-02", "2024-12-02", "2024-11-29", "0.02", "AN202411241641042694", "0.02", None),
        ("603285.SH", "2024-09-05", "2024-09-05", "2024-09-04", "1.0", "AN202408291639557116", "1.00", None),
    ]
    new_rows = []
    for symbol, reference, exdate, reg, cash, article, token, quote in additions:
        evidence, compact = notice(symbol, reference, article)
        assert token in compact
        new_rows.append(new_row(symbol, exdate, reg, cash, evidence, quote))
    # This notice is available as the original PDF; its first-page date table was visually checked.
    evidence = {"source_file": "sources/action_evidence_v2/600519.SH_2023-12-20/1218606528.pdf",
                "published_date": "2023-12-14", "reviewed_page": 1, "pdf_visual_review_passed": True,
                "source_text": "sources/action_evidence_v2/600519.SH_2023-12-20/1218606528.txt"}
    evidence["sha256"] = sha(evidence["source_file"])
    new_rows.append(new_row("600519.SH", "2023-12-20", "2023-12-19", "19.106", evidence, None))
    ledger = pd.concat([ledger, pd.DataFrame(new_rows)], ignore_index=True).sort_values(["symbol", "ex_date"])
    assert not ledger.duplicated(["symbol", "ex_date"]).any()
    assert len(ledger) == len(old) - 2 + 12
    assert ledger.loc[ledger.event_fields_complete, "register_date"].lt(ledger.loc[ledger.event_fields_complete, "ex_date"]).all()
    ledger.to_parquet(OUT / "dividend_event_ledger_provisional.parquet", index=False)
    ledger.loc[~ledger.event_fields_complete].to_parquet(OUT / "unresolved_event_fields.parquet", index=False)
    save(OUT / "reviewed_corrections.json", reviews)
    save(OUT / "rejected_misdated_events.json", removed)
    save(OUT / "added_issuer_dividends.json", [{"symbol": r["symbol"], "ex_date": str(r["ex_date"].date()),
                                             "cash_per_share": r["cash_per_share"], "sources": json.loads(r["v2_source_evidence"])} for r in new_rows])
    report = {"parent_version": "corporate_actions_reconciled_v1", "parent_ledger_sha256": sha("datasets/corporate_actions_reconciled_v1/dividend_event_ledger_provisional.parquet"),
              "parent_data_registration_hashes_verified": True, "original_unresolved_event_groups": 23,
              "corrected_existing_event_groups": len(reviews), "misdated_duplicate_events_removed": len(removed),
              "remaining_unresolved_event_groups": int((~ledger.event_fields_complete).sum()),
              "issuer_dividend_events_added": len(new_rows), "event_groups": len(ledger),
              "complete_event_fields": int(ledger.event_fields_complete.sum()),
              "identity_changes_used_only_for_retrospective_source_matching": True,
              "new_identity_links_not_applied_to_asof_industry_inputs": True,
              "mirror_notice_text_is_not_original_pdf_visual_verification": True,
              "complete_corporate_action_ledger": False, "economic_labels_ready": False}
    save(ROOT / "audits/action_revision_v2.json", report)
    print(json.dumps(report))


def new_row(symbol, exdate, reg, cash, evidence, quote):
    return {"symbol": symbol, "ex_date": pd.Timestamp(exdate), "register_date": pd.Timestamp(reg),
            "cash_payment_date": pd.Timestamp(exdate), "bonus_listing_date": pd.NaT,
            "cash_per_share": float(cash), "bonus_per_share": 0.0, "transfer_per_share": 0.0,
            "eastmoney_components": 0, "baostock_components": 0, "baostock_effective_components": 0,
            "equivalent_detail_rows_collapsed_with_independent_single_event_confirmation": 0,
            "manual_issuer_override": True, "quote_reference_special": False, "provider_amounts_agree": False,
            "issues": "[]", "event_fields_complete": True, "approved_for_economic_labels": False,
            "v2_reviewed_fields": True, "v2_source_evidence": json.dumps([evidence], ensure_ascii=False),
            "quote_cash_per_share": float(quote) if quote else float("nan"),
            "quote_cash_evidence_verified": quote is not None,
            "identity_mapping_is_retrospective_audit_only": False}


if __name__ == "__main__":
    main()
