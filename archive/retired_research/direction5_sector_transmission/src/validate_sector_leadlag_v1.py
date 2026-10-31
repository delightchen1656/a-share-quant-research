"""Validate source timing, test-family accounting and freeze the H3 diagnostic."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_sector_quote_panel_v1 import canonical,read,save,sha
from scan_sector_leadlag_v1 import fdr,ols

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"datasets/sector_leadlag_v1"


def prior_basket_check():
    calendar=pd.read_parquet(ROOT/"inputs_pre2025/trading_calendar_v1/calendar.parquet")
    days=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1),"calendar_date"])
    sample=None
    for year in range(2018,2024):
        panel=pd.read_parquet(ROOT/f"inputs_pre2025/eligibility_observed_dev_v1/{year}.parquet")
        panel=panel.sort_values(["symbol","date"])
        previous=panel.groupby("symbol")[["date","industry_code","observed_entry_rules_pass"]].shift(1)
        current_index=days.get_indexer(panel.date)
        previous_index=days.get_indexer(pd.to_datetime(previous.date))
        changed=(previous.observed_entry_rules_pass.eq(True)&~panel.observed_entry_rules_pass
                 &(current_index-previous_index==1))
        if changed.any():
            row=panel.loc[changed].sort_values(["date","symbol"]).iloc[0]
            prev=previous.loc[row.name]
            sample={"symbol":row.symbol,"return_date":row.date,"allocation_date":prev.date,
                    "industry_code":canonical(prev.industry_code)}
            basket=panel.loc[panel.date.eq(prev.date)&panel.observed_entry_rules_pass]
            basket=basket.loc[basket.industry_code.map(canonical).eq(sample["industry_code"])]
            break
    assert sample is not None and sample["symbol"] in set(basket.symbol)
    values=[]; target_stock_currently_unavailable=False
    for symbol in basket.symbol:
        frame=pd.read_parquet(ROOT/f"inputs_pre2025/kline_v1/{symbol}.parquet",columns=["date","pctChg","tradestatus","isST"])
        quote=frame.loc[frame.date.eq(sample["return_date"])]
        if len(quote)!=1:continue
        row=quote.iloc[0]
        value=pd.to_numeric(pd.Series([row.pctChg]),errors="coerce").iloc[0]
        if str(row.tradestatus)=="1" and np.isfinite(value): values.append(float(value)/100)
        if symbol==sample["symbol"]:
            target_stock_currently_unavailable=str(row.tradestatus)!="1" or not np.isfinite(value)
    built=pd.read_parquet(OUT/"sector_daily_quote_panel.parquet")
    row=built.loc[built.date.eq(sample["return_date"])&built.industry_code.eq(sample["industry_code"])].iloc[0]
    assert row.previous_close_basket_stocks==len(basket) and row.observed_quote_stocks==len(values)
    assert np.isclose(row.quote_sum,sum(values))
    if np.isfinite(row.quote_strength):assert np.isclose(row.quote_strength,np.mean(values))
    return {**{k:str(v) for k,v in sample.items()},"prior_basket_stocks":len(basket),
            "observed_quote_stocks":len(values),"current_qualification_change_did_not_redefine_prior_basket":True,
            "unavailable_current_quote_not_filled_with_zero":target_stock_currently_unavailable,
            "independently_recomputed_quote_sum_and_mean_match":True}


def main():
    spec=read("sector_leadlag_scan_v1.json"); summary=read("datasets/sector_leadlag_v1/scan_summary.json")
    assert sha("sector_leadlag_scan_v1.json")==summary["specification_sha256"]
    results=pd.read_parquet(OUT/"all_pair_lag_results.parquet")
    inventory=pd.read_parquet(OUT/"all_ordered_pair_lag_inventory.parquet")
    assert len(inventory)==81*80*4 and not inventory.duplicated(["leader","follower","lag"]).any()
    assert len(results)==int(inventory.status.eq("tested").sum())==summary["estimable_pair_lag_tests"]
    assert (results.leader!=results.follower).all() and results.initial_n.ge(400).all()
    bh,by=fdr(results.initial_p.to_numpy())
    assert np.allclose(bh,results.initial_q_BH) and np.allclose(by,results.initial_q_BY)
    expected=(results.initial_beta.gt(0)&results.initial_q_BY.le(.05)&results.valid_validation_years.eq(3)
              &results.positive_validation_direction_years.eq(3)&results.positive_forward_prediction_improvement_years.ge(2)
              &results.pooled_forward_MSE_improvement.gt(0))
    assert expected.eq(results.stable_positive_candidate).all()
    assert results.past_fit_beta_2021.eq(results.initial_beta).all()
    # Check HAC calendar-gap handling against an independently zero-padded sandwich.
    rng=np.random.default_rng(1809); positions=np.setdiff1d(np.arange(250),np.arange(70,91))
    z=np.column_stack([np.ones(len(positions)),rng.normal(size=len(positions))]);x=rng.normal(size=len(positions));y=.2*x+rng.normal(size=len(positions))
    fit=ols(z,x,y,positions,250); design=np.column_stack([z,x]);residual=y-design@fit["beta"]
    scores=np.zeros((250,3));scores[positions]=design*residual[:,None]
    meat=scores.T@scores
    for k in range(1,6):
        cross=scores[k:].T@scores[:-k];meat+=(1-k/6)*(cross+cross.T)
    inv=np.linalg.pinv(design.T@design);var=(inv@meat@inv)[-1,-1]*len(y)/(len(y)-3)
    assert np.isclose(var,fit["source_se"]**2)
    checks={"all_ordered_pairs_and_four_lags_accounted_for":True,"joint_sample_failures_not_reported_as_tested":True,
            "multiple_testing_family_and_q_values_recomputed":True,"stable_candidate_flags_recomputed":True,
            "2021_model_uses_frozen_initial_coefficients":True,"HAC_calendar_gaps_verified":True,
            "prior_day_basket_independent_real_case":prior_basket_check(),
            "raw_positive_p_below_005_count":int((results.initial_beta.gt(0)&results.initial_p.lt(.05)).sum()),
            "minimum_positive_BH_q":float(results.loc[results.initial_beta.gt(0),"initial_q_BH"].min()),
            "global_config_economic_gates_unchanged":True}
    config=read("config.json");assert not config["model_experiments_enabled"] and not config["execution_returns_ready"]
    for name in ("data_revision_v4_registration.json","data_revision_v5_registration.json"):
        for record in read("audits/"+name)["files"]:assert sha(record["path"])==record["sha256"]
    # Promote the audited structural code overlay for future reuse, preserving raw inputs.
    target=ROOT/"inputs_pre2025/industry_code_normalization_v1"
    target.mkdir(exist_ok=True)
    code_map=read("datasets/sector_leadlag_v1/code_normalization_audit.json")
    mapping={r["industry_code"]:r["canonical_code"] for r in code_map["prefix_corrections"]}
    normalization={"scope":"CSRC2012_structural_prefix_correction_only", "known_since":"2012-10-26",
                   "raw_to_canonical_overlay":mapping,"official_standard":code_map["standard_source"],
                   "visual_review_pages":code_map["visually_reviewed_pages"],
                   "original_whitelists_unchanged":True,"promoted_for_future_reuse_after_metadata_audit":True}
    output=target/"manifest.json"
    if output.exists():assert json.loads(output.read_text(encoding="utf-8"))==normalization
    else:save(str(output.relative_to(ROOT)),normalization)
    save("audits/sector_leadlag_v1/validation.json",checks)
    for p in [ROOT/"src/build_sector_quote_panel_v1.py",ROOT/"src/scan_sector_leadlag_v1.py",Path(__file__)]:ast.parse(p.read_text(encoding="utf-8"))
    paths=set(p for folder in [OUT,ROOT/"sources/sector_leadlag_v1",ROOT/"audits/sector_leadlag_v1",target] for p in folder.rglob("*") if p.is_file())
    registry_path=ROOT/"audits/sector_leadlag_v1/registration.json"
    paths.discard(registry_path)
    paths.update(ROOT/p for p in ["sector_leadlag_scan_v1.json","src/build_sector_quote_panel_v1.py","src/scan_sector_leadlag_v1.py","src/validate_sector_leadlag_v1.py"])
    registry={"scope":"user_requested_sector_quote_leadlag_scan_no_economic_backtest", "original_protocol_sha256":sha("research_protocol_v1.json"),
              "prior_data_registration_sha256":sha("audits/data_revision_v5_registration.json"),
              "statistical_scan_completed":True,"economic_label_factor_and_account_gates_unchanged":True,
              "files":[{"path":str(p.relative_to(ROOT)),"sha256":sha(p.relative_to(ROOT))} for p in sorted(paths)]}
    if registry_path.exists():assert json.loads(registry_path.read_text(encoding="utf-8"))==registry
    else:save(str(registry_path.relative_to(ROOT)),registry)
    print(json.dumps({"validation_passed":True,"registered_files":len(paths),"tested_pair_lags":len(results),
                      "stable_pairs":int(results.loc[expected,["leader","follower"]].drop_duplicates().shape[0]),
                      "real_prior_basket_case_independently_verified":checks["prior_day_basket_independent_real_case"]}))


if __name__=="__main__":main()
