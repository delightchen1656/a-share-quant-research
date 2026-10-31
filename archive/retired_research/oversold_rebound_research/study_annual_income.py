"""Revenue-first rule selection using only two previous matured training years.

Training selection uses a qfq price-path virtual account, NOT economic raw share
P&L. Final validation uses the existing raw-share/actions account engine.
All candidate exits, filters, and scoring are recorded before outer evaluation.
"""
import json
import math
import contextlib
import io
import numpy as np
import pandas as pd
from study import ROOT,SOURCE,digest
import account_backtest as engine

OUT=ROOT/'results_v12_annual_income'
FILTERS=['basic','price10','price20','price5to20','deep','deep_price20','deep_price10',
         'pos1_20','pos1_40','pos1_40_price20','volume12','volume15','price20_volume12',
         'shrink','deep_shrink','pos2_20','price10_pos1_40','price20_ma60slow']
TPS=[.02,.03,.04,.05]
HORIZONS=[1,2,3,4,5]


def mask(d,name):
    if name=='basic':return pd.Series(True,index=d.index)
    if name=='price10':return d.raw_signal_close<10
    if name=='price20':return d.raw_signal_close<20
    if name=='price5to20':return d.raw_signal_close.between(5,20,inclusive='left')
    if name=='deep':return d.below_ma20<=-.10
    if name=='deep_price20':return (d.below_ma20<=-.10)&(d.raw_signal_close<20)
    if name=='deep_price10':return (d.below_ma20<=-.10)&(d.raw_signal_close<10)
    if name=='pos1_20':return d.position1y<=.2
    if name=='pos1_40':return d.position1y<=.4
    if name=='pos1_40_price20':return (d.position1y<=.4)&(d.raw_signal_close<20)
    if name=='volume12':return d.volume_ratio>=1.2
    if name=='volume15':return d.volume_ratio>=1.5
    if name=='price20_volume12':return (d.raw_signal_close<20)&(d.volume_ratio>=1.2)
    if name=='shrink':return d.last3_volume_ratio<=.8
    if name=='deep_shrink':return (d.below_ma20<=-.10)&(d.last3_volume_ratio<=.8)
    if name=='pos2_20':return d.position2y<=.2
    if name=='price10_pos1_40':return (d.raw_signal_close<10)&(d.position1y<=.4)
    if name=='price20_ma60slow':return (d.raw_signal_close<20)&(d.ma60_slope10>-.03)
    raise KeyError(name)


def make_labels(d,paths):
    labels={};marks={}
    for (code,signal),g in paths.groupby(['code','signal_date']):
        key=(code,signal);g=g.sort_values('buy_offset');marks[key]={r.date:float(r.close_return) for r in g.itertuples() if r.observed}
        entry=g.iloc[0];rows={int(r.buy_offset):r for r in g.itertuples()}
        for tp in TPS:
            for horizon in HORIZONS:
                exit_day=None;ratio=None;phase=None
                for b in range(1,horizon+1):
                    bar=rows[b]
                    if not bar.observed:continue
                    if bar.open_return>=tp-1e-9:exit_day=bar.date;ratio=float(1+bar.open_return);phase='open';break
                    if bar.high_return>=tp-1e-9:exit_day=bar.date;ratio=1+tp;phase='touch';break
                if exit_day is None:
                    bar=rows[horizon]
                    if not bar.observed:continue
                    exit_day=bar.date;ratio=float(1+bar.close_return);phase='close'
                labels[(key,tp,horizon)]=dict(code=code,key=key,buy_date=entry.buy_date,raw_entry=float(entry.entry_raw),
                    exit_date=exit_day,ratio=ratio,phase=phase,mature=rows[5].date)
    return labels,marks


def virtual_account(events,labels,marks,tp,horizon,year,calendar):
    schedule={}
    for e in events.itertuples():
        trade=labels.get(((e.code,e.date),tp,horizon))
        if not trade or not trade['buy_date'].startswith(str(year)) or trade['exit_date']>f'{year}-12-31':continue
        schedule.setdefault(trade['buy_date'],[]).append(trade)
    cash=100000.;hold={};n=0;nav=[cash]
    def sell(code,day):
        nonlocal cash
        h=hold.pop(code);gross=h['notional']*h['ratio'];cash+=gross-engine.fee(gross,day,True)
    for day in calendar[year]:
        for code in list(hold):
            if hold[code]['exit_date']==day and hold[code]['phase']=='open':sell(code,day)
        for trade in sorted(schedule.get(day,[]),key=lambda x:x['code']):
            code=trade['code']
            if code in hold or len(hold)>=5:continue
            qty=engine.fit_shares(min(20000.,cash),trade['raw_entry'],day)
            if not qty:continue
            gross=qty*trade['raw_entry'];cash-=gross+engine.fee(gross,day)
            hold[code]=dict(trade,notional=gross,last_ratio=1.);n+=1
        for code in list(hold):
            if hold[code]['exit_date']==day:sell(code,day)
        value=0
        for h in hold.values():
            ret=marks[h['key']].get(day)
            if ret is not None:h['last_ratio']=1+ret
            value+=h['notional']*h['last_ratio']
        nav.append(cash+value)
    assert not hold
    nav=np.asarray(nav);dd=float((nav/np.maximum.accumulate(nav)-1).min())
    return dict(year=year,n=n,return_pct=cash/100000-1,max_drawdown=dd)


