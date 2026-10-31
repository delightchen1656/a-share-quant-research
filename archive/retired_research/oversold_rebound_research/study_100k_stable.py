"""100k only: slots/risk exits chosen on two prior matured years, never outer P&L."""
import json
import numpy as np
import pandas as pd
from study import ROOT,SOURCE,digest
from study_annual_income import FILTERS,mask
import account_backtest as engine

OUT=ROOT/'results_v13_100k_stable'
TPS=[.03,.05];DAYS=[2,3,5];STOPS=[None,.05,.08];SLOTS=[5,10,20]


def label_paths(paths):
    labels={};marks={}
    for key,g in paths.groupby(['code','signal_date']):
        g=g.sort_values('buy_offset');entry=g.iloc[0]
        marks[key]={r.date:float(r.close_return) for r in g.itertuples() if r.observed}
        rows={int(r.buy_offset):r for r in g.itertuples()}
        for tp in TPS:
            for horizon in DAYS:
                for sl in STOPS:
                    out=None
                    for b in range(1,horizon+1):
                        bar=rows[b]
                        if not bar.observed:continue
                        if sl is not None and bar.open_return<=-sl+1e-9:out=(bar.date,1+bar.open_return,'open');break
                        if bar.open_return>=tp-1e-9:out=(bar.date,1+bar.open_return,'open');break
                        if sl is not None and bar.low_return<=-sl+1e-9:out=(bar.date,1-sl,'stop');break
                        if bar.high_return>=tp-1e-9:out=(bar.date,1+tp,'touch');break
                    if out is None:
                        bar=rows[horizon]
                        if not bar.observed:continue
                        out=(bar.date,1+bar.close_return,'close')
                    labels[(key,tp,horizon,sl)]=dict(code=key[0],key=key,buy_date=entry.buy_date,raw_entry=float(entry.entry_raw),
                        exit_date=out[0],ratio=float(out[1]),phase=out[2],mature=rows[5].date)
    return labels,marks


def virtual(events,labels,marks,tp,horizon,sl,slots,year,calendar):
    schedule={}
    for e in events.itertuples():
        t=labels.get(((e.code,e.date),tp,horizon,sl))
        if t and t['buy_date'].startswith(str(year)) and t['exit_date']<=f'{year}-12-31':schedule.setdefault(t['buy_date'],[]).append(t)
    cash=100000.;hold={};n=0;nav=[cash]
    def close(code,day):
        nonlocal cash
        h=hold.pop(code);gross=h['notional']*h['ratio'];cash+=gross-engine.fee(gross,day,True)
    for day in calendar[year]:
        for code in list(hold):
            if hold[code]['exit_date']==day and hold[code]['phase']=='open':close(code,day)
        for t in sorted(schedule.get(day,[]),key=lambda x:x['code']):
            if t['code'] in hold or len(hold)>=slots:continue
            qty=engine.fit_shares(min(100000/slots,cash),t['raw_entry'],day)
            if not qty:continue
            gross=qty*t['raw_entry'];cash-=gross+engine.fee(gross,day)
            hold[t['code']]=dict(t,notional=gross,last_ratio=1.);n+=1
        for code in list(hold):
            if hold[code]['exit_date']==day:close(code,day)
        value=0.
        for h in hold.values():
            r=marks[h['key']].get(day)
            if r is not None:h['last_ratio']=1+r
            value+=h['notional']*h['last_ratio']
        nav.append(cash+value)
    assert not hold
    v=np.array(nav);dd=float((v/np.maximum.accumulate(v)-1).min())
    return dict(year=year,n=n,return_pct=cash/100000-1,max_drawdown=dd)


