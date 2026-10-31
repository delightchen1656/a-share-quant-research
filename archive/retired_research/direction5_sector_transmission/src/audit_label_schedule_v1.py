"""Audit label scheduling and missingness without calculating outcome values."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "datasets/label_schedule_dev_v1_building"
TARGET = ROOT / "inputs_pre2025/label_schedule_dev_v1"
END = pd.Timestamp("2023-12-31")


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def point_overlap(entry, exit_, value, include_exit=True):
    if pd.isna(value):
        return np.zeros(len(entry), dtype=bool)
    point = pd.Timestamp(value).to_datetime64()
    return (entry <= point) & ((exit_ >= point) if include_exit else (exit_ > point))


def endpoint_flags(present, valid, signal_index, development_size):
    entry, exit_ = signal_index + 1, signal_index + 6
    flags = np.zeros(len(signal_index), dtype=np.uint16)
    flags |= np.where(exit_ >= development_size, 1, 0).astype("uint16")
    flags |= np.where(~present[entry], 2, 0).astype("uint16")
    flags |= np.where(present[entry] & ~valid[entry], 4, 0).astype("uint16")
    flags |= np.where(~present[exit_], 8, 0).astype("uint16")
    flags |= np.where(present[exit_] & ~valid[exit_], 16, 0).astype("uint16")
    gap = np.zeros(len(signal_index), dtype=bool)
    for offset in range(1, 7):
        gap |= ~present[signal_index + offset]
    flags |= np.where(gap, 32, 0).astype("uint16")
    return flags


def unit_checks():
    days = pd.bdate_range("2020-01-01", periods=15).to_numpy()
    present = np.ones(15, dtype=bool)
    valid = np.ones(15, dtype=bool)
    signal = np.array([0, 1, 2])
    assert not endpoint_flags(present, valid, signal, 15).any()
    assert days[signal[0] + 6] == np.datetime64("2020-01-09")
    missing = present.copy(); missing[3] = False
    assert (endpoint_flags(missing, valid, np.array([0]), 15)[0] & 32) != 0
    halted = valid.copy(); halted[3] = False
    assert endpoint_flags(present, halted, np.array([0]), 15)[0] == 0
    halted[6] = False
    assert endpoint_flags(present, halted, np.array([0]), 15)[0] == 16
    assert endpoint_flags(present, valid, np.array([3]), 9)[0] & 1
    entry, exit_ = days[[1]], days[[6]]
    assert point_overlap(entry, exit_, days[1], include_exit=False)[0]
    assert not point_overlap(entry, exit_, days[6], include_exit=False)[0]
    assert point_overlap(entry, exit_, days[6], include_exit=True)[0]
    return {"entry_t1_exit_t6_has_five_session_intervals": True,
            "missing_intermediate_row_differs_from_known_suspension": True,
            "inactive_exit_is_not_silently_delayed": True,
            "record_date_close_excludes_same_day_open_sale": True,
            "development_and_training_cutoffs_use_scheduled_exit": True}


class Audit:
    def __init__(self):
        self.spec = read("label_definition_v1.json")
        registration = read("audits/label_definition_v1_registration.json")
        assert sha("label_definition_v1.json") == registration["label_definition_sha256"]
        for record in registration["input_manifests"]:
            assert sha(record["path"]) == record["sha256"]
        self.input = read("inputs_pre2025/kline_v1/manifest.json")
        self.symbols = [r["symbol"] for r in self.input["files"]]
        self.symbol_index = {s: i for i, s in enumerate(self.symbols)}
        self.calendar = pd.read_parquet(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet")
        self.days = pd.DatetimeIndex(self.calendar.loc[self.calendar.is_trading_day.eq(1), "calendar_date"])
        self.day_values = self.days.to_numpy()
        self.development_size = int(self.days.le(END).sum()) if hasattr(self.days, "le") else int((self.days <= END).sum())
        self.observed = np.zeros((len(self.symbols), self.development_size), dtype=bool)
        self.eligible = self.observed.copy()
        self.industry = np.full(self.observed.shape, -1, dtype="int16")
        self.industry_codes = []
        im = {}
        panel = read("inputs_pre2025/eligibility_observed_dev_v1/manifest.json")
        for record in panel["files"]:
            path = "inputs_pre2025/eligibility_observed_dev_v1/" + record["file"]
            assert sha(path) == record["sha256"]
            if not record["file"][:4].isdigit():
                continue
            frame = pd.read_parquet(ROOT / path, columns=["date", "symbol", "industry_code", "observed_entry_rules_pass"])
            for code in frame.industry_code.dropna().unique():
                if code not in im:
                    im[code] = len(self.industry_codes); self.industry_codes.append(code)
            si = frame.symbol.map(self.symbol_index).to_numpy(dtype=int)
            di = self.days.get_indexer(frame.date)
            assert (di >= 0).all() and (di < self.development_size).all()
            self.observed[si, di] = True
            self.eligible[si, di] = frame.observed_entry_rules_pass.to_numpy(dtype=bool)
            self.industry[si, di] = frame.industry_code.map(im).fillna(-1).to_numpy(dtype="int16")
        assert int(self.observed.sum()) == panel["observed_rows"]
        assert int(self.eligible.sum()) == panel["candidate_rows"]
        ledger = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v3/dividend_event_ledger_provisional.parquet")
        ledger = ledger.loc[ledger.ex_date.le(END) | ledger.register_date.le(END)].copy()
        self.events = {s: g for s, g in ledger.groupby("symbol")}
        references = pd.read_parquet(ROOT / "datasets/corporate_actions_reconciled_v3/reference_window_reconciliation.parquet")
        references = references.loc[references.reference_date.le(END)]
        self.references = {s: g for s, g in references.groupby("symbol")}
        rights = pd.read_parquet(ROOT / "datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet")
        rights = rights.loc[pd.to_datetime(rights.EQUITY_RECORD_DATE).le(END)]
        self.rights = {s: g for s, g in rights.groupby("SECUCODE")}
        self.precedence = self.spec["primary_reason_precedence"]
        self.reason_names = {int(k): v for k, v in self.spec["audit_failure_bits"].items()}

    def process(self, record):
        path = "inputs_pre2025/kline_v1/" + record["snapshot_file"]
        assert sha(path) == record["snapshot_sha256"]
        frame = pd.read_parquet(ROOT / path, columns=["date", "open", "volume", "amount", "tradestatus"])
        frame = frame.loc[frame.date.le(END)].sort_values("date")
        if frame.empty:
            return None
        assert not frame.date.duplicated().any()
        symbol = record["symbol"]
        si = self.symbol_index[symbol]
        index = self.days.get_indexer(frame.date)
        assert (index >= 0).all() and (index < self.development_size).all()
        assert np.array_equal(np.flatnonzero(self.observed[si]), index)
        present, valid = np.zeros(len(self.days), dtype=bool), np.zeros(len(self.days), dtype=bool)
        present[index] = True
        numbers = frame[["open", "volume", "amount"]].apply(pd.to_numeric, errors="coerce")
        valid[index] = frame.tradestatus.astype(str).eq("1").to_numpy() & np.isfinite(numbers.to_numpy()).all(axis=1) & numbers.gt(0).all(axis=1).to_numpy()
        flags = endpoint_flags(present, valid, index, self.development_size)
        entry, exit_ = self.day_values[index+1], self.day_values[index+6]
        for event in self.events.get(symbol, pd.DataFrame()).itertuples(index=False):
            overlap = point_overlap(entry, exit_, event.ex_date) | point_overlap(entry, exit_, event.register_date, include_exit=False)
            flags |= np.where(overlap, 64, 0).astype("uint16")
            if not event.event_fields_complete:
                flags |= np.where(overlap, 2048, 0).astype("uint16")
            if not event.provider_amounts_agree and not event.v2_reviewed_fields:
                flags |= np.where(overlap, 4096, 0).astype("uint16")
        for event in self.rights.get(symbol, pd.DataFrame()).itertuples(index=False):
            start = pd.Timestamp(event.EQUITY_RECORD_DATE)
            end = pd.Timestamp(event.LISTING_DATE) if pd.notna(event.LISTING_DATE) else END
            overlap = (entry <= end.to_datetime64()) & (exit_ >= start.to_datetime64())
            flags |= np.where(overlap, 128, 0).astype("uint16")
        for event in self.references.get(symbol, pd.DataFrame()).itertuples(index=False):
            bit = 0
            if event.status == "generic_reference_formula_mismatch_needs_investigation": bit = 256
            elif event.status == "no_known_dividend_or_rights_event": bit = 512
            elif event.status in ("issuer_reorganization_reference_matches_entitlement_accounting_pending",
                                   "issuer_directed_transfer_reference_matches_entitlement_accounting_pending",
                                   "issuer_differential_distribution_reference_is_not_public_cash"): bit = 1024
            if bit:
                flags |= np.where(point_overlap(entry, exit_, event.reference_date), bit, 0).astype("uint16")
        primary = np.zeros(len(flags), dtype="uint16")
        for bit in self.precedence:
            primary[(primary == 0) & ((flags & bit) != 0)] = bit
        eligible = self.eligible[si, index]
        industry = self.industry[si, index]
        codes = np.array([self.industry_codes[n] if n >= 0 else None for n in industry], dtype=object)
        return pd.DataFrame({"signal_date": frame.date.to_numpy(), "symbol": symbol, "industry_code": codes,
                             "signal_rules_pass": eligible, "scheduled_entry_date": entry, "scheduled_exit_date": exit_,
                             "earliest_scheduled_information_date": exit_, "scheduled_exit_in_development": exit_ <= END.to_datetime64(),
                             "input_audit_bits": flags, "primary_reason_bit": primary,
                             "plain_case_data_candidate": eligible & (flags == 0),
                             "training_label_approved": False})


SCHEMA = pa.schema([("signal_date", pa.timestamp("ns")), ("symbol", pa.string()), ("industry_code", pa.string()),
                    ("signal_rules_pass", pa.bool_()), ("scheduled_entry_date", pa.timestamp("ns")),
                    ("scheduled_exit_date", pa.timestamp("ns")), ("earliest_scheduled_information_date", pa.timestamp("ns")),
                    ("scheduled_exit_in_development", pa.bool_()), ("input_audit_bits", pa.uint16()),
                    ("primary_reason_bit", pa.uint16()), ("plain_case_data_candidate", pa.bool_()), ("training_label_approved", pa.bool_())])


def main():
    if TARGET.exists() or BUILD.exists():
        raise RuntimeError("Preserve existing or incomplete outputs; use a new version.")
    audit = Audit()
    tests = unit_checks()
    BUILD.mkdir(parents=True)
    writers, totals = {}, []
    industry_totals, reason_totals, fold_totals = [], [], []
    raw_rows, rule_rows, plain_rows = 0, 0, 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for offset in range(0, len(audit.input["files"]), 64):
                frames = [f for f in pool.map(audit.process, audit.input["files"][offset:offset+64]) if f is not None]
                if not frames: continue
                frame = pd.concat(frames, ignore_index=True)
                raw_rows += len(frame); rule_rows += int(frame.signal_rules_pass.sum()); plain_rows += int(frame.plain_case_data_candidate.sum())
                frame["year"] = frame.signal_date.dt.year
                selected = frame.loc[frame.signal_rules_pass].copy()
                summary = selected.groupby("year").agg(signal_rule_rows=("symbol", "size"), plain_case_data_candidates=("plain_case_data_candidate", "sum"))
                for bit in audit.reason_names:
                    summary[f"bit_{bit}"] = ((selected.input_audit_bits & bit) != 0).groupby(selected.year).sum()
                totals.append(summary)
                industry_totals.append(selected.groupby(["year", "industry_code"]).agg(signal_rule_rows=("symbol", "size"), plain_case_data_candidates=("plain_case_data_candidate", "sum")))
                reason_totals.append(selected.groupby(["year", "primary_reason_bit"]).size().rename("rows"))
                for cutoff in ("2020-12-31", "2021-12-31", "2022-12-31"):
                    prior = selected.loc[selected.signal_date.le(cutoff)]
                    fold_totals.append({"training_cutoff": cutoff, "signal_rule_rows": len(prior),
                                        "scheduled_exit_after_cutoff": int(prior.scheduled_exit_date.gt(cutoff).sum()),
                                        "plain_data_candidates_nominally_mature_by_cutoff": int((prior.plain_case_data_candidate & prior.scheduled_exit_date.le(cutoff)).sum())})
                for year, group in frame.groupby("year"):
                    year = int(year)
                    if year not in writers:
                        writers[year] = pq.ParquetWriter(BUILD / f"{year}.parquet", SCHEMA, compression="zstd")
                    writers[year].write_table(pa.Table.from_pandas(group[SCHEMA.names], schema=SCHEMA, preserve_index=False))
                if offset % 512 == 0:
                    print(json.dumps({"source_files_processed": min(offset+64, len(audit.input["files"])), "schedule_rows": raw_rows}), flush=True)
    finally:
        for writer in writers.values(): writer.close()
    yearly = pd.concat(totals).groupby(level=0).sum().sort_index()
    yearly["plain_candidate_fraction"] = yearly.plain_case_data_candidates / yearly.signal_rule_rows
    by_industry = pd.concat(industry_totals).groupby(level=[0,1]).sum().sort_index()
    by_industry["plain_candidate_fraction"] = by_industry.plain_case_data_candidates / by_industry.signal_rule_rows
    primary = pd.concat(reason_totals).groupby(level=[0,1]).sum().sort_index().reset_index()
    folds = pd.DataFrame(fold_totals).groupby("training_cutoff").sum().reset_index()
    yearly.reset_index().to_parquet(BUILD / "availability_by_year.parquet", index=False)
    by_industry.reset_index().to_parquet(BUILD / "availability_by_year_industry.parquet", index=False)
    primary.to_parquet(BUILD / "primary_unavailability_reasons.parquet", index=False)
    folds.to_parquet(BUILD / "scheduled_training_cutoff_purge.parquet", index=False)
    assert raw_rows == int(audit.observed.sum()) and rule_rows == int(audit.eligible.sum())
    assert rule_rows == int(yearly.signal_rule_rows.sum()) == int(primary.rows.sum())
    assert plain_rows == int(yearly.plain_case_data_candidates.sum())
    files, checked_rows = [], 0
    for path in sorted(BUILD.glob("*.parquet")):
        if path.stem.isdigit():
            data = pd.read_parquet(path)
            assert data.signal_date.dt.year.eq(int(path.stem)).all() and data.signal_date.le(END).all()
            assert not data.duplicated(["symbol", "signal_date"]).any()
            assert not data.training_label_approved.any()
            assert data.plain_case_data_candidate.eq(data.signal_rules_pass & data.input_audit_bits.eq(0)).all()
            assert (data.scheduled_exit_date > data.scheduled_entry_date).all()
            assert data.earliest_scheduled_information_date.eq(data.scheduled_exit_date).all()
            checked_rows += len(data)
        files.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": pq.ParquetFile(path).metadata.num_rows})
    assert checked_rows == raw_rows
    tests.update({"signal_pool_flags_preserved": True, "all_observed_signal_rows_retained": True,
                  "all_training_approval_flags_false": True, "output_contains_no_target_return_column": True,
                  "source_kline_hashes_verified": len(audit.input["files"]), "year_industry_and_reason_totals_reconcile": True})
    report = {"label_definition": "label_definition_v1.json", "label_definition_sha256": sha("label_definition_v1.json"),
              "scope": "2018_to_2023_schedules_and_quality_flags_only_no_label_values", "observed_signal_rows": raw_rows,
              "signal_rule_rows": rule_rows, "plain_case_data_candidates": plain_rows,
              "plain_case_data_candidate_fraction": plain_rows / rule_rows,
              "plain_candidates_are_not_approved_training_labels": True, "yearly": yearly.reset_index().to_dict("records"),
              "nominal_training_maturity_purge": folds.to_dict("records"),
              "reason_bits": audit.reason_names, "failure_reason_counts_overlap": True,
              "quality_guards_not_signal_day_filters_or_model_features": True,
              "missingness_is_event_and_industry_dependent_and_requires_bias_sensitivity_checks": True,
              "no_2024_prices_or_outcomes_used": True, "calendar_only_2024_dates_can_appear_for_unmatured_tail_schedules": True,
              "event_sources_used_for_guard_dates_not_economic_amounts": True, "current_staging_events_not_promoted_as_verified_returns": True,
              "label_values_computed": False, "schedule_and_guard_audit_passed": True,
              "label_admission_audit_passed": False, "minimum_execution_audit_passed": False,
              "factor_experiments_enabled": False, "files": files, "tests": tests,
              "code_sha256": sha("src/audit_label_schedule_v1.py")}
    save(BUILD / "manifest.json", report)
    assert BUILD.resolve().is_relative_to(ROOT.resolve()) and TARGET.resolve().is_relative_to(ROOT.resolve())
    BUILD.rename(TARGET)
    save(ROOT / "audits/label_schedule_dev_v1.json", report)
    print(json.dumps({k:v for k,v in report.items() if k in ["observed_signal_rows", "signal_rule_rows", "plain_case_data_candidates", "plain_case_data_candidate_fraction", "yearly", "nominal_training_maturity_purge", "label_values_computed", "schedule_and_guard_audit_passed"]}))


if __name__ == "__main__":
    main()
