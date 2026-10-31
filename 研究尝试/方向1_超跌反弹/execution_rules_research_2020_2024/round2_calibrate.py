import pathlib,pickle,json,pandas as pd,numpy as np
O=pathlib.Path('研究尝试/方向1_超跌反弹/execution_rules_research_2020_2024')
with open(O/'verified_cache.pkl','rb') as f:s,cal,data,e=pickle.load(f)
rows=[]
for z in s.itertuples():
 r=data[z.code][0];raw=r.loc[z.entry_date] if z.entry_date in r.index else None;prior=r.loc[:z.signal_date].tail(20)
 gap=float(raw.open/raw.preclose-1) if raw is not None and raw.preclose>0 and raw.open>0 else np.nan
 rows.append({'code':z.code,'signal_date':z.signal_date,'entry_date':z.entry_date,'year':int(z.entry_date[:4]),'amount20':prior.amount.mean(),'ret20':float(z.ret20)})
f=pd.DataFrame(rows);train=f[f.year<=2022];liq=float(train.amount20.quantile(.25));lo=float(train.ret20.quantile(.1));hi=float(train.ret20.quantile(.9))
r=json.loads((O/'PROXY_RESULTS.json').read_text())
def score(x):
 a=[z for z in x['annual']if z['year']<=2022];return float(np.median([z['return']for z in a])-.5*max(abs(z['drawdown'])for z in a)-.5*np.std([z['return']for z in a]))
c=max([x for x in r if x['rank']=='code' and not x['trail']],key=lambda x:(score(x),np.prod([1+z['return']for z in x['annual']if z['year']<=2022]),not x['trail'],x['id']))
new={k:c[k]for k in ['id','rank','tp','sl','h','trail']}
f['pass_LIQ']=f.amount20>=liq;f['pass_RET']=f.ret20.between(lo,hi);f['pass_BOTH']=f.pass_LIQ&f.pass_RET
for pool in ['LIQ','RET','BOTH']:f['reason_'+pool]=np.where(f['pass_'+pool],'accepted', 'below_training_liquidity_quantile' if pool=='LIQ' else ('outside_training_ret20_band_or_missing' if pool=='RET' else 'liquidity_or_ret20_failed'))
f.to_csv(O/'ROUND2_SIGNAL_FILTERS.csv',index=False)
config={'stage':'frozen_before_round2_outcome_comparison','threshold_training':'2020-2022 signal-day-known inputs only; open-gap withdrawn before any round2 outcomes','first_round_exit_selection_source':'pre2023 annual price-proxy summaries; later years excluded','liq_amount20_min':liq,'ret20_min':lo,'ret20_max':hi,'NEW':new,'training_score':score(c),'configs':12,'pools':['ALL','LIQ','RET','BOTH'],'past_2023_2024_outcomes_already_seen':True}
(O/'ROUND2_FROZEN_CONFIG.json').write_text(json.dumps(config,indent=2),encoding='utf-8');print(json.dumps(config,indent=2));print(f.groupby('year')[['pass_LIQ','pass_RET','pass_BOTH']].mean())
