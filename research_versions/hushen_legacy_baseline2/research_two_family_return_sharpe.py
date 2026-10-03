"""Bounded two-family tuning; freeze development winners before audit."""
import json
import numpy as np
import pandas as pd
import quarter_anchor_scan as q
from robust_policy_search import summarize

g=q.g
OUT=g.HERE/'two_family_return_sharpe_100k'
BASE=dict(count=6,power=.75,exposure=.8,threshold=.10,buffer=24,minimum=3000)
FAMILIES={'monthly':'固定月初','weekly_guard':'月初选股周度风控'}
PARAMS={'count':[5,7],'power':[.5,1.0],'exposure':[.7,.9]}

def configs():
    result=[]
    for family in FAMILIES:
        result.append(dict(BASE,family=family,name=family+'_base',changes={}))
        options=dict(PARAMS)
        if family=='weekly_guard':options['threshold']=[.08,.12]
        for key,values in options.items():
            for value in values:
                result.append(dict(BASE,**{'family':family,'name':family+'_'+key+'_'+str(value),key:value,'changes':{key:value}}))
    return result

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def admissible(a,b):
    return (a['median']>b['median']+.001 and a['sharpe']>b['sharpe']+.01
            and a['p10']>=b['p10']-.01 and a['drawdown']>=b['drawdown']-.02)

def objective(a,b):
    return (a['median']-b['median'])/.02+(a['sharpe']-b['sharpe'])/.10

