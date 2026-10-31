import pathlib,pandas as pd,pickle,json,numpy as np
O=pathlib.Path('研究尝试/方向1_超跌反弹/execution_rules_research_2020_2024')
with open(O/'verified_cache.pkl','rb') as f:s,cal,data,e=pickle.load(f)
ix={d:i for i,d in enumerate(cal)}
e['calendar_window_complete']=e.entry_date.map(lambda d: d in ix and ix[d]+20<len(cal));e['endpoint_quote_present']=e.close20.notna();e['window_complete']=e.calendar_window_complete&e.endpoint_quote_present
# Keep partial peak measurements explicitly labelled, do not extrapolate.
e.to_csv(O/'event_price_diagnostics.csv',index=False)
with open(O/'verified_cache.pkl','wb') as f:pickle.dump((s,cal,data,e),f)
x=e[e.window_complete];d=e.groupby('entry_date').size()
sm={'signals':len(e),'complete_D20_price_windows':len(x),'censored_or_endpoint_missing':int((~e.window_complete).sum()),'entry_states':s.next_state.value_counts().to_dict(),'stocks':len(data),'per_year_complete_window':{str(y):{'n':len(g),'median_peak20':g.peak20.median(),'touch20_rate_T1plus':g.tp20_touch.mean(),'mean_close20':g.close20.mean(),'median_giveback':g.peak_giveback.median(),'p10_close20':g.close20.quantile(.1)}for y,g in x.groupby('year')},'max_same_day_signals':int(d.max()),'signal_days':len(d),'fraction_signals_on_gt20_days':float(d[d>20].sum()/len(e)),'top10_days_signal_fraction':float(d.nlargest(10).sum()/len(e))}
(O/'price_diagnostics.json').write_text(json.dumps(sm,indent=2),encoding='utf-8');print(json.dumps(sm,indent=2))
