"""Exhaustive ordered-sector quote prediction diagnostic, not a trading backtest."""
from __future__ import annotations

import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr

from build_sector_quote_panel_v1 import read, sha, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets/sector_leadlag_v1"


def ols(z, x, y, hac_positions=None, calendar_size=None):
    design = np.column_stack([z,x])
    beta, _, rank, _ = np.linalg.lstsq(design,y,rcond=None)
    base, _, base_rank, _ = np.linalg.lstsq(z,y,rcond=None)
    if rank != design.shape[1] or base_rank != z.shape[1]: return None
    result = {"beta":beta,"base":base}
    if hac_positions is not None:
        errors = y-design@beta
        inv = np.linalg.pinv(design.T@design)
        influence = (design@inv[:,-1])*errors
        calendar = np.zeros(calendar_size); calendar[hac_positions] = influence
        variance = float(calendar@calendar)
        for lag in range(1,6): variance += 2*(1-lag/6)*float(calendar[lag:]@calendar[:-lag])
        variance *= len(y)/(len(y)-design.shape[1])
        se = np.sqrt(max(variance,0))
        result.update({"source_se":se,"source_p":float(2*ndtr(-abs(beta[-1]/se))) if se>0 else 1.0})
    return result


def fdr(p):
    p = np.asarray(p,dtype=float); n=len(p); order=np.argsort(p)
    q=np.minimum.accumulate((p[order]*n/np.arange(1,n+1))[::-1])[::-1]
    bh=np.empty(n); bh[order]=np.minimum(q,1)
    return bh,np.minimum(bh*np.sum(1/np.arange(1,n+1)),1)


def self_checks():
    bh,by=fdr([.01,.04,.03]); assert np.allclose(bh,[.03,.04,.04]) and np.all(by>=bh)
    rng=np.random.default_rng(481516)
    a=rng.normal(size=3001); noise=rng.normal(scale=.6,size=3001); b=np.zeros(3001)
    for i in range(1,len(b)): b[i]=.4*a[i-1]+.2*b[i-1]+noise[i]
    z=np.column_stack([np.ones(3000),b[:-1]])
    fit=ols(z,a[:-1],b[1:],np.arange(3000),3000)
    assert abs(fit["beta"][-1]-.4)<.04 and fit["source_p"]<1e-12
    # Independent direct sandwich calculation checks the scalar HAC variance.
    design=np.column_stack([z,a[:-1]]); u=b[1:]-design@fit["beta"]
    xu=design*u[:,None]; meat=xu.T@xu
    for k in range(1,6):
        cross=xu[k:].T@xu[:-k]; meat+=(1-k/6)*(cross+cross.T)
    bread=np.linalg.pinv(design.T@design)
    variance=(bread@meat@bread)[-1,-1]*len(u)/(len(u)-design.shape[1])
    assert np.isclose(fit["source_se"]**2,variance,rtol=1e-7)
    return {"known_synthetic_A_leads_B_effect_recovered":True,"HAC_matches_direct_matrix_sandwich":True,
            "BH_BY_monotone_corrections_checked":True,"test_seed_not_a_strategy_selection_seed":481516}


