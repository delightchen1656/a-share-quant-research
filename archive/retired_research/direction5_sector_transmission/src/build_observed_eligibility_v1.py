"""Build causal, observed-row entry rule flags; no returns, factors or rankings."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
START, END = pd.Timestamp("2018-01-01"), pd.Timestamp("2023-12-31")
BUILD = ROOT / "datasets/eligibility_observed_dev_v1_building"
TARGET = ROOT / "inputs_pre2025/eligibility_observed_dev_v1"
REASONS = {1: "signal_day_not_active", 2: "signal_day_ST_or_unknown_ST", 4: "invalid_signal_day_OHLC_volume_amount",
           8: "fewer_than_120_observed_valid_active_bars", 16: "industry_unknown_in_latest_available_whole_publication",
           32: "outside_registered_mainboard_prefixes"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Rules:
    def __init__(self):
        self.protocol = read(ROOT / "research_protocol_v1.json")
        registration = read(ROOT / "audits/protocol_v1_registration.json")
        assert sha(ROOT / "research_protocol_v1.json") == registration["protocol_sha256"]
        self.minimum = self.protocol["scope"]["new_entry_filters"]["minimum_observed_active_bars_before_or_on_signal_date"]
        assert self.minimum == 120
        self.prefixes = tuple(self.protocol["scope"]["symbol_prefixes"])
        self.kroot = ROOT / "inputs_pre2025/kline_v1"
        self.kmanifest = read(self.kroot / "manifest.json")
        iroot = ROOT / "inputs_pre2025/industry_official_v1"
        im = read(iroot / "manifest.json")
        assert sha(iroot / im["file"]) == im["sha256"]
        self.history = pd.read_parquet(iroot / im["file"])
        self.history["published_date"] = pd.to_datetime(self.history["published_date"])
        self.history["knowledge_start"] = pd.to_datetime(self.history["knowledge_start"])
        self.history = self.history.loc[self.history.knowledge_start.le(END)].copy()
        self.publications = self.history[["source_id", "published_date", "knowledge_start"]].drop_duplicates().sort_values("knowledge_start")
        assert not self.publications.knowledge_start.duplicated().any()
        self.starts = self.publications.knowledge_start.to_numpy()
        self.sources = self.publications.source_id.to_numpy()
        self.members = self.history[["source_id", "symbol", "industry_code", "classification_system", "published_date", "knowledge_start"]].copy()
        assert not self.members.duplicated(["source_id", "symbol"]).any()
        identity_root = ROOT / "inputs_pre2025/security_identity_v1"
        identities = read(identity_root / "manifest.json")
        for item in identities["files"]:
            assert sha(identity_root / item["file"]) == item["sha256"]
        self.links = pd.read_parquet(identity_root / "identity_links.parquet")
        self.calendar = pd.read_parquet(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet")
        cm = read(ROOT / "inputs_pre2025/trading_calendar_v1/manifest.json")
        assert sha(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet") == cm["sha256"]
        self.days = set(self.calendar.loc[self.calendar.is_trading_day.eq(1) & self.calendar.calendar_date.between(START, END), "calendar_date"])

    def transform(self, symbol, frame):
        frame = frame.loc[frame.date.between(START, END)].sort_values("date").copy()
        if frame.empty:
            return None
        assert not frame.date.duplicated().any() and set(frame.date).issubset(self.days)
        numeric = frame[["open", "high", "low", "close", "volume", "amount"]].apply(pd.to_numeric, errors="coerce")
        good = pd.Series(np.isfinite(numeric.to_numpy()).all(axis=1), index=frame.index) & numeric.gt(0).all(axis=1)
        active = frame.tradestatus.astype(str).eq("1")
        not_st = frame.isST.astype(str).eq("0")
        count = (good & active).cumsum().astype("int32")
        pos = np.searchsorted(self.starts, frame.date.to_numpy(), side="right") - 1
        source_ids = np.where(pos >= 0, self.sources[np.maximum(pos, 0)], None)
        result = pd.DataFrame({"date": frame.date.to_numpy(), "symbol": symbol,
                               "signal_day_active": active.to_numpy(), "signal_day_not_ST": not_st.to_numpy(),
                               "signal_day_numeric_valid": good.to_numpy(), "observed_valid_active_bars": count.to_numpy(),
                               "source_id": source_ids})
        result = result.merge(self.members, on=["symbol", "source_id"], how="left", validate="many_to_one", sort=False)
        result["industry_identity_repair_used"] = False
        for link in self.links.loc[self.links.storage_symbol.eq(symbol)].itertuples():
            allowed = result.date.ge(link.asof_join_knowledge_start) & result.date.ge(link.effective_date)
            prior = self.members.loc[self.members.symbol.eq(link.old_symbol)].drop(columns="symbol").set_index("source_id")
            for column in ["industry_code", "classification_system", "published_date", "knowledge_start"]:
                mapped = result.source_id.map(prior[column])
                both = allowed & result[column].notna() & mapped.notna()
                if column == "industry_code":
                    assert result.loc[both, column].eq(mapped.loc[both]).all()
                missing = allowed & result[column].isna() & mapped.notna()
                result.loc[missing, column] = mapped.loc[missing]
                result.loc[missing, "industry_identity_repair_used"] = True
        known = result.industry_code.notna()
        assert result.loc[known, "knowledge_start"].le(result.loc[known, "date"]).all()
        assert result.loc[known, "published_date"].lt(result.loc[known, "date"]).all()
        result["history_rule_pass"] = result.observed_valid_active_bars.ge(self.minimum)
        result["industry_known"] = known
        result["industry_publication_age_days"] = (result.date - result.published_date).dt.days.astype("Int32")
        flags = ((~result.signal_day_active).astype("uint16")
                 + 2 * (~result.signal_day_not_ST).astype("uint16")
                 + 4 * (~result.signal_day_numeric_valid).astype("uint16")
                 + 8 * (~result.history_rule_pass).astype("uint16")
                 + 16 * (~known).astype("uint16")
                 + (0 if symbol.startswith(self.prefixes) else 32))
        result["failure_bits"] = flags.astype("uint16")
        result["observed_entry_rules_pass"] = result.failure_bits.eq(0)
        return result

    def load(self, record):
        path = self.kroot / record["snapshot_file"]
        assert sha(path) == record["snapshot_sha256"]
        return self.transform(record["symbol"], pd.read_parquet(path))


SCHEMA = pa.schema([
    ("date", pa.timestamp("ns")), ("symbol", pa.string()), ("signal_day_active", pa.bool_()),
    ("signal_day_not_ST", pa.bool_()), ("signal_day_numeric_valid", pa.bool_()),
    ("observed_valid_active_bars", pa.int32()), ("source_id", pa.string()), ("industry_code", pa.string()),
    ("classification_system", pa.string()), ("published_date", pa.timestamp("ns")), ("knowledge_start", pa.timestamp("ns")),
    ("industry_identity_repair_used", pa.bool_()), ("history_rule_pass", pa.bool_()), ("industry_known", pa.bool_()),
    ("industry_publication_age_days", pa.int32()), ("failure_bits", pa.uint16()), ("observed_entry_rules_pass", pa.bool_())])


def validate_causality(rules):
    checks = []
    for symbol in ("600000.SH", "601360.SH", "001872.SZ"):
        frame = pd.read_parquet(rules.kroot / f"{symbol}.parquet")
        complete = rules.transform(symbol, frame)
        cut = pd.Timestamp("2020-06-30")
        prefix = rules.transform(symbol, frame.loc[frame.date.le(cut)])
        pd.testing.assert_frame_equal(prefix.reset_index(drop=True), complete.loc[complete.date.le(cut)].reset_index(drop=True))
        checks.append({"symbol": symbol, "adding_later_rows_does_not_change_earlier_flags": True})
    # Actual trading dates surrounding the sidecar's knowledge boundary.
    frame = pd.read_parquet(rules.kroot / "601360.SH.parquet")
    actual = rules.transform("601360.SH", frame)
    assert not actual.loc[actual.date.lt(pd.Timestamp("2018-04-28")), "industry_identity_repair_used"].any()
    assert actual.date.eq("2018-05-02").sum() == 1
    assert actual.loc[actual.date.eq("2018-05-02"), "industry_identity_repair_used"].all()
    sample = rules.transform("600000.SH", pd.read_parquet(rules.kroot / "600000.SH.parquet"))
    assert not sample.loc[sample.observed_valid_active_bars.lt(120), "history_rule_pass"].any()
    assert sample.observed_valid_active_bars.eq(120).sum() >= 1
    assert sample.loc[sample.observed_valid_active_bars.eq(120), "history_rule_pass"].all()
    return {"prefix_invariance_checks": checks, "identity_confirmation_boundary_checked": True,
            "history_119_120_boundary_checked": True,
            "holdout_2024_not_materialized": True, "no_return_or_factor_columns": True}


def main(resume_finalize=False):
    if TARGET.exists() or (BUILD.exists() and not resume_finalize):
        raise RuntimeError("Preserve existing output; use a new version or inspect an incomplete build.")
    rules = Rules()
    tests = validate_causality(rules)
    if resume_finalize:
        checks = read(ROOT / "audits/eligibility_observed_dev_v1_checks.json")
        assert checks["source_snapshot_file_hashes_verified"] == len(rules.kmanifest["files"])
        assert checks["rows_reconciled_to_daily_counts"]
        daily = [pd.read_parquet(BUILD / "daily_counts.parquet").set_index("date")]
        years = [int(p.stem) for p in BUILD.glob("[0-9][0-9][0-9][0-9].parquet")]
        assert sorted(years) == list(range(2018, 2024))
        finish(rules, tests, int(daily[0].observed_rows.sum()), daily, years)
        return
    BUILD.mkdir(parents=True)
    writers, daily, rows, symbols, repair_count = {}, [], 0, set(), 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            records = rules.kmanifest["files"]
            for offset in range(0, len(records), 64):
                frames = [v for v in pool.map(rules.load, records[offset:offset+64]) if v is not None]
                if not frames:
                    continue
                combined = pd.concat(frames, ignore_index=True)
                rows += len(combined)
                symbols.update(combined.symbol.unique())
                repair_count += int(combined.industry_identity_repair_used.sum())
                counts = combined.groupby("date").agg(observed_rows=("symbol", "size"), candidates=("observed_entry_rules_pass", "sum"))
                for bit in REASONS:
                    counts[f"failure_bit_{bit}"] = combined.failure_bits.map(lambda v: bool(v & bit)).groupby(combined.date).sum()
                daily.append(counts)
                for year, group in combined.groupby(combined.date.dt.year):
                    year = int(year)
                    if year not in writers:
                        writers[year] = pq.ParquetWriter(BUILD / f"{year}.parquet", SCHEMA, compression="zstd")
                    writers[year].write_table(pa.Table.from_pandas(group[SCHEMA.names], schema=SCHEMA, preserve_index=False))
                if offset % 512 == 0:
                    print(json.dumps({"files_processed": min(offset+64, len(records)), "observed_rows": rows}), flush=True)
    finally:
        for writer in writers.values():
            writer.close()
    finish(rules, tests, rows, daily, list(writers))


def finish(rules, tests, rows, daily, years):
    totals = pd.concat(daily).groupby(level=0).sum().sort_index()
    totals.reset_index().to_parquet(BUILD / "daily_counts.parquet", index=False)
    files, verified_rows, yearly = [], 0, []
    symbols, repair_count = set(), 0
    for year in sorted(years):
        path = BUILD / f"{year}.parquet"
        frame = pd.read_parquet(path)
        assert frame.date.dt.year.eq(year).all() and frame.date.le(END).all()
        assert not frame.duplicated(["date", "symbol"]).any()
        assert frame.observed_entry_rules_pass.eq(frame.failure_bits.eq(0)).all()
        assert not frame.loc[frame.observed_entry_rules_pass, "industry_code"].isna().any()
        verified_rows += len(frame)
        symbols.update(frame.symbol.unique())
        repair_count += int(frame.industry_identity_repair_used.sum())
        yearly.append({"year": year, "observed_rows": len(frame), "candidate_rows": int(frame.observed_entry_rules_pass.sum()),
                       "stocks_with_any_candidate_day": int(frame.loc[frame.observed_entry_rules_pass, "symbol"].nunique())})
        files.append({"file": path.name, "sha256": sha(path), "rows": len(frame)})
    assert verified_rows == rows == int(totals.observed_rows.sum())
    counts_file = BUILD / "daily_counts.parquet"
    files.append({"file": counts_file.name, "sha256": sha(counts_file), "rows": len(totals)})
    tests.update({"source_snapshot_file_hashes_verified": len(rules.kmanifest["files"]),
                  "output_row_identity_checks_passed": True, "rows_reconciled_to_daily_counts": True})
    save(ROOT / "audits/eligibility_observed_dev_v1_checks.json", tests)
    summary = {"scope": "observed_Kline_rows_only_not_complete_historical_security_universe", "start": "2018-01-01", "end": "2023-12-31",
               "observed_rows": rows, "observed_symbols": len(symbols), "market_dates_with_observed_rows": len(totals),
               "candidate_rows": int(totals.candidates.sum()),
               "first_candidate_date": str(totals.loc[totals.candidates.gt(0)].index.min().date()),
               "candidate_stock_count_daily_min_after_first_candidate": int(totals.loc[totals.index >= totals.loc[totals.candidates.gt(0)].index.min(), "candidates"].min()),
               "candidate_stock_count_daily_max": int(totals.candidates.max()),
               "identity_sidecar_repaired_rows": repair_count, "yearly": yearly, "files": files,
               "failure_bits": REASONS, "failure_counts_can_overlap": True,
               "source_manifests": [{"path": p, "sha256": sha(ROOT / p)} for p in
                                    ["inputs_pre2025/kline_v1/manifest.json", "inputs_pre2025/industry_official_v1/manifest.json",
                                     "inputs_pre2025/security_identity_v1/manifest.json", "inputs_pre2025/trading_calendar_v1/manifest.json"]],
               "protocol_sha256": sha(ROOT / "research_protocol_v1.json"),
               "historical_delisting_not_used_as_filter": True, "missing_Kline_rows_not_filled_or_assumed_suspended": True,
               "company_action_future_knowledge_not_used_as_entry_filter": True,
               "industry_publication_age_not_used_as_filter": True, "listing_age_not_inferred_from_observed_bar_count": True,
               "liquidity_capacity_and_execution_limits_not_yet_applied": True,
               "rules_panel_ready": True, "final_tradable_universe_ready": False,
               "labels_ready": False, "factor_experiments_enabled": False, "ranked_stock_selection_ready": False,
               "approved_scope": "audited_derived_point_in_time_qualification_flags_only",
               "code_sha256": sha(Path(__file__)), "tests": tests}
    save(BUILD / "manifest.json", summary)
    assert BUILD.resolve().is_relative_to(ROOT.resolve()) and TARGET.resolve().is_relative_to(ROOT.resolve())
    BUILD.rename(TARGET)
    save(ROOT / "audits/eligibility_observed_dev_v1.json", summary)
    config = read(ROOT / "config.json")
    config["observed_eligibility_development_snapshot"] = str(TARGET.relative_to(ROOT)).replace("\\", "/")
    config["daily_observed_rules_panel_ready"] = True
    save(ROOT / "config.json", config)
    print(json.dumps({k:v for k,v in summary.items() if k in ("observed_rows", "observed_symbols", "candidate_rows", "first_candidate_date", "yearly", "final_tradable_universe_ready", "factor_experiments_enabled")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-finalize", action="store_true")
    main(parser.parse_args().resume_finalize)
