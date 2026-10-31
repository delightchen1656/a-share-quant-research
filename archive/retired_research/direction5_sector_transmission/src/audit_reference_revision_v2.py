"""Recheck quote references with separately reviewed cash and reorganization evidence."""
from __future__ import annotations

import concurrent.futures
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from build_action_revision_v2 import notice, sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/corporate_actions_reconciled_v2"


def special_reviews():
    values = []
    jobs = [("000981.SZ", "2022-02-25", "1212454276", 2.10, 2),
            ("002323.SZ", "2022-01-06", "1212104022", 2.98, 1),
            ("600186.SH", "2020-01-21", "1207264232", 2.38, 2),
            ("600515.SH", "2021-12-22", "1211970832", 5.87, 2),
            ("600815.SH", "2019-12-23", "1207180289", 2.84, 1)]
    catalog = json.loads((ROOT / "sources/action_evidence_v2/catalog.json").read_text(encoding="utf-8"))
    for symbol, day, identifier, price, page in jobs:
        case = next(r for r in catalog if r["symbol"] == symbol and r["event_date"] == day)
        record = next(r for r in case["documents"] if Path(r["pdf"]).stem == identifier)
        assert sha(record["pdf"]) == record["sha256"]
        text = re.sub(r"\s+", "", (ROOT / record["text"]).read_text(encoding="utf-8"))
        assert f"{price:.2f}" in text and "转增" in text
        assert record["published_date"] <= day
        values.append({"symbol": symbol, "reference_date": day, "verified_reference_price": price,
                       "price_directly_announced": True,
                       "evidence": {**record, "reviewed_page": page, "visual_review_passed": True},
                       "business_category": "court_reorganization_capital_restructuring",
                       "retail_share_entitlement_accounting_verified": False})
    for symbol, day, article, price in [("002219.SZ", "2022-06-23", "AN202206211573714885", 2.49),
                                      ("600423.SH", "2018-12-26", "AN201812251279609209", 4.45)]:
        evidence, compact = notice(symbol, day, article)
        assert f"{price:.2f}" in compact and "转增" in compact
        values.append({"symbol": symbol, "reference_date": day, "verified_reference_price": price,
                       "price_directly_announced": True,
                       "evidence": evidence, "business_category": "court_reorganization_capital_restructuring",
                       "retail_share_entitlement_accounting_verified": False})
    # Complete single-page text responses can be reviewed even when another
    # document in the same retrieval job failed. Preserve that distinction.
    extra = [("000525.SZ", "2024-12-13", "AN202411151640921794", 9.07),
             ("000796.SZ", "2023-12-20", "AN202312191614537056", 3.93),
             ("002021.SZ", "2023-12-29", "AN202312281615161899", 2.80),
             ("002076.SZ", "2022-12-21", "AN202212191581209637", 2.23),
             ("600179.SH", "2020-12-07", "AN202012031436181679", 5.09),
             ("600306.SH", "2023-12-26", "AN202312221614829410", 8.14),
             ("600654.SH", "2022-12-23", "AN202212211581276199", 2.85),
             ("600666.SH", "2023-02-20", "AN202302161583251325", 1.79),
             ("601258.SH", "2019-12-30", "AN201912261372658558", 1.42)]
    for symbol, day, article, price in extra:
        path = f"sources/action_issuer_mirror_v2/{symbol}_{day}/{article}_content.json"
        raw = json.loads((ROOT / path).read_text(encoding="utf-8"))
        body = raw["data"]
        assert raw["success"] == 1 and body["is_ai_summary"] == 0 and int(body["page_size"]) == 1
        assert body["notice_date"][:10] <= day
        compact = re.sub(r"\s+", "", body["notice_content"])
        assert f"{price:.2f}元/股" in compact and "重整" in compact
        values.append({"symbol": symbol, "reference_date": day, "verified_reference_price": price,
                       "price_directly_announced": True,
                       "evidence": {"raw_response": path, "sha256": sha(path), "api_pages_complete": True,
                                    "pdf_visually_verified": False, "relevant_quote_paragraph_manually_reviewed": True},
                       "business_category": "court_reorganization_capital_restructuring",
                       "retail_share_entitlement_accounting_verified": False})
    directory = "sources/action_issuer_mirror_v2/002326.SZ_2019-09-30/catalog_text.json"
    case = json.loads((ROOT / directory).read_text(encoding="utf-8"))
    record = next(r for r in case["documents"] if "定向转增" in r["title"])
    evidence, compact = notice("002326.SZ", "2019-09-30", record["article_code"])
    assert all(token in compact for token in ("61,533,442", "817,463,027", "2019年9月30日", "1.206188"))
    values.append({"symbol": "002326.SZ", "reference_date": "2019-09-30",
                   "verified_reference_price": rounded(9.66 / (1 + 61533442 / 817463027)),
                   "price_directly_announced": False,
                   "source_formula": "previous_close / (1 + 61533442 / 817463027)",
                   "ordinary_investor_share_ratio_differs_from_total_capital_ratio": True,
                   "evidence": evidence, "business_category": "directed_capital_transfer_performance_compensation",
                   "retail_share_entitlement_accounting_verified": False})
    (OUT / "special_reference_reviews.json").write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return {(r["symbol"], pd.Timestamp(r["reference_date"])): r for r in values}


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main():
    breaks = pd.read_parquet(ROOT / "audits/semantics_v1/breaks.parquet")
    ledger = pd.read_parquet(OUT / "dividend_event_ledger_provisional.parquet")
    rights = pd.read_parquet(ROOT / "datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet")
    calendar = pd.read_parquet(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet")
    days = calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]
    index = {day: n for n, day in enumerate(days)}
    bg = {s: g for s, g in breaks.groupby("symbol")}
    eg = {s: g.sort_values("ex_date") for s, g in ledger.groupby("symbol")}
    rg = {s: g for s, g in rights.groupby("SECUCODE")}
    specials = special_reviews()

    def check(symbol):
        frame = pd.read_parquet(ROOT / f"inputs_pre2025/kline_v1/{symbol}.parquet", columns=["date", "close", "tradestatus"])
        active = frame.tradestatus.astype(str).eq("1") & frame.close.gt(0)
        frame["previous_active_date"] = frame.date.where(active).ffill().shift(1)
        previous = frame.set_index("date").previous_active_date
        available = set(frame.date)
        events, right_events = eg.get(symbol, ledger.iloc[:0]), rg.get(symbol, rights.iloc[:0])
        records = []
        for source in bg[symbol].itertuples(index=False):
            start = previous.loc[source.date]
            assert pd.notna(start) and start < source.date
            selected = events.loc[events.ex_date.gt(start) & events.ex_date.le(source.date)]
            selected_rights = right_events.loc[right_events.ex_date.gt(start) & right_events.ex_date.le(source.date)]
            between = days.iloc[index[start] + 1:index[source.date]]
            missing = len(set(between) - available)
            status, expected, difference = "no_known_dividend_or_rights_event", None, None
            quote_cash_used = False
            special = specials.get((symbol, source.date))
            if special:
                expected = special["verified_reference_price"]
                difference = expected - float(source.preclose)
                assert abs(difference) < 0.000101
                status = ("issuer_reorganization_reference_matches_entitlement_accounting_pending"
                          if special["business_category"] == "court_reorganization_capital_restructuring" else
                          "issuer_directed_transfer_reference_matches_entitlement_accounting_pending")
            elif len(selected_rights):
                status = "rights_issue_requires_distinct_reference_and_subscription_policy"
            elif len(selected):
                if missing:
                    status = "intervening_kline_rows_missing_not_assumed_suspended"
                elif selected[["cash_per_share", "bonus_per_share", "transfer_per_share"]].isna().any().any():
                    status = "dividend_amounts_unresolved"
                elif (selected.quote_reference_special & ~selected.quote_cash_evidence_verified).any():
                    status = "issuer_differential_distribution_reference_is_not_public_cash"
                else:
                    expected = float(source.previous_observed_active_close)
                    for event in selected.itertuples(index=False):
                        cash = event.quote_cash_per_share if event.quote_cash_evidence_verified else event.cash_per_share
                        quote_cash_used |= bool(event.quote_cash_evidence_verified)
                        expected = rounded((expected - cash) / (1 + event.bonus_per_share + event.transfer_per_share))
                    difference = expected - float(source.preclose)
                    if abs(difference) < 0.000101:
                        status = "issuer_weighted_reference_matches_at_cent_precision" if quote_cash_used else "generic_reference_matches_at_cent_precision"
                    else:
                        status = "generic_reference_formula_mismatch_needs_investigation"
            records.append({"symbol": symbol, "reference_date": source.date, "previous_active_date": start,
                            "previous_active_close": source.previous_observed_active_close, "observed_preclose": source.preclose,
                            "dividend_events_in_interval": len(selected), "rights_events_in_interval": len(selected_rights),
                            "intervening_market_sessions": len(between), "intervening_missing_kline_rows": missing,
                            "quote_cash_separated_from_public_shareholder_cash": quote_cash_used,
                            "generic_reference_expected": expected, "generic_reference_difference": difference, "status": status})
        return records
    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for rows in pool.map(check, sorted(bg)):
            records.extend(rows)
    frame = pd.DataFrame(records)
    frame.to_parquet(OUT / "reference_window_reconciliation.parquet", index=False)
    unresolved = frame.status.isin(["no_known_dividend_or_rights_event", "generic_reference_formula_mismatch_needs_investigation",
                                   "intervening_kline_rows_missing_not_assumed_suspended", "dividend_amounts_unresolved"])
    frame.loc[unresolved].to_parquet(OUT / "reference_windows_needing_investigation.parquet", index=False)
    previous = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v1/reference_window_reconciliation.parquet")
    transitions = previous[["symbol", "reference_date", "status"]].merge(frame[["symbol", "reference_date", "status"]],
                                                                       on=["symbol", "reference_date"], suffixes=["_v1", "_v2"], validate="one_to_one")
    assert len(transitions) == len(previous) == len(frame) == 15913
    transitions.loc[transitions.status_v1.ne(transitions.status_v2)].to_parquet(OUT / "reference_status_changes.parquet", index=False)
    report = {"reference_candidates": len(frame), "status_counts": frame.status.value_counts().to_dict(),
              "old_unknown_reference_candidates": int(previous.status.eq("no_known_dividend_or_rights_event").sum()),
              "remaining_unknown_reference_candidates": int(frame.status.eq("no_known_dividend_or_rights_event").sum()),
              "issuer_special_quote_cases_verified": len(specials),
              "issuer_reorganization_quote_cases_verified": sum(r["business_category"] == "court_reorganization_capital_restructuring" for r in specials.values()),
              "issuer_directed_transfer_quote_cases_verified": sum(r["business_category"] == "directed_capital_transfer_performance_compensation" for r in specials.values()),
              "quote_reference_validation_is_not_entitlement_or_account_return_validation": True,
              "raw_kline_values_changed": False, "economic_labels_ready": False}
    (ROOT / "audits/reference_window_reconciliation_v2.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
