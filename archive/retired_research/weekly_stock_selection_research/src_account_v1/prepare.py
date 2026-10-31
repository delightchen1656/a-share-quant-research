"""Bind registered annual forward signal artifacts; no final-model hindsight replay."""
import json
import pandas as pd
from common import BASE,AUDIT,SPEC,sha,dump,install_development_guard


def main():
    install_development_guard()
    assert not (AUDIT/'scores.parquet').exists()
    prior=BASE/'audits/holdout_restricted/research_v1'
    schedule=pd.read_parquet(prior/'weekly_schedule.parquet')
    schedule.to_parquet(AUDIT/'weekly_schedule.parquet',index=False)
    pieces=[]
    mapping={'combine__long_momentum':'long120','anchor11':'anchor11'}
    for year in [2021,2022,2023]:
        path=BASE/'audits/holdout_restricted/monday_factor_v5'/f'fold_scores_{year}.parquet'
        frame=pd.read_parquet(path)
        frame=frame.loc[frame.variant.isin(mapping)&frame['rank'].le(10)].copy()
        frame['method']=frame.variant.map(mapping)
        pieces.append(frame)
    scores=pd.concat(pieces,ignore_index=True)
    assert scores.groupby(['method','monday']).size().eq(10).all()
    assert (pd.to_datetime(scores.signal_date)<pd.to_datetime(scores.monday)).all()
    scores.to_parquet(AUDIT/'scores.parquet',index=False)
    dump(AUDIT/'signal_provenance.json',dict(years=[2021,2022,2023],historical_annual_forward_models=True,
         final2023model_not_applied_to_earlier_years=True,model_hyperparameters_and_features_unchanged=True,
         top10only_no_replacement=True,scores_sha256=sha(AUDIT/'scores.parquet'),
         development_factor_selection_already_observed_these_years=True,not_independent_validation=True))
    print('Saved exact historical forwardtop10signals; no new model fitting.',flush=True)


if __name__=='__main__':
    main()
