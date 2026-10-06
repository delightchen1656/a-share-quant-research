from pathlib import Path
import importlib.util,json,hashlib,sys
import pandas as pd
import numpy as np
HERE=Path(__file__).resolve().parent;BASE=HERE.parents[1]
def dump(n,x):(HERE/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def prepare():
    p=mod(BASE/'test2_retrain_2022/pipeline.py','feature_utils');p.dump=dump
    ranks,eligible,prices,dates=p.features('evaluation')
    score=p.smooth(ranks,eligible,[.35,.20,.25,.20]);starts=dates[(dates>='2020-01-01')&(dates<'2020-02-01')][:1]
    wanted=set(starts)
    for i,d in enumerate(dates):
        if d<starts[0]:continue
        prev=dates[i-1]
        if (i-1)%20==0:wanted.add(d)
    signals=sorted(dates[dates.get_loc(d)-1] for d in wanted)
    rankings={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist() for d in signals}
    dump('rankings.json',rankings)
    entry=BASE/'test2_weekly/uploaded_source.py'
    dump('protocol.json',dict(strategy_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),weights=[-.35,-.20,.25,-.20],starts=[str(d.date()) for d in starts],end=str(dates[-1].date()),initial_cash=100000,
       notes='Frozen uploaded original 20-session strategy; no fitting or selection. Independent empty-start accounts, daily open matching approximation. Same cash/action/tax ledger as prior studies. 2020 onwards retrospective overlapping paths, not independent samples.'))
    print('PREPARED',len(starts),'starts',len(rankings),'rankings',flush=True)
def run():
    import ledger
    p=mod(BASE/'test2_retrain_2022/pipeline.py','utils');p.HERE=HERE
    engine=mod(HERE/'weekly_engine.py','weekly_engine');entry=BASE/'test2_weekly/uploaded_source.py'
    engine.load_model=lambda k:engine.module(entry,'weekly_export')
    old=BASE/'start_date_study';dates=pd.DatetimeIndex(pd.read_parquet(old/'benchmark.parquet').date)
    ranks=p.read('rankings.json');protocol=p.read('protocol.json');assert hashlib.sha256(entry.read_bytes()).hexdigest()==protocol['strategy_sha256']
    days,actions,outs=ledger.load(p,engine,ranks,dates,old)
    results=[];curves=[];trades=[];issues={};ref={};schedules={}
    for start in pd.to_datetime(protocol['starts']):
        a=engine.Account('D11',start,actions,days,outs);schedule=[]
        for i in range(dates.get_loc(start),len(dates)):
            d=dates[i];previous_targets=a.m.g.alpha_targets;a.step(d,i,dates[i-1],ranks)
            expected=d==start or (i-1)%20==0
            assert (a.m.g.alpha_targets is not previous_targets)==expected
            if expected:schedule.append(str(d.date()))
        assert a.trades
        q=pd.DataFrame(a.curve);nav=q.equity.to_numpy();dd=nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]-1
        results.append(dict(start=str(start.date()),end=str(dates[-1].date()),final_equity=float(nav[-1]),total_return=float(nav[-1]/100000-1),
            cagr=float((nav[-1]/100000)**(365.25/((dates[-1]-start).days+1))-1),max_drawdown=float(-dd.min()),fees=a.fees,dividend_tax=a.tax,
            trades=len(a.trades),avg_exposure=float(q.exposure.mean()),final_cash=a.cash,final_market_value=float(q.market_value.iloc[-1]),unresolved_actions=len(a.issues),capacity_rejections=a.capacity_hits))
        curves.extend(a.curve);trades.extend(a.trades);issues.update(a.issues);ref.update(a.reference_diffs);schedules[str(start.date())]=schedule
        print('RUN',start.date(),round(nav[-1],2),'issues',len(a.issues),flush=True)
    dump('results.json',results);dump('unresolved_actions.json',issues);dump('reference_differences.json',ref);dump('schedules.json',schedules)
    pd.DataFrame(curves).to_parquet(HERE/'daily_equity.parquet',index=False);pd.DataFrame(trades).to_parquet(HERE/'trades.parquet',index=False)
if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