def main():
    if (OUT/"scan_summary.json").exists(): raise RuntimeError("Preserve existing scan; register a new version.")
    tests=self_checks(); spec=read("sector_leadlag_scan_v1.json")
    registration=read("audits/sector_leadlag_v1/preregistration.json")
    assert sha("sector_leadlag_scan_v1.json")==registration["specification_sha256"]
    manifest=read("datasets/sector_leadlag_v1/panel_manifest.json")
    assert sha("datasets/sector_leadlag_v1/sector_daily_quote_panel.parquet")==manifest["panel_sha256"]
    panel=pd.read_parquet(OUT/"sector_daily_quote_panel.parquet")
    codes=sorted(panel.industry_code.unique()); dates=pd.DatetimeIndex(sorted(panel.date.unique()))
    def pivot(column): return panel.pivot(index="date",columns="industry_code",values=column).reindex(index=dates,columns=codes).to_numpy()
    returns,sums,count=pivot("quote_strength"),pivot("quote_sum"),pivot("observed_quote_stocks")
    total_sum,total_count=sums.sum(axis=1),count.sum(axis=1)
    source_ids=panel.groupby("date").allocation_publication_id.agg(lambda s:s.unique()[0]).reindex(dates).to_numpy()
    assert panel.groupby("date").allocation_publication_id.nunique().le(1).all()
    availability=pd.read_parquet(OUT/"sector_availability.parquet").set_index("industry_code")
    eligible=set(availability.loc[availability.initial_sector_coverage_screen_pass].index)
    names=read("datasets/sector_leadlag_v1/industry_names.json")
    minimum=spec["regression"]["minimum_initial_training_observations"]
    min_year=spec["regression"]["minimum_observations_each_validation_year"]
    results, inventory=[],[]
    for ai,a in enumerate(codes):
        for bi,b in enumerate(codes):
            if ai==bi: continue
            if a not in eligible or b not in eligible:
                for lag in spec["regression"]["lags_sessions"]:
                    inventory.append({"leader":a,"follower":b,"lag":lag,"status":"insufficient_initial_sector_coverage","initial_joint_n":0})
                continue
            other_n=total_count-count[:,ai]-count[:,bi]
            with np.errstate(divide="ignore",invalid="ignore"):
                market=(total_sum-sums[:,ai]-sums[:,bi])/other_n
            market[other_n<spec["regression"]["minimum_other_market_quote_stocks"]]=np.nan
            ea,eb=returns[:,ai]-market,returns[:,bi]-market
            for lag in spec["regression"]["lags_sessions"]:
                t=np.arange(max(1,lag-1),len(dates)-1)
                source_t=t-lag+1; target_t=t+1
                z=np.column_stack([np.ones(len(t)),eb[t],eb[t-1],market[t],market[t-1]])
                x,y=ea[source_t],eb[target_t]
                valid=np.isfinite(z).all(axis=1)&np.isfinite(x)&np.isfinite(y)
                # All allocation publications here are known by forecast signal t.
                earliest=t-np.maximum(lag-1,1)
                valid &= source_ids[earliest]==source_ids[target_t]
                train=valid&(dates[target_t]<=pd.Timestamp("2020-12-31"))
                inv={"leader":a,"follower":b,"lag":lag,"initial_joint_n":int(train.sum())}
                if train.sum()<minimum:
                    inventory.append({**inv,"status":"insufficient_joint_initial_observations"});continue
                initial=ols(z[train],x[train],y[train],target_t[train],len(dates))
                if initial is None:
                    inventory.append({**inv,"status":"rank_deficient_initial_design"});continue
                inventory.append({**inv,"status":"tested"})
                record={"leader":a,"leader_name":names[a],"follower":b,"follower_name":names[b],"lag":lag,
                        "initial_n":int(train.sum()),"initial_beta":float(initial["beta"][-1]),
                        "initial_HAC_se":float(initial["source_se"]),"initial_p":initial["source_p"]}
                sse_full,sse_base,positive_direction,improved,valid_years=0.,0.,0,0,0
                for year in (2021,2022,2023):
                    cutoff=pd.Timestamp(f"{year-1}-12-31")
                    past=valid&(dates[target_t]<=cutoff)
                    future=valid&(dates[target_t].year==year)
                    record[f"n_{year}"]=int(future.sum())
                    record[f"validation_beta_{year}"]=np.nan
                    record[f"forward_MSE_improvement_{year}"]=np.nan
                    record[f"past_fit_beta_{year}"]=np.nan
                    if future.sum()<min_year or past.sum()<minimum:continue
                    fitted=initial if year==2021 else ols(z[past],x[past],y[past])
                    diagnostic=ols(z[future],x[future],y[future])
                    if fitted is None or diagnostic is None:continue
                    assert dates[target_t[past]].max()<=cutoff
                    full_prediction=np.column_stack([z[future],x[future]])@fitted["beta"]
                    base_prediction=z[future]@fitted["base"]
                    full_error=float(np.sum((y[future]-full_prediction)**2))
                    base_error=float(np.sum((y[future]-base_prediction)**2))
                    skill=1-full_error/base_error if base_error>0 else np.nan
                    record[f"validation_beta_{year}"]=float(diagnostic["beta"][-1])
                    record[f"past_fit_beta_{year}"]=float(fitted["beta"][-1])
                    record[f"forward_MSE_improvement_{year}"]=skill
                    valid_years+=1;positive_direction+=int(diagnostic["beta"][-1]>0);improved+=int(skill>0)
                    sse_full+=full_error;sse_base+=base_error
                record.update({"valid_validation_years":valid_years,"positive_validation_direction_years":positive_direction,
                               "positive_forward_prediction_improvement_years":improved,
                               "pooled_forward_MSE_improvement":1-sse_full/sse_base if sse_base>0 else np.nan})
                results.append(record)
        if ai%5==0:
            pd.DataFrame(results).to_parquet(OUT/"scan_checkpoint.parquet",index=False)
            print(json.dumps({"leader_industries_processed":ai+1,"total_industries":len(codes),"tested_pair_lags":len(results)}),flush=True)
    frame=pd.DataFrame(results)
    bh,by=fdr(frame.initial_p.to_numpy())
    frame["initial_q_BH"]=bh;frame["initial_q_BY"]=by
    frame["initial_positive_BY_pass"]=(frame.initial_beta>0)&(frame.initial_q_BY<=.05)
    frame["initial_positive_BH_exploratory_pass"]=(frame.initial_beta>0)&(frame.initial_q_BH<=.05)
    frame["stable_positive_candidate"]=(frame.initial_positive_BY_pass & frame.valid_validation_years.eq(3)
                                         & frame.positive_validation_direction_years.eq(3)
                                         & frame.positive_forward_prediction_improvement_years.ge(2)
                                         & frame.pooled_forward_MSE_improvement.gt(0))
    frame=frame.sort_values(["initial_q_BY","initial_p","leader","follower","lag"])
    frame.to_parquet(OUT/"all_pair_lag_results.parquet",index=False)
    pd.DataFrame(inventory).to_parquet(OUT/"all_ordered_pair_lag_inventory.parquet",index=False)
    frame.loc[frame.stable_positive_candidate].to_parquet(OUT/"stable_positive_candidates.parquet",index=False)
    frame.loc[frame.initial_beta.gt(0)].head(20).to_parquet(OUT/"top20_initial_training_positive_diagnostics.parquet",index=False)
    assert len(inventory)==len(codes)*(len(codes)-1)*4
    assert not frame.duplicated(["leader","follower","lag"]).any()
    summary={"canonical_industries":len(codes),"initial_coverage_eligible_industries":len(eligible),
             "ordered_industry_pairs_in_inventory":len(codes)*(len(codes)-1),"pre_registered_lags":[1,2,3,5],
             "all_pair_lag_inventory_count":len(inventory),"estimable_pair_lag_tests":len(frame),
             "skipped_reasons":pd.DataFrame(inventory).status.value_counts().to_dict(),
             "initial_positive_BY_significant_tests":int(frame.initial_positive_BY_pass.sum()),
             "initial_positive_BH_exploratory_significant_tests":int(frame.initial_positive_BH_exploratory_pass.sum()),
             "stable_positive_pair_lag_tests":int(frame.stable_positive_candidate.sum()),
             "stable_positive_ordered_pairs":int(frame.loc[frame.stable_positive_candidate,["leader","follower"]].drop_duplicates().shape[0]),
             "top_diagnostics_ranked_only_by_initial_training":frame.loc[frame.initial_beta.gt(0)].head(10).fillna(0).to_dict("records"),
             "validation_is_development_selection_data_not_final_test":True,
             "2024_holdout_used":False,"economic_returns_or_account_backtests_computed":False,
             "all_global_economic_label_factor_and_account_gates_unchanged":True,
             "no_causal_or_tradable_profit_claim":True,"self_checks":tests,
             "specification_sha256":sha("sector_leadlag_scan_v1.json")}
    save("datasets/sector_leadlag_v1/scan_summary.json",summary)
    save("audits/sector_leadlag_v1/scan_summary.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ["top_diagnostics_ranked_only_by_initial_training","self_checks"]}))


if __name__=="__main__":main()