def main():
    OUT.mkdir(exist_ok=True)
    cs=configs()
    save('protocol.json',dict(configs=cs,
        development='24 starts: Jan/Apr/Jul/Oct2020-2021, offsets0/5/10 sessions; 24months each',
        audit='24 starts: Jan-Aug2024, offsets0/5/10 sessions; already observed history, not pristine OOS',
        selection='Within each family: median annual >base+.1pp and median Sharpe>base+.01, P10>=base-1pp, worst DD>=base-2pp. Max joint objective annual gain/2pp + Sharpe gain/.10.',
        round2='At most one combination per family from top2 admissible one-factor changes with distinct parameter keys, if any. Development only. No further search.',
        freeze='Freeze one winner per family before audits. No reselection after audit.',
        acceptance='Audit same admissibility gate; both cost-stress periods median annual and Sharpe >=family base, P10>=base-1pp, DD>=base-2pp.',
        controls='100k, lots100, baseline6stocks/80%/inverse-downside power.75/buffer24/min3000. No changes to factor weights, date1, fees or price assumptions.',
        weekly_guard='Index60day drawdown threshold mild=parameter, severe=parameter+.05, exposure caps40%/20%. Monday postponed sell-only checks; recover only on month rebalance.',
        limitations='Fixed universe, approximate corporate actions, daily open not minute fills. Overlapping windows, repeatedly studied history. No formal baseline overwrite.'))
    idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
    cal=pd.DatetimeIndex(idx.date.drop_duplicates())
    f=pd.read_parquet(g.HERE/'cadence_multiround_100k/exact_date_factors.parquet')
    ranks={};drawdowns={}
    for d,x in f.groupby('execute_date'):
        x=x.sort_values('symbol').copy();assert x.signal_date.max()<d
        hist=idx[idx.date<=x.signal_date.iloc[0]]
        drawdowns[d]=hist.close.iloc[-1]/hist.close.tail(60).max()-1
        strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
        x['score']=.25*g.bt.rank01(x.amount20.to_numpy(),True)+.2*g.bt.rank01(x.near_high.to_numpy())+.55*g.bt.rank01(x.dividend.to_numpy())
        r=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
        ranks[d]=r.sort_values(['score','symbol'],ascending=[False,True]).copy()
    panel=g.bt.load_daily_panel(set().union(*(set(x.head(24).symbol) for x in ranks.values())))
    original={k:getattr(g.bt,k) for k in ('START','END','INITIAL_CASH','SLIPPAGE','COMMISSION','MIN_COMMISSION','apply_corporate_action')}
    def action(cash,positions,day,previous):
        cash=original['apply_corporate_action'](cash,positions,day,previous)
        for s,qty in positions.items():
            if s not in day.index or s not in previous:continue
            pre=float(day.loc[s,'preclose'])
            if np.isfinite(pre) and pre>0 and 1+1e-8<previous[s]/pre<=1.02:cash+=qty*(previous[s]-pre)
        return cash
    g.bt.INITIAL_CASH=100000.;g.bt.apply_corporate_action=action
    starts=pd.DatetimeIndex(g.features().execute_date.unique()).sort_values()
    expand=lambda ss:[cal[cal.get_loc(d)+n] for d in ss for n in (0,5,10)]
    dev=expand([d for d in starts if d.year in (2020,2021) and d.month in (1,4,7,10)])
    audit=expand([d for d in starts if d.year==2024 and d.month<=8])
    old=json.loads((g.HERE/'calendar_structure_100k/results.json').read_text(encoding='utf-8'))
    regression={(r['name'],r['start'],r['split']):r for r in old}
    rows=[];checks=[]
    def run(cfg,start,split,stress=False,full=False):
        end=original['END'] if full else start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        assert end<=original['END']
        g.bt.START=start;g.bt.END=end
        for key in ('SLIPPAGE','COMMISSION','MIN_COMMISSION'):setattr(g.bt,key,original[key]*(2 if stress else 1))
        monthly={start}
        for due in pd.date_range(start.replace(day=1),end,freq='MS'):
            actual=cal[cal.searchsorted(due)]
            if start<actual<=end:monthly.add(actual)
        def frame(d):
            r=ranks[d].copy();r['downside']=r.downside.pow(cfg['power']);return r
        def cap(d):
            if cfg['family']=='monthly':return cfg['exposure']
            draw=drawdowns[d];threshold=cfg['threshold']
            return min(cfg['exposure'],.2 if draw<-(threshold+.05) else (.4 if draw<-threshold else cfg['exposure']))
        rr={d:frame(d) for d in sorted(monthly)};ee={d:cap(d) for d in rr};limits={}
        if cfg['family']=='weekly_guard':
            for due in pd.date_range(start,end,freq='W-MON'):
                d=cal[cal.searchsorted(due)]
                if d>end or d in monthly or cap(d)>=cfg['exposure']:continue
                prior=max(m for m in monthly if m<d)
                rr[d]=rr[prior];ee[d]=cfg['exposure'];limits[d]=cap(d)
        c,t=g.bt.simulate(rr,.05,cfg['count'],cfg['buffer'],ee,1.5,panel,min_adjustment=cfg['minimum'],risk_only_limits=limits)
        assert (c.cash>=-.01).all()
        assert (t[t.side=='BUY'].quantity%100==0).all()
        assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
        assert not ((t.date.isin(limits))&(t.side=='BUY')).any()
        row=dict(name=cfg['name'],family=cfg['family'],split=split,stress=stress,start=str(start.date()),end=str(c.date.iloc[-1].date()),**q.measure(c),fees=float((t.commission+t.stamp_tax).sum()),orders=len(t))
        if not cfg['changes'] and not full:
            key=('fixed1' if cfg['family']=='monthly' else 'fixed_risk',row['start'],split)
            if key in regression:
                for k in ('annualized','drawdown','sharpe'):assert abs(row[k]-regression[key][k])<1e-9,(key,k)
                checks.append(key)
        rows.append(row);save('results.json',rows)
        if full:
            # Reusable trace without introducing spreadsheet artifacts.
            save(cfg['name']+'_full_curve.json',[dict(date=str(z.date.date()),equity=z.equity,cash=z.cash,holdings=int(z.holdings)) for z in c.itertuples()])
        return row
    development={};winners={};validation={};passed={}
    try:
        for cfg in cs:
            z=summarize([run(cfg,d,'dev') for d in dev]);development[cfg['name']]=z
            print('ROUND1',cfg['name'],z,flush=True)
        for family in FAMILIES:
            baseline=next(c for c in cs if c['name']==family+'_base');b=development[baseline['name']]
            eligible=sorted([c for c in cs if c['family']==family and admissible(development[c['name']],b)],key=lambda c:objective(development[c['name']],b),reverse=True)
            changes={}
            for cfg in eligible:
                key=next(iter(cfg['changes']))
                if key not in changes:changes.update(cfg['changes'])
                if len(changes)==2:break
            if len(changes)==2:
                combo={**baseline,**changes,'name':family+'_combo','changes':changes};cs.append(combo)
                save('round2_'+family+'.json',combo)
                z=summarize([run(combo,d,'dev') for d in dev]);development[combo['name']]=z
                print('ROUND2',combo['name'],z,flush=True)
                if admissible(z,b):eligible.append(combo)
            winners[family]=max(eligible,key=lambda c:objective(development[c['name']],b)) if eligible else baseline
        save('frozen_winners.json',winners)
        for family,winner in winners.items():
            baseline=next(c for c in cs if c['name']==family+'_base')
            for cfg in {c['name']:c for c in (baseline,winner)}.values():
                validation[cfg['name']]={}
                for split,ss,stress in [('audit',audit,False),('stress_dev',dev,True),('stress_audit',audit,True)]:
                    z=summarize([run(cfg,d,split,stress) for d in ss]);validation[cfg['name']][split]=z
                    print('VALIDATE',cfg['name'],split,z,flush=True)
            a=validation[winner['name']];b=validation[baseline['name']]
            ok=winner['name']!=baseline['name'] and admissible(a['audit'],b['audit'])
            ok=ok and all(a[s]['median']>=b[s]['median'] and a[s]['sharpe']>=b[s]['sharpe'] and a[s]['p10']>=b[s]['p10']-.01 and a[s]['drawdown']>=b[s]['drawdown']-.02 for s in ('stress_dev','stress_audit'))
            passed[family]=bool(ok)
        # Descriptive full period only AFTER selection and validation; never select from it.
        full=[]
        for family,winner in winners.items():
            baseline=next(c for c in cs if c['name']==family+'_base')
            for cfg in {c['name']:c for c in (baseline,winner)}.values():full.append(run(cfg,dev[0],'full',full=True))
        save('summary.json',dict(configs=cs,development=development,winners=winners,validation=validation,passed=passed,full=full,runs=len(rows),regression_checks=len(checks)))
        lines=['# 两方向年化与Sharpe调参','', '10万元，每个开发/验证窗口24个月；月初及移位5/10交易日起点。先开发筛选，再冻结验证，不按后段重选。','', '| 参数版本 | 年化中位数 | P10 | 最差窗口回撤 | Sharpe |','|---|---:|---:|---:|---:|']
        for cfg in cs:
            z=development[cfg['name']];lines.append('|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(cfg['name'],z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe']))
        lines+=['','| 冻结方向 | 参数 | 全部条件通过 |','|---|---|---|']
        for family,cfg in winners.items():lines.append('|%s|%s|%s|'%(FAMILIES[family],json.dumps(cfg['changes'],ensure_ascii=False),passed[family]))
        lines+=['','| 版本 | 验证 | 年化中位数 | P10 | 最差回撤 | Sharpe |','|---|---|---:|---:|---:|---:|']
        for name,tests in validation.items():
            for test,z in tests.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(name,test,z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe']))
        lines+=['','| 版本 | 全历史终值 | 年化 | 回撤 | Sharpe |','|---|---:|---:|---:|---:|']
        for z in full:lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(z['name'],z['final_equity'],z['annualized']*100,-z['drawdown']*100,z['sharpe']))
        lines+=['','总回测数：'+str(len(rows))+'；旧结果回归检查：'+str(len(checks)), '全历史为2020-01-02至2026-09-11描述性结果，不参与筛选；各24月窗口有重叠，后段历史已观察，不能声称独立样本外。平台成交差异、股票池与公司行动限制仍在。未替换正式策略。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('DONE',len(rows),passed,flush=True)
    finally:
        for k,v in original.items():setattr(g.bt,k,v)

if __name__=='__main__':main()
