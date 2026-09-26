"""Two bounded rounds: cadence/signal structures, then frozen-candidate validation."""
import json
import numpy as np
import pandas as pd
import quarter_anchor_scan as q
from robust_policy_search import summarize

g=q.g
OUT=g.HERE/'cadence_multiround_100k'
BASE=dict(count=6,buffer=24,minimum=3000,power=.75,cadence='monthly',signal='regime',guard=False)
CONFIGS=[dict(BASE,name='control',label='月度6只基准'),
    dict(BASE,name='monthly_guard',label='月度弱市降仓',guard=True),
    dict(BASE,name='biweekly',label='双周原选股',cadence='biweekly'),
    dict(BASE,name='weekly',label='每周原选股',cadence='weekly'),
    dict(BASE,name='biweekly_lowturn',label='双周低换手',cadence='biweekly',buffer=32,minimum=5000),
    dict(BASE,name='weekly_lowturn',label='每周低换手',cadence='weekly',buffer=32,minimum=5000),
    dict(BASE,name='monthly_trend',label='月度趋势过滤降仓',signal='trend',guard=True),
    dict(BASE,name='biweekly_trend',label='双周趋势过滤降仓',cadence='biweekly',signal='trend',guard=True),
    dict(BASE,name='weekly_trend',label='每周趋势过滤降仓',cadence='weekly',signal='trend',guard=True),
    dict(BASE,name='weekly_quality',label='每周质量低风险',cadence='weekly',signal='quality')]


