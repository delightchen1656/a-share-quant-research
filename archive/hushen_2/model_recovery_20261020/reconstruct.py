"""Shadow-only behavioral reconstruction; never writes the production model directory."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
import lightgbm as lgb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'archive/hushen_2/pre_registration_research_20261020'
OUT = HERE / 'behavioral_v1'
FEATURES = ['f_ret1','f_ret5','f_ret20','f_ret60','f_vol20','f_ma20','f_amount_ratio5','f_log_amount','f_log_price','f_turn','f_range','f_downside20','f_ohlc_rsi14','f_ohlc_atr_compress5_20']
PARAMS = dict(objective='regression', metric='l2', learning_rate=.04,
              num_leaves=63, min_data_in_leaf=100, lambda_l2=1.,
              feature_fraction=1., bagging_fraction=1., seed=20261020,
              deterministic=True, force_col_wise=True, num_threads=6, verbosity=-1)

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    paths=[SOURCE/'cache/model_panel_batch002_pre2025.parquet',SOURCE/'results/batch_004_pre2025_factor_tuning/base_component_panel_pre2025.parquet']
    protocol={'status':'shadow_only_not_original', 'purpose':'Approximate missing original predictions, not train on future returns',
              'train_years':[2020,2021], 'evaluation_years':[2022,2023,2024],
              'no_post2024_inputs':True,'no_production_replacement':True,
              'fixed_rounds':500,'parameters':PARAMS,'features':FEATURES,
              'inputs':{str(p.relative_to(ROOT)):sha(p) for p in paths},
              'limitations':['Original trees, training labels and full parameters unavailable.',
                'Teacher was originally trained through 2021; imitation is not exact restoration.',
                'Historical investment returns cannot be inherited by the reconstructed model.']}
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    x=pd.read_parquet(paths[0],columns=['date','symbol']+FEATURES)
    base=pd.read_parquet(paths[1])
    for p in (x,base):
        p['date']=pd.to_datetime(p.date)
        assert p.date.max()<pd.Timestamp('2025-01-01')
        assert not p.duplicated(['date','symbol']).any()
    p=base.merge(x,on=['date','symbol'],how='inner',validate='one_to_one').sort_values(['date','symbol']).reset_index(drop=True)
    assert len(p)==len(base), 'Incomplete feature/teacher join'
    assert np.isfinite(p[FEATURES+['utility','pen025']].to_numpy()).all()
    train=p.date.dt.year.isin([2020,2021])
    assert train.any() and p.loc[train,'date'].max()<=pd.Timestamp('2021-12-31')
    shadow=p[base.columns].copy()
    reports=[]
    for name in ('utility','pen025'):
        print('Training',name,'rows',int(train.sum()),flush=True)
        model=lgb.train(PARAMS,lgb.Dataset(p.loc[train,FEATURES],label=p.loc[train,name]),num_boost_round=500)
        path=OUT/f'{name}.txt'
        model.save_model(str(path))
        loaded=lgb.Booster(model_file=str(path))
        assert loaded.feature_name()==FEATURES
        yhat=loaded.predict(p[FEATURES],num_threads=6)
        assert np.isfinite(yhat).all()
        shadow[name]=yhat
        for year in range(2020,2025):
            mask=p.date.dt.year.eq(year)
            y=p.loc[mask,name].to_numpy(); pred=yhat[mask]
            ranks=pd.DataFrame({'date':p.loc[mask,'date'],'y':y,'pred':pred}).groupby('date')[['y','pred']].rank(pct=True)
            reports.append({'model':name,'year':year,'split':'fit' if year<=2021 else 'temporal_evaluation',
                            'rows':len(y),'rmse':float(np.sqrt(np.mean((y-pred)**2))),
                            'r2':float(1-np.sum((y-pred)**2)/np.sum((y-y.mean())**2)),
                            'mean_daily_spearman':float(ranks.assign(date=p.loc[mask,'date'].to_numpy()).groupby('date').apply(lambda g:g.y.corr(g.pred),include_groups=False).mean())})
        print(name,'saved',sha(path),flush=True)
    sys.path.insert(0,str(HERE.parent/'runtime'))
    from strategy import build_signals
    original=build_signals(p); rebuilt=build_signals(shadow)
    original.to_csv(OUT/'teacher_signals_pre2025.csv',index=False)
    rebuilt.to_csv(OUT/'reconstructed_signals_pre2025.csv',index=False)
    signal_rows=[]
    for year in range(2020,2025):
        a=original[original.date.dt.year.eq(year)]; b=rebuilt[rebuilt.date.dt.year.eq(year)]
        sets_a=a.groupby('date').symbol.agg(set); sets_b=b.groupby('date').symbol.agg(set)
        assert sets_a.index.equals(sets_b.index)
        hits=[len(sets_a[d]&sets_b[d]) for d in sets_a.index]
        signal_rows.append({'year':year,'split':'fit' if year<=2021 else 'temporal_evaluation',
                            'days':len(hits),'top3_overlap':sum(hits)/len(a),
                            'exact_top3_set_days':sum(h==3 for h in hits)/len(hits)})
    pd.DataFrame(reports).to_csv(OUT/'SCORE_FIDELITY.csv',index=False)
    pd.DataFrame(signal_rows).to_csv(OUT/'SIGNAL_FIDELITY.csv',index=False)
    manifest={'status':'shadow_only_not_original','models':{n:sha(OUT/f'{n}.txt') for n in ('utility','pen025')},
              'joined_rows':len(p),'training_rows':int(train.sum()),'score_metrics':reports,'signal_metrics':signal_rows,
              'production_unchanged':True}
    (OUT/'REPORT.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(pd.DataFrame(signal_rows).to_string(index=False),flush=True)

if __name__=='__main__': main()