def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(filters=FILTERS,takeprofits=TPS,horizons=HORIZONS,outer_years=[2021,2022,2023,2024],
        training='Two previous signal/entry years; only B5-matured labels before outer Jan1. Candidate selection based on 100k/5-slot qfq-price-path proxy, not real share/cash economic returns.',
        criterion='Min12 actual virtual trades each year; both training-year returns>0; worst training DD<=20%; maximize min(year returns)-0.5*max(abs(year DD))+0.25*mean(year returns); otherwise cash.',
        validation='Chosen yearly rule frozen before raw-account testing. No changes based on outer-year performance. User accepts lower hit precision for revenue/DD.',boundary='2024-12-31')
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    features=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet')
    paths=pd.read_parquet(ROOT/'results_v6_first5/daily_paths.parquet')
    # Older records include all basic signals; training only uses mature past paths.
    calendar_dates=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    calendar={y:[x for x in calendar_dates if x.startswith(str(y))] for y in range(2018,2025)}
    labels,marks=make_labels(features,paths)
    mature={key:g.date.max() for key,g in paths.groupby(['code','signal_date'])}
    features['short_mature']=[mature[(r.code,r.date)] for r in features.itertuples()]
    choices=[];candidate_scores=[];selections={};annual_rules={}
    for pool in ['sample','leaders']:
        cohort=features.loc[features.is_leader] if pool=='leaders' else features
        chosen_ids=set();configs={}
        for year in range(2021,2025):
            train=cohort.loc[(cohort.short_mature<f'{year}-01-01') & cohort.year.between(year-2,year-1)]
            assert train.short_mature.max()<f'{year}-01-01'
            options=[]
            for name in FILTERS:
                subset=train.loc[mask(train,name)]
                for tp in TPS:
                    for horizon in HORIZONS:
                        scores=[virtual_account(subset,labels,marks,tp,horizon,y,calendar) for y in [year-2,year-1]]
                        worst=min(x['return_pct'] for x in scores);mean=np.mean([x['return_pct'] for x in scores]);dd=max(-x['max_drawdown'] for x in scores)
                        score=worst-.5*dd+.25*mean
                        eligible=all(x['n']>=12 and x['return_pct']>0 for x in scores) and dd<=.20
                        item=dict(pool=pool,outer_year=year,filter=name,take_profit=tp,forced_day=horizon,
                            train_scores=scores,score=float(score),eligible=eligible)
                        candidate_scores.append(item)
                        if eligible:options.append(item)
            pick=max(options,key=lambda x:x['score']) if options else None
            choices.append(dict(pool=pool,year=year,pick=pick,eligible_candidates=len(options)))
            if pick:
                configs[year]=dict(take_profit=pick['take_profit'],forced_day=pick['forced_day'])
                test=cohort.loc[cohort.year==year];test=test.loc[mask(test,pick['filter'])]
                chosen_ids.update(zip(test.code,test.date))
            print('selection',pool,year,'picked',None if pick is None else (pick['filter'],pick['take_profit'],pick['forced_day']),flush=True)
        selections[pool]=chosen_ids;annual_rules[pool]=configs
    (OUT/'choices.json').write_text(json.dumps(choices,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'training_candidates.json').write_text(json.dumps(candidate_scores,ensure_ascii=False,indent=2),encoding='utf8')
    inputs=list(engine.prepare())
    prior=json.loads((ROOT/'results_v11_filtered_horizons/summary.json').read_text(encoding='utf8'))
    excluded={tuple(x) for x in prior['excluded_specials']};base=inputs[0].copy();inputs[1]=selections
    iterations=[]
    for attempt in range(5):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy();results=[];new=set()
        engine.OUT=OUT
        for pool in ['sample','leaders']:
            for capital,slots in [(1000000,50),(100000,5)]:
                r=engine.run(*inputs,pool,True,capital,slots,annual_rules=annual_rules[pool])
                results.append(r)
                t=pd.read_parquet(OUT/r['key']/'trades.parquet')
                for _,e in t.loc[t.reason.str.contains('delayed')].iterrows():new.add((e.code,e.signal_date))
        iterations.append(dict(excluded=sorted(excluded),new=sorted(new)))
        if not new:break
        excluded.update(new)
    else:raise RuntimeError('Special exclusions did not stabilize')
    result=dict(results=results,choices=choices,excluded_specials=sorted(excluded),iterations=iterations,
        protocol_sha256=digest(OUT/'PROTOCOL.json'),features_sha256=digest(ROOT/'results_v5_long_position/events.parquet'),
        caveats=['All pre2025 periods previously explored: research-time walk-forward evaluation, not untouched blind test.',
                 'Train selection proxy uses adjusted paths, not literal raw-share economic profit; final accounts use raw shares/actions.',
                 'Current 947-stock retrospective cohort, current leader membership; known special events excluded ex post.',
                 'No 2025+ data, no production/viewer changes. Annual rule choices depend on prior matured labels only.'])
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('FINAL',json.dumps(result['results'],ensure_ascii=False))


if __name__=='__main__':main()
