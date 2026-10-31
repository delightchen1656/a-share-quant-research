"""Evaluate the36fixed trials without accessing any posterior result."""
import json
import numpy as np
import pandas as pd
from settings import OLD,OUT,variants,dump,install_read_boundary


def main():
    install_read_boundary()
    assert json.loads((OUT/'fit_complete.json').read_text(encoding='utf-8'))['model_fits']==180
    assert not (OUT/'summary.parquet').exists(),'Do not overwrite evaluated development trials'
    labels=pd.read_parquet(OLD/'weekly_factor_panel.parquet')[['signal_date','symbol','ordinary_gross_quote_return','label_status']]
    scores=pd.concat([pd.read_parquet(OUT/f'fold_scores_{year}.parquet') for year in range(2019,2024)],ignore_index=True)
    selected=scores.loc[scores['rank'].le(10)].merge(labels,on=['signal_date','symbol'],validate='many_to_one',how='left')
    assert selected.label_status.notna().all()
    weekly=selected.groupby(['variant','year','signal_date','monday','tuesday'],sort=False).agg(
        signal_mean=('ordinary_gross_quote_return','mean'),known=('ordinary_gross_quote_return','count'),
        selected=('symbol','size')).reset_index()
    assert weekly.selected.eq(10).all() and weekly.signal_mean.notna().all()
    for ref in ['anchor11','original12']:
        reference=weekly.loc[weekly.variant.eq(ref),['monday','signal_mean','known']].rename(columns={'signal_mean':ref+'_mean','known':ref+'_known'})
        weekly=weekly.merge(reference,on='monday',validate='many_to_one')
    weekly['improvement']=weekly.signal_mean-weekly.anchor11_mean
    weekly['improvement_original12']=weekly.signal_mean-weekly.original12_mean
    weekly['joint_complete']=weekly.known.eq(10)&weekly.anchor11_known.eq(10)
    annual=weekly.groupby(['variant','year']).agg(mean_signal_return=('signal_mean','mean'),mean_improvement=('improvement','mean'),
        mean_improvement_original12=('improvement_original12','mean'),weeks=('monday','size'),known=('known','sum'),selected=('selected','sum')).reset_index()
    development=weekly.loc[weekly.year.ge(2021)].copy()
    matrix=development.pivot(index='monday',columns='variant',values='improvement').sort_index()
    assert matrix.notna().all().all()
    names=list(matrix.columns)
    new_variants=[v for v in names if v not in ['original12','anchor11']]
    x=matrix.to_numpy()
    n=len(matrix)
    rng=np.random.default_rng(26027)
    starts=rng.integers(0,n,size=(2000,int(np.ceil(n/5))))
    indices=((starts[:,:,None]+np.arange(5))%n).reshape(2000,-1)[:,:n]
    boots=np.stack([x[ix].mean(axis=0) for ix in indices])
    estimates=x.mean(axis=0)
    sd=boots.std(axis=0,ddof=1)
    mask=np.array([v in new_variants for v in names])&(sd>1e-14)
    q=float(np.quantile(np.max(np.abs((boots[:,mask]-estimates[mask])/sd[mask]),axis=1),.95))
    anchor_coverage=float(development.loc[development.variant.eq('anchor11'),'known'].sum()/development.loc[development.variant.eq('anchor11'),'selected'].sum())
    summary=[]
    for variant,g in development.groupby('variant',sort=False):
        j=names.index(variant)
        yy=annual.loc[annual.variant.eq(variant)&annual.year.ge(2021)].set_index('year')
        ci=np.quantile(boots[:,j],[.025,.975])
        coverage=float(g.known.sum()/g.selected.sum())
        simultaneous_low=float(estimates[j]-q*sd[j])
        joint=g.loc[g.joint_complete]
        best=g.sort_values(['signal_mean','monday'],ascending=[False,True])
        without1=best.iloc[1:]
        without5=best.iloc[5:]
        per_signal=selected.loc[selected.variant.eq(variant)&selected.year.ge(2021),'ordinary_gross_quote_return'].dropna()
        passed=bool(variant in new_variants and g.improvement.mean()>0 and yy.mean_improvement.gt(0).all()
                    and simultaneous_low>0 and coverage>=anchor_coverage-.005)
        summary.append(dict(variant=variant,mean_signal_return=float(g.signal_mean.mean()),mean_improvement=float(g.improvement.mean()),
            mean_improvement_original12=float(g.improvement_original12.mean()),positive_improvement_years=int(yy.mean_improvement.gt(0).sum()),
            improvement2021=float(yy.loc[2021,'mean_improvement']),improvement2022=float(yy.loc[2022,'mean_improvement']),improvement2023=float(yy.loc[2023,'mean_improvement']),
            known_coverage=coverage,unknown=int((g.selected-g.known).sum()),joint_complete_weeks=len(joint),
            joint_complete_improvement=float(joint.improvement.mean()),
            mean_without_best1_week=float(without1.signal_mean.mean()),improvement_without_best1_week=float(without1.improvement.mean()),
            mean_without_best5_weeks=float(without5.signal_mean.mean()),improvement_without_best5_weeks=float(without5.improvement.mean()),
            positive_week_fraction=float(g.signal_mean.gt(0).mean()),known_signal_median=float(per_signal.median()),
            known_signal_win_fraction=float(per_signal.gt(0).mean()),
            improvement_ci_low=float(ci[0]),improvement_ci_high=float(ci[1]),
            simultaneous_ci_low=simultaneous_low,simultaneous_ci_high=float(estimates[j]+q*sd[j]),upgrade_gate=passed))
    summary=pd.DataFrame(summary).sort_values(['mean_signal_return','variant'],ascending=[False,True])
    choices=[]
    adaptive=[]
    for year in [2021,2022,2023]:
        past=annual.loc[annual.year.isin([year-2,year-1])&annual.variant.isin(new_variants)].pivot(index='variant',columns='year',values='mean_improvement')
        eligible=past.loc[past.gt(0).all(axis=1)]
        if len(eligible):
            chosen=eligible.mean(axis=1).rename('mean').reset_index().sort_values(['mean','variant'],ascending=[False,True]).variant.iloc[0]
        else:
            chosen='anchor11'
        choices.append(dict(year=year,chosen_variant=chosen,only_selection_years=[year-2,year-1]))
        piece=weekly.loc[weekly.year.eq(year)&weekly.variant.eq(chosen)].copy()
        piece['source_variant']=chosen
        piece['variant']='causal_prior2year_selector'
        adaptive.append(piece)
    adaptive=pd.concat(adaptive,ignore_index=True)
    exploratory=summary.loc[summary.variant.isin(new_variants)].iloc[0]
    eligible=summary.loc[summary.upgrade_gate]
    retained=eligible.variant.iloc[0] if len(eligible) else 'anchor11'
    decision=dict(upgrade_eligible=bool(len(eligible)),retained_variant=retained,retained_features=variants()[retained],
        best_exploratory_variant=exploratory.variant,best_exploratory_features=variants()[exploratory.variant],
        all_gate_passers=eligible.variant.tolist(),fixed_pre_registered_gate=True,posteriors_not_read=True,
        same_postperiod_not_retested=True,meaning='Pre2024development only, never a new independent validation')
    summary.to_parquet(OUT/'summary.parquet',index=False)
    annual.to_parquet(OUT/'annual_means.parquet',index=False)
    weekly.to_parquet(OUT/'weekly_all_folds.parquet',index=False)
    selected.to_parquet(OUT/'selected_signal_labels.parquet',index=False)
    adaptive.to_parquet(OUT/'causal_selector_weeks.parquet',index=False)
    dump(OUT/'causal_selector_choices.json',choices)
    dump(OUT/'decision.json',decision)
    dump(OUT/'metric_notes.json',dict(ordinary_label_conditional_gross_means=True,not_executable_portfolio_returns=True,
        maxT_simultaneous_family_size=34,approximate95percent_maxT_quantile=q,bootstrap_blocks=5,bootstrap_repeats=2000,
        cumulative_development_selection_bias_not_removed=True,
        concentration_sensitivity='Remove best1/best5weeks by each candidate signal mean; remove identical weeks from its anchor comparison. Diagnostic only, not a trading rule.',
        unknowns_not_zero_or_pre_entry_excluded=True))
    print(summary[['variant','mean_signal_return','mean_improvement','positive_improvement_years','simultaneous_ci_low','upgrade_gate']].to_string(index=False),flush=True)
    print('Causal prior2year selector: mean',adaptive.signal_mean.mean(),'delta vsanchor',adaptive.improvement.mean(),flush=True)
    print('Retained:',retained,'best exploratory:',exploratory.variant,flush=True)


if __name__=='__main__':
    main()
