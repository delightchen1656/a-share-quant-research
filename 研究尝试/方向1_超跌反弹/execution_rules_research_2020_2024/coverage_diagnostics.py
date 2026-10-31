import pathlib,pickle,pandas as pd,numpy as np,json
O=pathlib.Path('研究尝试/方向1_超跌反弹/execution_rules_research_2020_2024')
with open(O/'verified_cache.pkl','rb') as f:s,cal,data,e=pickle.load(f)
rows=[];gaps=[]
for code,(r,q) in data.items():
 f=(q.close/r.close).where((r.close>0)&(q.close>0));change=f/f.shift()-1
 for day,val in change[(change.abs()>.0001)&(change.index>='2020-01-01')].items():rows.append({'code':code,'date':day,'factor_ratio_change':val})
 # All diagnostics preserve and report quote omissions, never use them to prune signals.
 active=r[(r.tradestatus==1)&(r.volume>0)&(r.close>0)]
 first=str(s.loc[s.code==code,'entry_date'].min());a=[d for d in cal if d>=first]
 missing=[d for d in a if d not in r.index]
 if missing:gaps.append({'code':code,'missing_sessions_from_first_entry':len(missing),'first_gap':missing[0],'last_gap':missing[-1],'last_active_quote':active.index[-1] if len(active) else None})
pd.DataFrame(rows).to_csv(O/'observed_factor_jumps.csv',index=False);pd.DataFrame(gaps).to_csv(O/'quote_coverage_gaps.csv',index=False)
print(json.dumps({'factor_jump_rows':len(rows),'codes_with_quote_gaps_after_first_signal':len(gaps),'missing_sessions':sum(x['missing_sessions_from_first_entry']for x in gaps)},indent=2))
