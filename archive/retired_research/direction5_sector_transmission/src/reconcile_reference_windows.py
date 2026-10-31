"""Reconcile quote-reference changes over observed suspension intervals, without returns."""
from __future__ import annotations

import concurrent.futures
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/corporate_actions_reconciled_v1"


def rounded(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main():
    breaks = pd.read_parquet(ROOT / "audits/semantics_v1/breaks.parquet")
    ledger = pd.read_parquet(OUT / "dividend_event_ledger_provisional.parquet")
    rights = pd.read_parquet(ROOT / "datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet")
    calendar = pd.read_parquet(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet")
    trading_days = calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]
    market_index = {day: index for index, day in enumerate(trading_days)}
    bg = {s: g for s, g in breaks.groupby("symbol")}
    eg = {s: g.sort_values("ex_date") for s, g in ledger.groupby("symbol")}
    rg = {s: g for s, g in rights.groupby("SECUCODE")}
    empty_events = ledger.iloc[:0]
    empty_rights = rights.iloc[:0]

    def check(symbol):
        frame = pd.read_parquet(ROOT / "inputs_pre2025/kline_v1" / f"{symbol}.parquet", columns=["date", "close", "tradestatus"])
        frame["active"] = frame.tradestatus.astype(str).eq("1") & frame.close.gt(0)
        frame["previous_active_date"] = frame.date.where(frame.active).ffill().shift(1)
        previous = frame.set_index("date").previous_active_date
        available = set(frame.date)
        events = eg.get(symbol, empty_events)
        right_events = rg.get(symbol, empty_rights)
        values = []
        for source in bg[symbol].itertuples(index=False):
            start = previous.loc[source.date]
            if pd.isna(start) or start >= source.date:
                raise RuntimeError("Invalid previous-active reference interval.")
            selected = events.loc[events.ex_date.gt(start) & events.ex_date.le(source.date)]
            selected_rights = right_events.loc[right_events.ex_date.gt(start) & right_events.ex_date.le(source.date)]
            between = trading_days.iloc[market_index[start] + 1:market_index[source.date]]
            missing = len(set(between) - available)
            status = "no_known_dividend_or_rights_event"
            expected, difference = None, None
            if len(selected_rights):
                status = "rights_issue_requires_distinct_reference_and_subscription_policy"
            elif len(selected):
                if missing:
                    status = "intervening_kline_rows_missing_not_assumed_suspended"
                elif selected[["cash_per_share", "bonus_per_share", "transfer_per_share"]].isna().any().any():
                    status = "dividend_amounts_unresolved"
                elif selected.quote_reference_special.any():
                    status = "issuer_differential_distribution_reference_is_not_public_cash"
                else:
                    expected = float(source.previous_observed_active_close)
                    for event in selected.itertuples(index=False):
                        expected = rounded((expected - event.cash_per_share) / (1 + event.bonus_per_share + event.transfer_per_share))
                    difference = expected - float(source.preclose)
                    status = "generic_reference_matches_at_cent_precision" if abs(difference) < 0.000101 else "generic_reference_formula_mismatch_needs_investigation"
            values.append({"symbol": symbol, "reference_date": source.date, "previous_active_date": start,
                           "previous_active_close": source.previous_observed_active_close, "observed_preclose": source.preclose,
                           "dividend_events_in_interval": len(selected), "rights_events_in_interval": len(selected_rights),
                           "intervening_market_sessions": len(between), "intervening_missing_kline_rows": missing,
                           "matched_only_after_interval_expansion": len(selected) > 0 and not selected.ex_date.eq(source.date).any(),
                           "generic_reference_expected": expected, "generic_reference_difference": difference, "status": status})
        return values

    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for items in pool.map(check, sorted(bg)):
            records.extend(items)
    frame = pd.DataFrame(records)
    frame.to_parquet(OUT / "reference_window_reconciliation.parquet", index=False)
    frame.loc[frame.status.isin(["no_known_dividend_or_rights_event", "generic_reference_formula_mismatch_needs_investigation",
                               "intervening_kline_rows_missing_not_assumed_suspended", "dividend_amounts_unresolved"])].to_parquet(OUT / "reference_windows_needing_investigation.parquet", index=False)
    report = {"reference_candidates": len(frame), "status_counts": frame.status.value_counts().to_dict(),
              "dividend_date_or_suspension_interval_matches": int(frame.dividend_events_in_interval.gt(0).sum()),
              "rights_date_or_suspension_interval_matches": int(frame.rights_events_in_interval.gt(0).sum()),
              "additional_dividend_matches_from_suspension_intervals": int(frame.matched_only_after_interval_expansion.sum()),
              "no_assumed_trading_or_suspension_for_missing_rows": True,
              "quote_reference_checks_are_not_economic_return_labels": True,
              "complete_corporate_action_ledger": False, "economic_labels_ready": False}
    (ROOT / "audits/reference_window_reconciliation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
