"""Stage 6-8 diagnostics only: units, reference-price breaks and status integrity."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CUTOFF = pd.Timestamp("2024-12-31")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_one(item):
    path = ROOT / CONFIG["snapshot"] / item["snapshot_file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != item["snapshot_sha256"]:
        raise RuntimeError(f"Snapshot changed: {path.name}")
    df = pd.read_parquet(path)
    if df.date.isna().any() or df.date.max() > CUTOFF or df.date.duplicated().any() or not df.date.is_monotonic_increasing:
        raise RuntimeError(f"Date audit failed: {path.name}")
    active = df.tradestatus.astype(str).eq("1")
    status_unknown = ~df.tradestatus.astype(str).isin(["0", "1"])
    st_unknown = ~df.isST.astype(str).isin(["0", "1"])
    numeric_cols = ["open", "high", "low", "close", "preclose", "volume", "amount", "turn", "pctChg"]
    num = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    price_ok = num[["open", "high", "low", "close"]].gt(0).all(axis=1)
    nonfinite = ~np.isfinite(num).all(axis=1)
    positive_trades = active & price_ok & num.volume.gt(0) & num.amount.gt(0)
    vwap = num.amount / num.volume.where(num.volume.gt(0))
    eps = 0.010001  # diagnostic tolerance; do not silently alter data using this threshold
    inside = vwap.ge(num.low - eps) & vwap.le(num.high + eps)
    inside_strict = vwap.ge(num.low - 0.000101) & vwap.le(num.high + 0.000101)
    inside_if_lots = (vwap / 100).ge(num.low - eps) & (vwap / 100).le(num.high + eps)
    outliers = positive_trades & ~inside
    previous_active_close = num.close.where(active & num.close.gt(0)).ffill().shift(1)
    comparable = active & num.preclose.gt(0) & previous_active_close.gt(0)
    ref_break = comparable & (num.preclose - previous_active_close).abs().gt(0.0001001)
    quote_return = 100 * (num.close / num.preclose.where(num.preclose.gt(0)) - 1)
    error = (quote_return - num.pctChg).abs()
    pct_mismatch = active & num.preclose.gt(0) & error.gt(0.000101)
    breaks = df.loc[ref_break, ["date", "code", "close", "preclose", "pctChg"]].copy()
    breaks["previous_observed_active_close"] = previous_active_close[ref_break]
    breaks["signal"] = "reference_price_discontinuity_not_a_verified_corporate_action"
    breaks["symbol"] = item["symbol"]
    bad = df.loc[outliers, ["date", "code", "open", "high", "low", "close", "volume", "amount"]].copy()
    bad["amount_over_volume"] = vwap[outliers]
    bad["symbol"] = item["symbol"]
    strict_bad = df.loc[positive_trades & ~inside_strict, ["date", "code", "low", "high", "volume", "amount"]].copy()
    strict_bad["amount_over_volume"] = vwap[positive_trades & ~inside_strict]
    strict_bad["symbol"] = item["symbol"]
    pct_bad = df.loc[pct_mismatch, ["date", "code", "close", "preclose", "pctChg"]].copy()
    pct_bad["computed_quote_return_percent"] = quote_return[pct_mismatch]
    pct_bad["error_percentage_points"] = error[pct_mismatch]
    pct_bad["symbol"] = item["symbol"]
    return {
        "symbol": item["symbol"], "rows": len(df), "active_rows": int(active.sum()),
        "positive_trade_rows": int(positive_trades.sum()),
        "vwap_within_range_as_shares": int((positive_trades & inside).sum()),
        "vwap_within_range_strict": int((positive_trades & inside_strict).sum()),
        "vwap_within_range_if_lots": int((positive_trades & inside_if_lots).sum()),
        "active_rows_without_positive_volume_or_amount": int((active & ~positive_trades).sum()),
        "nonfinite_numeric_rows": int(nonfinite.sum()),
        "active_nonfinite_numeric_rows": int((active & nonfinite).sum()),
        "suspended_nonfinite_numeric_rows": int((~active & nonfinite).sum()),
        "unknown_tradestatus_rows": int(status_unknown.sum()), "unknown_st_rows": int(st_unknown.sum()),
        "negative_turn_rows": int(num.turn.lt(0).sum()),
        "reference_price_breaks": int(ref_break.sum()), "quote_return_mismatches": int(pct_mismatch.sum()),
        "breaks": breaks, "vwap_outliers": bad, "vwap_strict_diagnostics": strict_bad, "pct_mismatches": pct_bad,
    }


def main():
    snapshot = ROOT / CONFIG["snapshot"]
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert pd.Timestamp(manifest["cutoff"]) <= CUTOFF
    output = ROOT / "audits/semantics_v1"
    output.mkdir(parents=True, exist_ok=True)
    result = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for value in pool.map(check_one, manifest["files"]):
            result.append(value)
    frame_keys = ["breaks", "vwap_outliers", "vwap_strict_diagnostics", "pct_mismatches"]
    for key in frame_keys:
        frames = [r[key] for r in result if not r[key].empty]
        frame = pd.concat(frames, ignore_index=True) if frames else result[0][key].copy()
        frame.to_parquet(output / f"{key}.parquet", index=False)
    scalars = [{k: v for k, v in r.items() if k not in frame_keys} for r in result]
    pd.DataFrame(scalars).to_parquet(output / "per_symbol.parquet", index=False)
    sum_keys = [key for key in scalars[0] if key != "symbol"]
    totals = {key: sum(r[key] for r in scalars) for key in sum_keys}
    totals["files"] = len(result)
    totals["share_unit_vwap_consistency"] = totals["vwap_within_range_as_shares"] / totals["positive_trade_rows"]
    totals["lot_unit_vwap_consistency"] = totals["vwap_within_range_if_lots"] / totals["positive_trade_rows"]
    report = {
        "cutoff": str(CUTOFF.date()), "stage": "6_to_8_data_semantics", "totals": totals,
        "unit_contract": {"price": "CNY_per_share", "volume": "shares", "amount": "CNY", "turn": "percent", "pctChg": "percent", "adjustflag": "3_unadjusted"},
        "documentation": "sources/vendor_documentation/stockKData.md",
        "numeric_checks_are_unit_consistency_evidence_not_independent_vendor_lineage_proof": True,
        "reference_price_break_interpretation": "possible_ex_right_reference_or_correction; not an event ledger and not direct shareholder economic returns",
        "unusual_rows_policy": "preserve and investigate; no automatic deletion, price adjustment or fabricated corporate action",
        "corporate_action_economic_returns_ready": False, "factor_experiments_enabled": False,
        "model_experiments_enabled": False, "account_backtest_enabled": False,
        "outputs": {key: str((output / f"{key}.parquet").relative_to(ROOT)) for key in frame_keys}
    }
    save(output / "summary.json", report)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
