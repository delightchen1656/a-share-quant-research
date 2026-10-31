"""Fixed training procedure. Annual refits, never tune on evaluated years."""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from common import SPEC

def fit_year(panel,year):
    columns=SPEC['factors']
    # Rank using complete signal-date eligible pool BEFORE label filtering.
    ranks=panel.groupby('signal_date')[columns].rank(pct=True,na_option='keep')
    mask=panel.label_maturity_date.lt(f'{year}-01-01')&panel.ordinary_quote_excess.notna()
    assert mask.any() and panel.loc[mask,'label_maturity_date'].max()<f'{year}-01-01'
    med=ranks.loc[mask].median()
    assert med.notna().all()
    w=(1/panel.loc[mask].groupby('signal_date').symbol.transform('size')).to_numpy()
    w/=w.mean()
    scaler=StandardScaler().fit(ranks.loc[mask].fillna(med),sample_weight=w)
    model=HistGradientBoostingRegressor(**SPEC['fixed_HGB'])
    model.fit(scaler.transform(ranks.loc[mask].fillna(med)),panel.loc[mask,'ordinary_quote_excess'],sample_weight=w)
    return dict(features=columns,medians=med,scaler=scaler,model=model,training_end=f'{year-1}-12-31'),dict(
        year=year,training_rows=int(mask.sum()),training_dates=int(panel.loc[mask,'signal_date'].nunique()),
        latest_matured_training_label=str(panel.loc[mask,'label_maturity_date'].max()),
        no_current_year_labels_used=True)

def predict_year(pack,panel,year):
    g=panel.loc[panel.year.eq(year)].copy()
    ranks=g.groupby('signal_date')[pack['features']].rank(pct=True,na_option='keep')
    g['score']=pack['model'].predict(pack['scaler'].transform(ranks.fillna(pack['medians'])))
    g=g.sort_values(['signal_date','score','symbol'],ascending=[True,False,True])
    g['rank']=g.groupby('signal_date').cumcount()+1
    return g.loc[g['rank'].le(10),['signal_date','monday','tuesday','year','symbol','score','rank']].assign(method='long120')
