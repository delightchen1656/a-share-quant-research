"""Complete yearly Q1 start-date scans, same frozen rules, no optimization."""
import json
import numpy as np
import pandas as pd
import quarter_anchor_scan as q

g=q.g
OUT=g.HERE/'quarter_anchor_all_years_2020_2026'


def save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def percentiles(rows):
    ordered=sorted(rows,key=lambda x:(x['total_return'],x['actual_start']))
    return [dict(percentile=p,**ordered[int(np.floor(p/100*(len(ordered)-1)+.5))]) for p in (0,25,50,75,100)]


def main():
    OUT.mkdir(exist_ok=True)
    q.OUT=OUT
    idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
    dates=pd.DatetimeIndex(idx.date.drop_duplicates())
    end=g.bt.END
    mappings={};schedules={};needed=set();known={}
    for year in range(2020,2027):
        requested=pd.date_range(f'{year}-01-01',f'{year}-03-31')
        mappings[year]={str(d.date()):dates[dates.searchsorted(d)] for d in requested}
        old=g.HERE/f'quarter_anchor_scan_{year}'/'unique_results.json'
        if old.exists():
            known[year]=json.loads(old.read_text(encoding='utf-8'))
            assert {r['actual_start'] for r in known[year]}=={str(d.date()) for d in mappings[year].values()}
        for anchor in sorted(set(mappings[year].values())):
            days=[];n=0
            while True:
                due=q.quarter_day(anchor,n)
                if due>end:break
                ix=dates.searchsorted(due)
                if ix==len(dates) or dates[ix]>end:break
                days.append(dates[ix]);n+=1
            assert days[0]==anchor and len(days)==len(set(days))
            schedules[anchor]=days
            if year not in known:needed.update(days)
    control_days=[d for d,s in g.bt.execution_signal_dates() if d.month in (1,4,7,10)]
    needed.update(control_days)
    save(OUT/'protocol.json',dict(years=list(range(2020,2027)),end=str(end.date()),capital=100000,
        strategy='Original 8-stock / buffer24 / exposure80% / min-adjustment3000 rules; 3-calendar-month actual-entry anchor.',
        signal='Strictly previous trading session; exact dates recalculated, not month-first substitutions.',
        percentile='Deduplicate actual trading-session entry dates, ascending total return, nearest actual sample, ties by date.',
        reused_years=list(known),limitations=['Daily opening-price execution proxy, no minute parity.',
            'Historical fixed universe, approximate corporate actions, all history observed.',
            'Different holding durations; 2026 windows shorter than one year, annualization unstable.',
            'Overlapping windows; maxima are retrospective, not optimized entry dates.']))
    print('FEATURE DATES',len(needed),'new starts',sum(d.year not in known for d in schedules),flush=True)
    f=q.build_features([(d,dates[dates.get_loc(d)-1]) for d in sorted(needed)])
    ranks=g.bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
    for d,x in list(ranks.items()):
        hist=idx[idx.date<=x.signal_date.iloc[0]]
        strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
        z=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
        ranks[d]=z.sort_values(['score','symbol'],ascending=[False,True])
    union=set().union(*(set(x.head(24).symbol) for x in ranks.values()))
    panel=g.bt.load_daily_panel(union)
    original={k:getattr(g.bt,k) for k in ('START','INITIAL_CASH','apply_corporate_action')}
    def action(cash,positions,day,previous):
        cash=original['apply_corporate_action'](cash,positions,day,previous)
        for s,qty in positions.items():
            if s not in day.index or s not in previous:continue
            pre=float(day.loc[s,'preclose'])
            if np.isfinite(pre) and pre>0 and 1+1e-8<previous[s]/pre<=1.02:cash+=qty*(previous[s]-pre)
        return cash
    g.bt.INITIAL_CASH=100000.;g.bt.apply_corporate_action=action
    results=dict(known)
    try:
        control,_=g.bt.simulate({d:ranks[d] for d in control_days},.05,8,24,.8,1.5,panel,min_adjustment=3000)
        ref=pd.read_csv(g.HERE/'approximate_parity_100k/include_small_corporate_actions_equity.csv')
        assert np.allclose(control.equity,ref.equity,atol=.01,rtol=0),'control drift'
        save(OUT/'control_check.json',dict(passed=True,**q.measure(control)))
        for year in range(2020,2027):
            if year in known:continue
            results[year]=[]
            starts=sorted(set(mappings[year].values()))
            for i,anchor in enumerate(starts,1):
                g.bt.START=anchor
                c,t=g.bt.simulate({d:ranks[d] for d in schedules[anchor]},.05,8,24,.8,1.5,panel,min_adjustment=3000)
                assert c.date.iloc[0]==anchor and c.date.iloc[-1]==end
                assert (c.cash>=-.01).all()
                assert (t[t.side=='BUY'].quantity%100==0).all()
                results[year].append(dict(actual_start=str(anchor.date()),**q.measure(c),
                    total_return=float(c.equity.iloc[-1]/100000-1),orders=len(t)))
                save(OUT/f'{year}_unique_results.json',results[year])
                if i%10==0 or i==len(starts):print('RUN',year,i,len(starts),flush=True)
    finally:
        for k,v in original.items():setattr(g.bt,k,v)
    tables={};counts={};rows=[]
    for year in range(2020,2027):
        assert len(results[year])==len(set(mappings[year].values()))
        save(OUT/f'{year}_unique_results.json',results[year])
        lookup={r['actual_start']:r for r in results[year]}
        requested=[dict(requested_start=k,**lookup[str(v.date())]) for k,v in mappings[year].items()]
        save(OUT/f'{year}_all_requested_results.json',requested)
        counts[year]=dict(calendar_starts=len(requested),unique_starts=len(results[year]))
        tables[year]=percentiles(results[year])
        rows.extend(dict(year=year,**r) for r in results[year])
    save(OUT/'all_unique_results.json',rows)
    save(OUT/'percentile_tables.json',tables)
    save(OUT/'counts.json',counts)
    lines=['# 2020—2026每年一季度起点扫描','',f'各10万元独立入场，8只持股、80%目标仓位、每3个日历月调仓，统一截至{end.date()}。',
        '按实际交易日起点去重后，累计收益升序取最近实际样本。非交易日顺延；不是原固定季度月初日程。',
        '2020、2021沿用同规则已验证结果；2022—2026本轮补算，原基准净值回归测试通过。','']
    for year,table in tables.items():
        lines += [f'## {year}年一季度', '',f"{counts[year]['calendar_starts']}个日历起点，{counts[year]['unique_starts']}条独立路径。",'',
            '| 收益位置 | 实际入场 | 累计收益 | 年化收益 | 最大回撤 | Sharpe | 期末资产 |',
            '|---|---|---:|---:|---:|---:|---:|']
        for x in table:
            lines.append('| %d%% | %s | %.2f%% | %.2f%% | %.2f%% | %.3f | %.2f |'%(x['percentile'],x['actual_start'],x['total_return']*100,x['annualized']*100,-x['drawdown']*100,x['sharpe'],x['final_equity']))
        lines.append('')
    lines += ['2026年持有期不足一年，年化由短期复利外推，不代表长期预期。不同年份持有期不同，不能只用累计收益横比。',
        '全部窗口重叠，不构成独立样本外证据。最高收益日期不能事后当作最优策略。',
        '本地日开盘成交代理、固定股票池、除权近似仍限制可迁移性；没有宣称SuperMind分钟撮合已复现。']
    (OUT/'全部年度分位表.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',counts,flush=True)
    print(json.dumps(tables,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