def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    OUT.mkdir(exist_ok=True);q.OUT=OUT
    save('protocol.json',dict(configs=CONFIGS,capital=100000,
        round1='24 monthly starts 2020-2021, 24-month windows. Max P10 subject to median>=control-1pp and worst DD>=control-2pp; freeze single winner before audit.',
        round2='Winner buffer +/-4 as sensitivity, NOT new selection. 16 shifted development starts (+5/+10 sessions on Jan/Apr/Jul/Oct 2020-2021), and 24 shifted audit starts (0/+5/+10 sessions Jan-Aug 2024). Double costs on original 24 dev and 8 audit starts.',
        acceptance='Candidate must improve P10 on both shifted dev and audit with median>=control-1pp and DD>=control-2pp; stress P10 improves in both periods. Both neighbors dev P10>=control-1pp, median>=control-1pp, DD>=control-2pp. No audit-driven reselection.',
        scheduling='Immediate entry at each start; monthly anchor day, weekly every7 calendar days, biweekly every14. Closed sessions postponed, anchor unchanged. Strict prior-session signals.',
        star_analogy='Trend eligibility and exits at rebalance + index-based exposure reduction, NOT STAR ML model or daily stop-loss clone.',
        limitations=['Daily-open proxy, no minute parity. Fixed historical universe, approximate corporate actions.',
            'Overlapping/repeatedly observed history, not pristine OOS. No baseline replacement.']))
    index=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    index['date']=pd.to_datetime(index.date);index=index.sort_values('date')
    calendar=pd.DatetimeIndex(index.date.drop_duplicates())
    days=calendar[(calendar>=g.bt.START)&(calendar<=g.bt.END)]
    f=q.build_features([(d,calendar[calendar.get_loc(d)-1]) for d in days])
    ranks={n:{} for n in ('regime','trend','quality')};exposures={}
    for d,frame in f.groupby('execute_date'):
        x=frame.sort_values('symbol').copy()
        hist=index[index.date<=x.signal_date.iloc[0]]
        strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
        draw=hist.close.iloc[-1]/hist.close.tail(60).max()-1
        exposures[d]=.2 if draw<-.10 else (.8 if strong else .4)
        attack=.25*g.bt.rank01(x.amount20.to_numpy(),True)+.2*g.bt.rank01(x.near_high.to_numpy())+.55*g.bt.rank01(x.dividend.to_numpy())
        x['score']=attack
        r=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
        ranks['regime'][d]=r.sort_values(['score','symbol'],ascending=[False,True])
        ranks['quality'][d]=g.score(x,'quality')
        # No daily stop orders: failing the trend screen triggers exit at next rebalance.
        trend=x[(x.below_ma60<=1e-12)&(x.near_high>=.85)]
        ranks['trend'][d]=trend.sort_values(['score','symbol'],ascending=[False,True])
    union=set().union(*(set(x.head(36).symbol) for rr in ranks.values() for x in rr.values()))
    panel=g.bt.load_daily_panel(union)
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
    dev=[d for d in starts if d.year in (2020,2021)]
    audit=[d for d in starts if d.year==2024 and d.month<=8]
    shift=lambda d,n:calendar[calendar.get_loc(d)+n]
    shifted_dev=[shift(d,n) for d in dev if d.month in (1,4,7,10) for n in (5,10)]
    shifted_audit=[shift(d,n) for d in audit for n in (0,5,10)]
    rows=[]
    def run(cfg,start,split,stress=False):
        g.bt.START=start;g.bt.END=start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        if split in ('dev','neighbor','shift_dev'):assert g.bt.END<pd.Timestamp('2024-01-01')
        assert g.bt.END<=original['END']
        for key in ('SLIPPAGE','COMMISSION','MIN_COMMISSION'):setattr(g.bt,key,original[key]*(2 if stress else 1))
        rr={};ee={};n=0
        while True:
            if cfg['cadence']=='monthly':due=start+pd.DateOffset(months=n)
            else:due=start+pd.Timedelta(days=n*(7 if cfg['cadence']=='weekly' else 14))
            if due>g.bt.END:break
            d=calendar[calendar.searchsorted(due)];n+=1
            if d>g.bt.END:break
            r=ranks[cfg['signal']][d].copy()
            exposure=exposures[d] if cfg['guard'] else .8
            if len(r)<cfg['count']:
                r=ranks['regime'][d].copy();exposure=0.
            r['downside']=r.downside.pow(cfg['power'])
            rr[d]=r;ee[d]=exposure
        c,t=g.bt.simulate(rr,.05,cfg['count'],cfg['buffer'],ee,1.5,panel,min_adjustment=cfg['minimum'])
        assert (c.cash>=-.01).all()
        assert (t[t.side=='BUY'].quantity%100==0).all()
        assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
        row=dict(name=cfg['name'],split=split,stress=stress,start=str(start.date()),end=str(c.date.iloc[-1].date()),
            **q.measure(c),fees=float((t.commission+t.stamp_tax).sum()),orders=len(t),cash_fraction=float((c.cash/c.equity).mean()))
        rows.append(row);save('results.json',rows)
        return row
    def gate(a,b):return a['p10']>b['p10'] and a['median']>=b['median']-.01 and a['drawdown']>=b['drawdown']-.02
    try:
        development={}
        for cfg in CONFIGS:
            development[cfg['name']]=summarize([run(cfg,d,'dev') for d in dev])
            print('ROUND1',cfg['name'],development[cfg['name']],flush=True)
        eligible=[c for c in CONFIGS[1:] if gate(development[c['name']],development['control'])]
        winner=max(eligible,key=lambda c:development[c['name']]['p10']) if eligible else CONFIGS[0]
        save('frozen_round1.json',dict(winner=winner,eligible=[c['name'] for c in eligible],development=development))
        neighbors={}
        for delta in (-4,4):
            cfg=dict(winner,name='neighbor_buffer_'+str(winner['buffer']+delta),buffer=winner['buffer']+delta)
            neighbors[cfg['name']]=summarize([run(cfg,d,'neighbor') for d in dev])
            print('NEIGHBOR',cfg['name'],neighbors[cfg['name']],flush=True)
        validation={}
        for cfg in {c['name']:c for c in [CONFIGS[0],winner]}.values():
            data={}
            for split,ss,stress in [('shift_dev',shifted_dev,False),('audit',shifted_audit,False),('stress_dev',dev,True),('stress_audit',audit,True)]:
                data[split]=summarize([run(cfg,d,split,stress) for d in ss])
                print('ROUND2',cfg['name'],split,data[split],flush=True)
            validation[cfg['name']]=data
        ref=development['control']
        stable=all(s['p10']>=ref['p10']-.01 and s['median']>=ref['median']-.01 and s['drawdown']>=ref['drawdown']-.02 for s in neighbors.values())
        name=winner['name'];passed=name!='control' and stable
        if passed:
            passed=all(gate(validation[name][s],validation['control'][s]) for s in ('shift_dev','audit'))
            passed=passed and all(validation[name][s]['p10']>validation['control'][s]['p10'] for s in ('stress_dev','stress_audit'))
        result=dict(winner=winner,development=development,neighbors=neighbors,validation=validation,
            neighbor_stability=stable,passed=bool(passed),runs=len(rows),platform_parity=False)
        save('summary.json',result)
        lines=['# 月度/双周/周度多方向研究','', '10万元、目标6只；真实调仓日前一交易日信号，日开盘成交近似。月度对照是启动日锚定月度，而不是月初缓存版本。',
            '第一轮10方向×24起点，各持有24个月。第二轮冻结候选，检查邻近保留区间、移位起点、后段与双倍成本。','',
            '| 方案 | 开发年化中位数 | 开发年化P10 | 最差窗口回撤 | Sharpe中位数 | 中位费用 |', '|---|---:|---:|---:|---:|---:|']
        for cfg in CONFIGS:
            z=development[cfg['name']]
            lines.append('| %s | %.2f%% | %.2f%% | %.2f%% | %.3f | %.2f |'%(cfg['label'],z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe'],z['fees']))
        lines+=['','冻结候选：'+winner['label'],'是否通过全部预设条件：'+str(bool(passed)),'',
            '| 方案 | 验证项 | 年化中位数 | 年化P10 | 最差回撤 |','|---|---|---:|---:|---:|']
        for name,tests in validation.items():
            for test,z in tests.items():lines.append('| %s | %s | %.2f%% | %.2f%% | %.2f%% |'%(name,test,z['median']*100,z['p10']*100,-z['drawdown']*100))
        lines+=['','趋势方向仅借鉴趋势过滤、退出和降仓结构，没有复制科创机器学习模型。退出在调仓日检查，不是日内触价止损。',
            '不按后段结果重新挑候选；未修改任何正式基准或平台代码。','历史已被反复观察，重叠窗口不独立；股票池、公司行动和分钟成交差异仍未解决，不是收益保证。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('DONE',len(rows),winner['name'],passed,flush=True)
    finally:
        for k,v in original.items():setattr(g.bt,k,v)


if __name__=='__main__':main()
