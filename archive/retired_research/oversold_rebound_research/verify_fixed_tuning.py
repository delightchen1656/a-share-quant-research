"""Reconcile baseline on identical exclusions, rerank unchanged grid fairly if needed."""
import json
import pandas as pd
from study import ROOT,digest
from tune_fixed_income import OUT
import account_backtest as engine


def main():
    path=OUT/'summary.json';m=json.loads(path.read_text(encoding='utf8'))
    inputs=list(engine.prepare());exc={tuple(x) for x in m['excluded_specials']}
    inputs[0]=inputs[0].loc[[(r.code,r.date) not in exc for r in inputs[0].itertuples()]].copy()
    f=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet')
    baseline_folder=OUT/'baseline_common';baseline_folder.mkdir(exist_ok=True);engine.OUT=baseline_folder
    sub=f.loc[(f.raw_signal_close<10)&(f.below_ma20<=-.10)];ids=set(zip(sub.code,sub.date));inputs[1]={'sample':ids,'leaders':ids}
    baseline=engine.run(*inputs,'sample',True,100000,5,forced_day=3,take_profit=.05,quiet=True)
    assert not baseline['specials']
    old_baseline=m['baseline'];old_result=m['persisted_result']
    rows=json.loads((OUT/'comparison.json').read_text(encoding='utf8'))
    minimum=min(x['return_pct'] for x in baseline['yearly']);total=baseline['summary']['total_return'];dd=-baseline['summary']['max_drawdown']
    for row in rows:
        r=row['result'];row['all_year_dominant']=row['qualified'] and -r['summary']['max_drawdown']<=dd+1e-9 and all(y['return_pct']>=b['return_pct']-1e-9 for y,b in zip(r['yearly'],baseline['yearly']))
        row['balanced_dominant']=row['qualified'] and -r['summary']['max_drawdown']<=dd+1e-9 and row['worst_year']>=minimum-1e-9 and r['summary']['total_return']>=total-1e-9
    good=[x for x in rows if x['qualified']]
    tier,pool=next((name,a) for name,a in [('all_year_dominant',[x for x in good if x['all_year_dominant']]),('balanced_dominant',[x for x in good if x['balanced_dominant']]),('positive_with_dd12',good)] if a)
    stable=[x for x in pool if x['neighborhood']['stable']]
    winner=max(stable or pool,key=lambda x:(x['worst_year'],x['result']['summary']['total_return'],x['result']['summary']['max_drawdown']))
    c=winner['config'];sub=f.loc[(f.raw_signal_close<c['price'])&(f.below_ma20<=-c['deviation'])];ids=set(zip(sub.code,sub.date));inputs[1]={'sample':ids,'leaders':ids};engine.OUT=OUT
    r=engine.run(*inputs,'sample',True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'],quiet=True)
    assert abs(r['summary']['final_equity']-winner['result']['summary']['final_equity'])<.01 and not r['specials']
    t=pd.read_parquet(OUT/r['key']/'trades.parquet')
    assert abs(100000+t.pnl.sum()-r['summary']['final_equity'])<.01
    assert t.buy_offset.between(1,c['forced_day']).all()
    m.update(baseline_original=old_baseline,baseline=baseline,winner=winner,persisted_result=r,selected_tier=tier,
        baseline_same_exclusions_verified=True,baseline_original_equity_difference=baseline['summary']['final_equity']-old_baseline['summary']['final_equity'],
        fair_verification_selected_same_parameters=c==m['winner']['config'],
        all_year_dominant=sum(x['all_year_dominant'] for x in rows),balanced_dominant=sum(x['balanced_dominant'] for x in rows))
    path.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    check=dict(cash_pnl_reconciled=True,no_delayed_exit=True,exit_within_horizon=True,
        baseline_same_exclusion_cohort=True,baseline_original_equity_difference=m['baseline_original_equity_difference'],
        old_v14_engine_hash_still_matches=digest(ROOT/'account_backtest.py')==json.loads((ROOT/'results_v14_fixed_income/FROZEN_RULE.json').read_text(encoding='utf8'))['hashes']['account_backtest.py'])
    (OUT/'VERIFICATION.json').write_text(json.dumps(check,indent=2),encoding='utf8')
    print('baseline_difference',m['baseline_original_equity_difference'],'config',c,'winner',r['summary']['final_equity'])


if __name__=='__main__':main()
