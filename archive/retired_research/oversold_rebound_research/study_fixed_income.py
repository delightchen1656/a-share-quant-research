"""Explicitly IN-DEVELOPMENT fixed-rule comparison, not time-out-of-sample selection."""
import json
import pandas as pd
from study import ROOT,digest
from study_annual_income import mask
import account_backtest as engine

OUT=ROOT/'results_v14_fixed_income'


def main():
    OUT.mkdir(exist_ok=True)
    scores=json.loads((ROOT/'results_v13_100k_stable/training_scores.json').read_text(encoding='utf8'))
    # One prior-2024 proxy-scored exit per filter/slot pair, then full actual-account
    # comparison on already explored 2021..2024. Do NOT call the winner OOS.
    candidates=[]
    for pool in ['sample','leaders']:
        groups={}
        for c in scores:
            if c['pool']!=pool or c['year']!=2024:continue
            if not all(x['n']>=6 for x in c['training']):continue
            groups.setdefault((c['filter'],c['slots']),[]).append(c)
        for group in groups.values():candidates.append(max(group,key=lambda x:x['score']))
    (OUT/'PROTOCOL.json').write_text(json.dumps(dict(candidates=candidates,
        selection='Development-only: require >=6 actual entries each year, all4 years positive, total daily-DD<=15%; maximize minimum annual return, then mean annual return, then lower DD. Otherwise report no qualifying rule.',
        caution='The 2021-2024 years participate in choosing winner. This is NOT an untouched test or a rule known before2021. No2025+ data allowed.'),ensure_ascii=False,indent=2),encoding='utf8')
    inputs=list(engine.prepare());base=inputs[0].copy()
    feature=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet')
    prior=json.loads((ROOT/'results_v11_filtered_horizons/summary.json').read_text(encoding='utf8'))
    excluded={tuple(x) for x in prior['excluded_specials']};all_results=[];iterations=[]
    for attempt in range(5):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
        all_results=[];new=set()
        for i,c in enumerate(candidates):
            pool=c['pool'];sub=feature.loc[mask(feature,c['filter'])]
            ids=set(zip(sub.code,sub.date));inputs[1]={'sample':ids,'leaders':ids}
            r=engine.run(*inputs,pool,True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'],persist=False,quiet=True)
            for e in r['specials']:new.add((e['code'],e['signal_date']))
            annual=[x['return_pct'] for x in r['yearly']]
            n_by_year=r['yearly_trades']
            eligible=all(x>0 for x in annual) and all(n_by_year.get(y,0)>=6 for y in range(2021,2025)) and -r['summary']['max_drawdown']<=.15
            all_results.append(dict(config=c,result=r,eligible=eligible,worst_year=min(annual),mean_year=sum(annual)/4))
            if (i+1)%15==0:print('candidate',i+1,'/',len(candidates),flush=True)
        iterations.append(dict(excluded=sorted(excluded),new_specials=sorted(new)))
        if not new:break
        excluded.update(new)
    else:raise RuntimeError('Special case cleanup not stable')
    qualified=[x for x in all_results if x['eligible']]
    winner=max(qualified,key=lambda x:(x['worst_year'],x['mean_year'],x['result']['summary']['max_drawdown'])) if qualified else None
    best_unqualified=max(all_results,key=lambda x:x['worst_year'])
    (OUT/'comparison.json').write_text(json.dumps(all_results,ensure_ascii=False,indent=2),encoding='utf8')
    if winner:
        c=winner['config'];sub=feature.loc[mask(feature,c['filter'])];ids=set(zip(sub.code,sub.date));inputs[1]={'sample':ids,'leaders':ids}
        engine.OUT=OUT
        r=engine.run(*inputs,c['pool'],True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'])
        assert abs(r['summary']['final_equity']-winner['result']['summary']['final_equity'])<.01
        winner['persisted_result']=r
    result=dict(winner=winner,best_unqualified=best_unqualified,qualified=len(qualified),candidates=len(candidates),excluded_specials=sorted(excluded),cleanup=iterations,
        protocol_sha256=digest(OUT/'PROTOCOL.json'),research_only=True,
        caveat='Selected on previously explored2021-2024 performance, hence development fit, not OOS proof. No post2024 results read, no deployment or source-model retraining.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('qualified',len(qualified),'winner',json.dumps(winner,ensure_ascii=False),'best_unqualified',json.dumps(best_unqualified,ensure_ascii=False))


if __name__=='__main__':main()
