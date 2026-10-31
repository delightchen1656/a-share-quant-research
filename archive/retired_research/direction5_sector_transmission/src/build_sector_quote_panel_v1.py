"""Construct point-in-time sector quote strength for the user-requested H3 scan."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/sector_leadlag_v1"


def read(path): return json.loads((ROOT / path).read_text(encoding="utf-8"))
def sha(path): return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
def save(path, data):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def canonical(code):
    number = int(code[1:])
    for a,b,letter in [(1,5,"A"),(6,12,"B"),(13,43,"C"),(44,46,"D"),(47,50,"E"),(51,52,"F"),(53,60,"G"),
                       (61,62,"H"),(63,65,"I"),(66,69,"J"),(70,70,"K"),(71,72,"L"),(73,75,"M"),
                       (76,78,"N"),(79,81,"O"),(82,82,"P"),(83,84,"Q"),(85,89,"R"),(90,90,"S")]:
        if a <= number <= b: return letter + f"{number:02d}"
    raise ValueError("Unknown CSRC2012 major code: " + code)


def main():
    spec = read("sector_leadlag_scan_v1.json")
    previous = read("audits/data_revision_v5_registration.json")
    for item in previous["files"]: assert sha(item["path"]) == item["sha256"]
    source = read("sources/sector_leadlag_v1/taxonomy_source.json")
    assert sha(source["file"]) == source["sha256"]
    registration = {"specification_sha256": sha("sector_leadlag_scan_v1.json"),
                    "parent_protocol_sha256": sha("research_protocol_v1.json"),
                    "prior_data_registration_sha256": sha("audits/data_revision_v5_registration.json"),
                    "registered_before_sector_quote_aggregation_or_regression": True,
                    "scope": "user_authorized_H3_statistical_diagnostic_only_global_economic_gates_unchanged"}
    target = ROOT / "audits/sector_leadlag_v1/preregistration.json"
    if target.exists():
        assert json.loads(target.read_text(encoding="utf-8")) == registration
    else: save(str(target.relative_to(ROOT)), registration)
    if (OUT / "panel_manifest.json").exists(): raise RuntimeError("Existing sector panel is frozen; use a new version.")
    OUT.mkdir(parents=True, exist_ok=True)
    hm = read("inputs_pre2025/industry_official_v1/manifest.json")
    history = pd.read_parquet(ROOT / "inputs_pre2025/industry_official_v1" / hm["file"])
    history = history.loc[pd.to_datetime(history.knowledge_start).le(spec["development_end"])].copy()
    assert history.classification_system.eq("CSRC2012").all()
    history["canonical_code"] = history.industry_code.map(canonical)
    corrections = history.loc[history.industry_code.ne(history.canonical_code)].groupby(["industry_code","canonical_code"]).size().reset_index(name="membership_publication_rows")
    name_map = history.groupby("canonical_code").industry_name.agg(lambda s: s.value_counts().index[0]).to_dict()
    name_map.update({"D44":"电力、热力生产和供应业","E47":"房屋建筑业","E48":"土木工程建筑业",
                     "I63":"电信、广播电视和卫星传输服务","L71":"租赁业","L72":"商务服务业",
                     "O80":"机动车、电子产品和日用产品修理业","R85":"新闻和出版业"})
    codes = sorted(name_map)
    code_index = {s:i for i,s in enumerate(codes)}
    calendar = pd.read_parquet(ROOT / "inputs_pre2025/trading_calendar_v1/calendar.parquet")
    days = pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1) & calendar.calendar_date.le(spec["development_end"]), "calendar_date"])
    assert days.is_unique
    day_values = days.to_numpy()
    km = read("inputs_pre2025/kline_v1/manifest.json")
    symbols = [r["symbol"] for r in km["files"]]
    symbol_index = {s:i for i,s in enumerate(symbols)}
    quotes = np.full((len(days), len(symbols)), np.nan)
    def load(record):
        path = "inputs_pre2025/kline_v1/" + record["snapshot_file"]
        assert sha(path) == record["snapshot_sha256"]
        frame = pd.read_parquet(ROOT / path, columns=["date","pctChg","tradestatus"])
        frame = frame.loc[frame.date.le(spec["development_end"])]
        index = np.searchsorted(day_values, frame.date.to_numpy())
        assert (index < len(days)).all() and np.array_equal(day_values[index],frame.date.to_numpy())
        value = pd.to_numeric(frame.pctChg, errors="coerce").to_numpy(dtype=float) / 100
        value[~frame.tradestatus.astype(str).eq("1").to_numpy()] = np.nan
        return symbol_index[record["symbol"]], index, value
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for si,index,value in pool.map(load, km["files"]): quotes[index,si] = value
    count, sums, basket = [np.zeros((len(days),len(codes))) for _ in range(3)]
    changed_rows = 0
    for year in range(2018,2024):
        frame = pd.read_parquet(ROOT / f"inputs_pre2025/eligibility_observed_dev_v1/{year}.parquet",
                                columns=["date","symbol","industry_code","observed_entry_rules_pass"])
        frame = frame.loc[frame.observed_entry_rules_pass].copy()
        di = days.get_indexer(frame.date) + 1
        keep = di < len(days); frame = frame.loc[keep]; di = di[keep]
        si = frame.symbol.map(symbol_index).to_numpy(dtype=int)
        canonical_code = frame.industry_code.map(canonical)
        changed_rows += int(frame.industry_code.ne(canonical_code).sum())
        ci = canonical_code.map(code_index).to_numpy(dtype=int)
        observed = quotes[di,si]
        np.add.at(basket, (di,ci), 1)
        good = np.isfinite(observed)
        np.add.at(count, (di[good],ci[good]), 1)
        np.add.at(sums, (di[good],ci[good]), observed[good])
    measure = spec["sector_measure"]
    with np.errstate(divide="ignore",invalid="ignore"):
        coverage = count/basket
        returns = sums/count
    good = (basket>=measure["minimum_prior_basket_stocks"]) & (count>=measure["minimum_valid_quote_observations"]) & (coverage>=measure["minimum_quote_coverage_fraction"])
    returns[~good] = np.nan
    pubs = history[["source_id","knowledge_start"]].drop_duplicates().sort_values("knowledge_start")
    starts = pd.to_datetime(pubs.knowledge_start).to_numpy()
    prior_day = days.to_numpy().copy(); prior_day[1:] = days[:-1].to_numpy(); prior_day[0] = np.datetime64("2017-12-31")
    publication_index = np.searchsorted(starts, prior_day, side="right")-1
    sources = pubs.source_id.to_numpy()[np.maximum(publication_index,0)]
    records = pd.DataFrame({"date":np.repeat(days.to_numpy(),len(codes)), "industry_code":np.tile(codes,len(days)),
                            "previous_close_basket_stocks":basket.ravel().astype(int), "observed_quote_stocks":count.ravel().astype(int),
                            "quote_coverage":coverage.ravel(), "quote_sum":sums.ravel(), "quote_strength":returns.ravel(),
                            "allocation_publication_id":np.repeat(sources,len(codes))})
    records.to_parquet(OUT / "sector_daily_quote_panel.parquet", index=False)
    availability = []
    for code,i in code_index.items():
        initial = np.isfinite(returns[:,i]) & (days<=pd.Timestamp("2020-12-31"))
        availability.append({"industry_code":code,"industry_name":name_map[code],"initial_valid_days":int(initial.sum()),
                             "valid_days_2021":int((np.isfinite(returns[:,i]) & (days.year==2021)).sum()),
                             "valid_days_2022":int((np.isfinite(returns[:,i]) & (days.year==2022)).sum()),
                             "valid_days_2023":int((np.isfinite(returns[:,i]) & (days.year==2023)).sum()),
                             "initial_sector_coverage_screen_pass":bool(initial.sum()>=spec["regression"]["minimum_initial_training_observations"])})
    pd.DataFrame(availability).to_parquet(OUT / "sector_availability.parquet",index=False)
    save("datasets/sector_leadlag_v1/industry_names.json", name_map)
    save("datasets/sector_leadlag_v1/code_normalization_audit.json", {"standard_source":source,"visually_reviewed_pages":[9,12,13,14],
          "prefix_corrections":corrections.to_dict("records"),"affected_allocated_stock_days":changed_rows,
          "original_industry_and_eligibility_snapshots_modified":False})
    manifest = {"scope":"previous_close_baskets_next_session_quote_strength_not_economic_return", "development_end":spec["development_end"],
                "canonical_industries_in_historical_snapshot":len(codes),"raw_industry_codes":int(history.industry_code.nunique()),
                "sectors_passing_initial_coverage_screen":sum(r["initial_sector_coverage_screen_pass"] for r in availability),
                "calendar_days":len(days),"stock_snapshot_hashes_verified":len(km["files"]),
                "holdout_prices_used":False,"future_ST_not_used_to_redefine_prior_basket":True,
                "quote_coverage_and_noninvestability_limits_registered":True,
                "panel_sha256":sha("datasets/sector_leadlag_v1/sector_daily_quote_panel.parquet"),
                "specification_sha256":sha("sector_leadlag_scan_v1.json")}
    save("datasets/sector_leadlag_v1/panel_manifest.json",manifest)
    print(json.dumps(manifest))


if __name__ == "__main__": main()
