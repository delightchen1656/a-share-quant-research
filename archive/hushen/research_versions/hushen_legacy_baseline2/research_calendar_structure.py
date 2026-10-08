"""Frozen small structure search with shifted entries included BEFORE selection."""
import json
import numpy as np
import pandas as pd
import quarter_anchor_scan as q
from robust_policy_search import summarize

g=q.g
OUT=g.HERE/'calendar_structure_100k'
CONFIGS=[dict(name='control',label='启动日锚定月度',day=0,buffer=24,risk=False),
 dict(name='fixed1',label='固定每月1日',day=1,buffer=24,risk=False),
 dict(name='fixed11',label='固定每月11日',day=11,buffer=24,risk=False),
 dict(name='fixed21',label='固定每月21日',day=21,buffer=24,risk=False),
 dict(name='fixed_loose',label='固定月初宽保留区间',day=1,buffer=32,risk=False),
 dict(name='fixed_tight',label='固定月初窄保留区间',day=1,buffer=12,risk=False),
 dict(name='fixed_risk',label='固定月初选股周度风控',day=1,buffer=24,risk=True),
 dict(name='anchor_risk',label='锚定月度选股周度风控',day=0,buffer=24,risk=True)]

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    OUT.mkdir(exist_ok=True)
    save('protocol.json',dict(configs=CONFIGS,capital=100000,count=6,power=.75,
      development='2020/2021 Jan Apr Jul Oct first session +0/5/10 sessions, 24 starts, each24months',
      audit='2024 Jan-Aug first session +0/5/10 sessions, 24 starts, each24months',
      selection='Freeze best development P10, median>=control-1pp, worst DD>=control-2pp; no audit reselection',
      acceptance='Audit same gate, doubled-cost dev/audit P10 higher than control. If no candidate, retain control without promotion.',
      execution='Immediate entry, then fixed calendar day (closed session postponed) or start-day anchored monthly. Prior-session signals. Weekly risk Monday postponed, sell only to .4 at index60day drawdown<-10%, .2 below-15%, otherwise no action. Restore exposure only at monthly rebalance.',
      limitations='Already observed overlapping history, daily-open approximation, frozen universe and approximate corporate actions. Not platform parity or independent OOS.'))
    idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
    cal=pd.DatetimeIndex(idx.date.drop_duplicates())
    f=pd.read_parquet(g.HERE/'cadence_multiround_100k/exact_date_factors.parquet')
    ranks={};risk={}
    for d,x in f.groupby('execute_date'):
        x=x.sort_values('symbol').copy()
        assert x.signal_date.max()<d
        hist=idx[idx.date<=x.signal_date.iloc[0]]
        draw=hist.close.iloc[-1]/hist.close.tail(60).max()-1
        risk[d]=.2 if draw<-.15 else (.4 if draw<-.10 else .8)
        strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
        x['score']=.25*g.bt.rank01(x.amount20.to_numpy(),True)+.2*g.bt.rank01(x.near_high.to_numpy())+.55*g.bt.rank01(x.dividend.to_numpy())
        r=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
        r=r.sort_values(['score','symbol'],ascending=[False,True]).copy()
        r['downside']=r.downside.pow(.75);ranks[d]=r
    panel=g.bt.load_daily_panel(set().union(*(set(x.head(32).symbol) for x in ranks.values())))
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
    old=json.loads((g.HERE/'cadence_multiround_100k/results.json').read_text(encoding='utf-8'))
    regression={r['start']:r for r in old if r['name']=='control' and r['split'] in ('dev','shift_dev','audit')}
    rows=[];checks=[]
    def run(cfg,start,split,stress=False):
        end=start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        assert end<=original['END']
        if split=='dev':assert end<pd.Timestamp('2024-01-01')
        g.bt.START=start;g.bt.END=end
        for key in ('SLIPPAGE','COMMISSION','MIN_COMMISSION'):setattr(g.bt,key,original[key]*(2 if stress else 1))
        monthly={start}
        if cfg['day']:
            due=[pd.Timestamp(d.year,d.month,cfg['day']) for d in pd.date_range(start.replace(day=1),end,freq='MS')]
        else:due=[start+pd.DateOffset(months=n) for n in range(1,25)]
        for d in due:
            actual=cal[cal.searchsorted(d)]
            if start<actual<=end:monthly.add(actual)
        rr={d:ranks[d] for d in sorted(monthly)}
        ee={d:risk[d] if cfg['risk'] else .8 for d in rr}
        limits={}
        if cfg['risk']:
            for monday in pd.date_range(start,end,freq='W-MON'):
                d=cal[cal.searchsorted(monday)]
                if d>end or d in monthly or risk[d]>=.8:continue
                prior=max(m for m in monthly if m<d)
                rr[d]=ranks[prior];ee[d]=.8;limits[d]=risk[d]
        c,t=g.bt.simulate(rr,.05,6,cfg['buffer'],ee,1.5,panel,min_adjustment=3000,risk_only_limits=limits)
        assert (c.cash>=-.01).all()
        assert (t[t.side=='BUY'].quantity%100==0).all()
        assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
        assert not ((t.date.isin(limits))&(t.side=='BUY')).any()
        row=dict(name=cfg['name'],split=split,stress=stress,start=str(start.date()),**q.measure(c),fees=float((t.commission+t.stamp_tax).sum()),orders=len(t))
        if cfg['name']=='control' and not stress:
            ref=regression[row['start']]
            for key in ('annualized','drawdown','sharpe'):assert abs(row[key]-ref[key])<1e-9,(key,row,ref)
            checks.append(row['start'])
        rows.append(row);save('results.json',rows)
        return row
    def gate(a,b):return a['p10']>b['p10'] and a['median']>=b['median']-.01 and a['drawdown']>=b['drawdown']-.02
    try:
        development={}
        for cfg in CONFIGS:
            z=summarize([run(cfg,d,'dev') for d in dev]);development[cfg['name']]=z
            print('DEV',cfg['name'],z,flush=True)
        eligible=[c for c in CONFIGS[1:] if gate(development[c['name']],development['control'])]
        winner=max(eligible,key=lambda c:development[c['name']]['p10']) if eligible else CONFIGS[0]
        save('frozen_candidate.json',winner)
        validation={}
        for cfg in {c['name']:c for c in (CONFIGS[0],winner)}.values():
            validation[cfg['name']]={}
            for split,ss,stress in [('audit',audit,False),('stress_dev',dev,True),('stress_audit',audit,True)]:
                z=summarize([run(cfg,d,split,stress) for d in ss]);validation[cfg['name']][split]=z
                print('VALIDATE',cfg['name'],split,z,flush=True)
        name=winner['name'];passed=name!='control'
        if passed:
            passed=gate(validation[name]['audit'],validation['control']['audit']) and all(validation[name][s]['p10']>validation['control'][s]['p10'] for s in ('stress_dev','stress_audit'))
        save('summary.json',dict(development=development,validation=validation,winner=winner,passed=passed,runs=len(rows),regression_checks=len(checks)))
        lines=['# 固定月历与周度风控研究','', '10万元，6只，每个窗口24个月；开发阶段包含月初及后移5/10交易日起点。','', '| 方向 | 年化中位数 | 年化P10 | 最差窗口回撤 | Sharpe |','|---|---:|---:|---:|---:|']
        for cfg in CONFIGS:
            z=development[cfg['name']];lines.append('|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(cfg['label'],100*z['median'],100*z['p10'],-100*z['drawdown'],z['sharpe']))
        lines+=['','冻结候选：'+winner['label']+'；验证通过：'+str(passed),'','| 方案 | 验证 | 年化中位数 | P10 | 最差回撤 |','|---|---|---:|---:|---:|']
        for name,tests in validation.items():
            for test,z in tests.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.2f%%|'%(name,test,z['median']*100,z['p10']*100,-z['drawdown']*100))
        lines+=['','总回测数：'+str(len(rows))+'；旧对照回归检查通过：'+str(len(checks)), '本轮没有独立样本外数据；未解决分钟成交、固定股票池和公司行动差异。未覆盖正式基准或生成实盘策略。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('DONE',len(rows),winner,passed,flush=True)
    finally:
        for key,value in original.items():setattr(g.bt,key,value)

if __name__=='__main__':main()
