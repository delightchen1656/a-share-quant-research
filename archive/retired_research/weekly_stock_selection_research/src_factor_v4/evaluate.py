"""All registered development comparisons, causal historical selector, fixed final decision."""
import json
import numpy as np
import pandas as pd
from settings import OLD,OUT,sha,dump,variants


def main():
    assert json.loads((OUT/'fit_complete.json').read_text(encoding='utf-8'))['model_fits']==225
    assert not (OUT/'summary.parquet').exists(),'Keep original evaluated trial set'
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    all_scores=pd.concat([pd.read_parquet(OUT/f'fold_scores_{y}.parquet') for y in [2019,2020,2021,2022,2023]],ignore_index=True)
    top=all_scores.loc[all_scores['rank'].le(10)].copy()
    top=top.merge(panel[['signal_date','symbol','ordinary_gross_quote_return','label_status']],
                  on=['signal_date','symbol'],validate='many_to_one',how='left')
    assert top.groupby(['variant','monday']).size().eq(10).all() and top.label_status.notna().all()
    weekly=top.groupby(['variant','year','signal_date','monday','tuesday'],sort=False).agg(
        signal_mean=('ordinary_gross_quote_return','mean'),known=('ordinary_gross_quote_return','count'),
        selected=('symbol','size')).reset_index()
    assert weekly.signal_mean.notna().all(),'Do not fabricate an empty-label mean'
    baseline=weekly.loc[weekly.variant.eq('baseline12'),['monday','signal_mean','known']].rename(columns={'signal_mean':'baseline_mean','known':'baseline_known'})
    weekly=weekly.merge(baseline,on='monday',validate='many_to_one')
    weekly['improvement']=weekly.signal_mean-weekly.baseline_mean
    weekly['joint_complete']=weekly.known.eq(10)&weekly.baseline_known.eq(10)
    annual=weekly.groupby(['variant','year']).agg(mean_signal_return=('signal_mean','mean'),
        mean_improvement=('improvement','mean'),weeks=('monday','size'),known=('known','sum'),selected=('selected','sum')).reset_index()
    development=weekly.loc[weekly.year.ge(2021)].copy()
    matrix=development.pivot(index='monday',columns='variant',values='improvement').sort_index()
    assert matrix.notna().all().all()
    names=list(matrix.columns)
    x=matrix.to_numpy()
    rng=np.random.default_rng(26027)
    n=len(matrix)
    starts=rng.integers(0,n,size=(2000,int(np.ceil(n/5))))
    indices=((starts[:,:,None]+np.arange(5))%n).reshape(2000,-1)[:,:n]
    boots=np.stack([x[ix].mean(axis=0) for ix in indices])
    estimates=x.mean(axis=0)
    std=boots.std(axis=0,ddof=1)
    usable=std>1e-14
    max_t=np.max(np.abs((boots[:,usable]-estimates[usable])/std[usable]),axis=1)
    family_q=float(np.quantile(max_t,.95))
    summaries=[]
    for name,g in development.groupby('variant',sort=False):
        j=names.index(name)
        ci=np.quantile(boots[:,j],[.025,.975])
        joint=g.loc[g.joint_complete]
        yy=annual.loc[annual.variant.eq(name)&annual.year.ge(2021)].set_index('year')
        summaries.append(dict(variant=name,mean_signal_return=float(g.signal_mean.mean()),mean_improvement=float(g.improvement.mean()),
            positive_improvement_years=int(yy.mean_improvement.gt(0).sum()),
            improvement2021=float(yy.loc[2021,'mean_improvement']),improvement2022=float(yy.loc[2022,'mean_improvement']),
            improvement2023=float(yy.loc[2023,'mean_improvement']),
            known_coverage=float(g.known.sum()/g.selected.sum()),unknown=int((g.selected-g.known).sum()),
            joint_complete_weeks=len(joint),joint_complete_mean_improvement=float(joint.improvement.mean()),
            mean_known_per_week=float(g.known.mean()),positive_week_fraction=float(g.signal_mean.gt(0).mean()),
            improvement_ci_low=float(ci[0]),improvement_ci_high=float(ci[1]),
            simultaneous_ci_low=float(estimates[j]-family_q*std[j]),simultaneous_ci_high=float(estimates[j]+family_q*std[j])))
    summary=pd.DataFrame(summaries).sort_values('mean_signal_return',ascending=False)
    adaptive=[]
    choices=[]
    for year in [2021,2022,2023]:
        past=annual.loc[annual.year.isin([year-2,year-1])]
        p=past.pivot(index='variant',columns='year',values='mean_improvement')
        valid=p.loc[p.gt(0).all(axis=1)].copy()
        if len(valid):
            selection=valid.mean(axis=1).rename('prior_mean').reset_index().sort_values(['prior_mean','variant'],ascending=[False,True]).variant.iloc[0]
        else:
            selection='baseline12'
        choices.append(dict(year=year,chosen_variant=selection,selection_years=[year-2,year-1],only_past_year_outcomes_used=True))
        piece=weekly.loc[weekly.year.eq(year)&weekly.variant.eq(selection)].copy()
        piece['source_variant']=selection
        piece['variant']='causal_past2year_selector'
        adaptive.append(piece)
    adaptive=pd.concat(adaptive,ignore_index=True)
    qualifying=summary.loc[summary.improvement2022.gt(0)&summary.improvement2023.gt(0)&summary.mean_improvement.gt(0)].copy()
    qualifying['last2mean']=(qualifying.improvement2022+qualifying.improvement2023)/2
    if len(qualifying):
        final=qualifying.sort_values(['last2mean','variant'],ascending=[False,True]).variant.iloc[0]
    else:
        final='baseline12'
    decision=dict(selected_variant=final,features=variants()[final],
        policy_sha256=sha(OUT/'ONE_WAY_AUDIT_POLICY.json'),selected_before_future_data_or_audit=True,
        qualified_variants=qualifying.sort_values('last2mean',ascending=False).variant.tolist(),
        no_post_result_combination_added=True,meaning='Pre2024development candidate only, no future performance claimed')
    summary.to_parquet(OUT/'summary.parquet',index=False)
    annual.to_parquet(OUT/'annual_means.parquet',index=False)
    weekly.to_parquet(OUT/'weekly_all_folds.parquet',index=False)
    adaptive.to_parquet(OUT/'causal_selector_weeks.parquet',index=False)
    top.to_parquet(OUT/'selected_signal_labels.parquet',index=False)
    dump(OUT/'causal_selector_choices.json',choices)
    dump(OUT/'final_development_decision.json',decision)
    dump(OUT/'metric_notes.json',dict(primary='ordinary-label conditional gross means, no fees or actual execution',
        common_label_sensitivity='Intersection of weeks with all10selected stock labels known in BOTH variant and baseline; not intersecting the selected stock names.',
        multiplicity='2000circular5weekblock bootstraps of paired weekly improvements. Also report approximate simultaneous maxT intervals across44nonbaseline trials; reuse and selection bias still remain.',
        maxT_95_quantile=family_q,all45trials_retained=True,no_future_quotes_read=True))
    print(summary[['variant','mean_signal_return','mean_improvement','positive_improvement_years','known_coverage','simultaneous_ci_low','simultaneous_ci_high']].to_string(index=False),flush=True)
    print('Causal past2-year selector',choices, 'mean',adaptive.signal_mean.mean(),'improvement',adaptive.improvement.mean(),flush=True)
    print('Selected under pre-registered final rule:',final,flush=True)


if __name__=='__main__':
    main()