def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(filters=FILTERS,take_profit=TPS,forced_day=DAYS,stop_loss=STOPS,slots=SLOTS,capital=100000,
        selection='Before each year use prior2 years with B5-matured labels; min12 virtual trades and positive return in each, worst DD<=20%; maximize min annual return-0.5*max DD+0.25*mean annual return. No eligible candidate => cash.',
        training_proxy='qfq price-path cash/slot proxy, not raw share/corporate action economic accounting; final results use raw account engine.',
        stop_rule='T+1; opening gaps at open; otherwise stop before TP when both hit within daily bar.',
        history='All pre2025 data already explored; research walk-forward, not untouched blind validation. Broader rule design informed by earlier development runs, never claimed newly blind.')
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    f=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet');paths=pd.read_parquet(ROOT/'results_v6_first5/daily_paths.parquet')
    labels,marks=label_paths(paths)
    mature={key:g.date.max() for key,g in paths.groupby(['code','signal_date'])}
    f['short_mature']=[mature[(r.code,r.date)] for r in f.itertuples()]
    cal=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    calendar={y:[x for x in cal if x.startswith(str(y))] for y in range(2019,2025)}
    choices=[];all_scores=[];selected={};annual={}
    for pool in ['sample','leaders']:
        cohort=f.loc[f.is_leader] if pool=='leaders' else f
        ids=set();configs={}
        for year in range(2021,2025):
            train=cohort.loc[(cohort.short_mature<f'{year}-01-01') & cohort.year.between(year-2,year-1)]
            assert train.short_mature.max()<f'{year}-01-01'
            options=[]
            for name in FILTERS:
                sub=train.loc[mask(train,name)]
                for tp in TPS:
                    for horizon in DAYS:
                        for sl in STOPS:
                            for slots in SLOTS:
                                scores=[virtual(sub,labels,marks,tp,horizon,sl,slots,y,calendar) for y in [year-2,year-1]]
                                worst=min(x['return_pct'] for x in scores);avg=float(np.mean([x['return_pct'] for x in scores]));dd=max(-x['max_drawdown'] for x in scores)
                                eligible=all(x['n']>=12 and x['return_pct']>0 for x in scores) and dd<=.20
                                item=dict(pool=pool,year=year,filter=name,take_profit=tp,forced_day=horizon,stop_loss=sl,slots=slots,
                                    training=scores,score=worst-.5*dd+.25*avg,eligible=eligible)
                                all_scores.append(item)
                                if eligible:options.append(item)
            pick=max(options,key=lambda x:x['score']) if options else None
            choices.append(dict(pool=pool,year=year,pick=pick,eligible_candidates=len(options)))
            if pick:
                configs[year]={k:pick[k] for k in ['take_profit','forced_day','stop_loss','slots']}
                outer=cohort.loc[cohort.year==year];outer=outer.loc[mask(outer,pick['filter'])]
                ids.update(zip(outer.code,outer.date))
            print(pool,year,'choice',None if pick is None else {k:pick[k] for k in ['filter','take_profit','forced_day','stop_loss','slots']},flush=True)
        selected[pool]=ids;annual[pool]=configs
    (OUT/'choices.json').write_text(json.dumps(choices,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'training_scores.json').write_text(json.dumps(all_scores,ensure_ascii=False,indent=2),encoding='utf8')
    inputs=list(engine.prepare());inputs[1]=selected;base=inputs[0].copy()
    prior=json.loads((ROOT/'results_v11_filtered_horizons/summary.json').read_text(encoding='utf8'))
    excluded={tuple(x) for x in prior['excluded_specials']};iterations=[]
    for attempt in range(5):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy();engine.OUT=OUT;results=[];new=set()
        for pool in ['sample','leaders']:
            r=engine.run(*inputs,pool,True,100000,20,annual_rules=annual[pool]);results.append(r)
            trades=pd.read_parquet(OUT/r['key']/'trades.parquet')
            for _,e in trades.loc[trades.reason.str.contains('delayed')].iterrows():new.add((e.code,e.signal_date))
        iterations.append(dict(excluded=sorted(excluded),new=sorted(new)))
        if not new:break
        excluded.update(new)
    else:raise RuntimeError('Special case exclusions did not stabilize')
    result=dict(results=results,choices=choices,excluded_specials=sorted(excluded),cleanup=iterations,
        protocol_sha256=digest(OUT/'PROTOCOL.json'),annual_rulebook=annual,
        note='Only100k. Annual slots allocate initial capital/slot count, not NAV; unspent profits remain cash. ML40day high precision constraint removed by user. No2025+ data, no production deployment.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('FINAL',json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main()
