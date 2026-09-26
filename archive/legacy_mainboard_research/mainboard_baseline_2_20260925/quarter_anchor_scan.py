"""Exact calendar-day quarter anchors, Jan-Mar 2020, no parameter optimization."""
import calendar
import json
import numpy as np
import pandas as pd
import group_research as g
from start_date_robustness import measure

OUT=g.HERE/'quarter_anchor_scan_2020'


def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def quarter_day(anchor,n):
    m=anchor.year*12+anchor.month-1+3*n
    y,m0=divmod(m,12)
    return anchor.replace(year=y,month=m0+1,day=min(anchor.day,calendar.monthrange(y,m0+1)[1]))


def build_features(pairs):
    cache=OUT/'exact_date_factors.parquet'
    if cache.exists():return pd.read_parquet(cache)
    execution=pd.DatetimeIndex([d for d,s in pairs])
    signals=pd.DatetimeIndex([s for d,s in pairs])
    pieces=[];fallbacks=0
    for number,symbol in enumerate(g.bt.load_universe(),1):
        rp,qp=g.bt.raw_path(symbol),g.bt.qfq_path(symbol)
        if not rp.exists() or not qp.exists():continue
        raw=pd.read_parquet(rp);adj=pd.read_parquet(qp)
        for z in (raw,adj):
            z['date']=pd.to_datetime(z.date)
            z.sort_values('date',inplace=True)
            z.drop_duplicates('date',inplace=True)
        raw=raw.set_index('date');adj=adj.set_index('date')
        r=raw[raw.tradestatus.astype(str)=='1']
        q=adj[adj.tradestatus.astype(str)=='1']
        if len(q)<250:continue
        c=q.close.astype(float);ret=c.pct_change(fill_method=None)
        x=pd.DataFrame(index=q.index)
        x['amount20']=q.amount.astype(float).rolling(20,min_periods=1).mean()
        x['vol20']=ret.rolling(20).std()
        x['near_high']=c/c.rolling(120).max()
        x['below_high']=1-x.near_high
        x['below_ma60']=(1-c/c.rolling(60).mean()).clip(lower=0)
        x['downside']=ret.clip(upper=0).pow(2).rolling(20).mean().pow(.5).clip(lower=.002)
        x['eligible']=(np.arange(len(q))>=249)&c.rolling(121).count().eq(121)&q.isST.astype(str).ne('1')&x.vol20.between(.004,.08)&x.amount20.ge(50000000.)
        if q.index.equals(r.index):
            factor=c/r.close.astype(float)
            changes=factor.pct_change(fill_method=None).abs()
            events=changes.where((changes>.0005)&(changes<.12),0.)
            y0=events.rolling(250,min_periods=1).sum()
            y1=y0.shift(250).fillna(0)
            y2=y0.shift(500).fillna(0)
            x['dividend']=.7*(y0.gt(0).astype(int)+y1.gt(0).astype(int)+y2.gt(0).astype(int))/3+.3*(y0/.05).clip(upper=1)
        else:
            # Exact original reference for mismatched raw/qfq trading histories.
            x['dividend']=np.nan
            fallbacks+=1
        positions=q.index.searchsorted(signals,side='right')-1
        valid=positions>=0
        z=x.iloc[np.maximum(positions,0)].reset_index(drop=True)
        z['execute_date']=execution;z['signal_date']=signals;z['symbol']=symbol
        z=z[valid & z.eligible].copy()
        if not q.index.equals(r.index):
            z['dividend']=[g.bt.dividend_quality(q.loc[:s].tail(751),r.loc[:s].tail(751)) for s in z.signal_date]
        turn=raw.turn.astype(float)
        extra=pd.DataFrame(dict(turn20=turn.rolling(20).mean(),
            float_cap_proxy=raw.volume.astype(float)/turn.where(turn>0)*100*raw.close.astype(float)))
        e=extra.reindex(pd.DatetimeIndex(z.signal_date))
        z['turn20']=e.turn20.to_numpy();z['float_cap_proxy']=e.float_cap_proxy.to_numpy()
        pieces.append(z.drop(columns=['eligible','vol20']))
        if number%250==0:print('FACTORS',number,flush=True)
    f=pd.concat(pieces,ignore_index=True)
    f['float_cap_proxy_group']=np.floor(f.groupby('execute_date').float_cap_proxy.rank(pct=True)*3).clip(upper=2).fillna(-1).astype(int)
    # Validate all overlapping dates against previously frozen monthly factors.
    old=g.features();days=set(f.execute_date)&set(old.execute_date)
    a=f[f.execute_date.isin(days)];b=old[old.execute_date.isin(days)]
    merged=a.merge(b,on=['execute_date','symbol'],suffixes=('_new','_old'),validate='one_to_one')
    assert len(merged)==len(a)==len(b),'eligibility drift vs monthly reference'
    cols=['amount20','near_high','below_high','below_ma60','downside','dividend','turn20','float_cap_proxy']
    errors={}
    for col in cols:
        aa=merged[col+'_new'].to_numpy();bb=merged[col+'_old'].to_numpy()
        errors[col]=float(np.nanmax(np.abs(aa-bb)))
        assert np.allclose(aa,bb,rtol=1e-8,atol=1e-9,equal_nan=True),col
    assert (merged.float_cap_proxy_group_new==merged.float_cap_proxy_group_old).all()
    save('factor_checks.json',dict(overlapping_dates=len(days),checked_rows=len(merged),errors=errors,fallback_symbols=fallbacks))
    f.to_parquet(cache,index=False)
    return f


def main():
    OUT.mkdir(exist_ok=True)
    save('protocol.json',dict(requested_starts=['2020-01-01','2020-03-31'],capital=100000,
        strategy='8 stocks, buffer24, exposure80%, minimum adjustment3000, original signals',
        schedule='First exchange session on/after requested date; every 3 calendar months from actual first entry, closed days postponed without anchor drift.',
        endpoint=str(g.bt.END.date()), quantiles='Sort total return ascending; nearest actual observation at 0/25/50/75/100%, tie-break requested date. Report 91 requested dates and unique trading dates separately.',
        model='Daily-open proxy, small corporate-action correction; no minute replication or point-in-time universe guarantee. No selecting new best date as optimized policy.'))
    idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
    dates=pd.DatetimeIndex(idx.date.drop_duplicates())
    end=g.bt.END;requested=pd.date_range('2020-01-01','2020-03-31',freq='D')
    mappings={str(d.date()):dates[dates.searchsorted(d)] for d in requested}
    schedules={};needed=set()
    for anchor in sorted(set(mappings.values())):
        schedule=[];n=0
        while True:
            due=quarter_day(anchor,n)
            if due>end:break
            ix=dates.searchsorted(due)
            if ix==len(dates) or dates[ix]>end:break
            schedule.append(dates[ix]);n+=1
        assert schedule[0]==anchor
        schedules[anchor]=schedule;needed.update(schedule)
    # Include original fixed quarters for the control regression, not in percentiles.
    control_days=[d for d,s in g.bt.execution_signal_dates() if d.month in (1,4,7,10)]
    needed.update(control_days)
    pairs=[(d,dates[dates.get_loc(d)-1]) for d in sorted(needed)]
    save('schedules.json',{str(k.date()):[str(d.date()) for d in v] for k,v in schedules.items()})
    print('DATES',len(requested),'unique entries',len(schedules),'factor days',len(pairs),flush=True)
    f=build_features(pairs)
    ranks=g.bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
    for d,x in list(ranks.items()):
        hist=idx[idx.date<=x.signal_date.iloc[0]]
        strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
        q=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
        ranks[d]=q.sort_values(['score','symbol'],ascending=[False,True])
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
    results={}
    try:
        control,_=g.bt.simulate({d:ranks[d] for d in control_days},.05,8,24,.8,1.5,panel,min_adjustment=3000)
        reference=pd.read_csv(g.HERE/'approximate_parity_100k/include_small_corporate_actions_equity.csv')
        assert np.allclose(control.equity,reference.equity,atol=.01,rtol=0),'control equity changed'
        save('fixed_quarter_control.json',measure(control))
        for i,(anchor,days) in enumerate(schedules.items(),1):
            g.bt.START=anchor
            c,t=g.bt.simulate({d:ranks[d] for d in days},.05,8,24,.8,1.5,panel,min_adjustment=3000)
            assert (c.cash>=-.01).all()
            results[anchor]=dict(actual_start=str(anchor.date()),**measure(c),total_return=float(c.equity.iloc[-1]/100000-1),orders=len(t))
            save('unique_results.json',list(results.values()))
            print('RUN',i,len(schedules),anchor.date(),flush=True)
    finally:
        for k,v in original.items():setattr(g.bt,k,v)
    rows=[dict(requested_start=k,**results[v]) for k,v in mappings.items()]
    save('all_requested_results.json',rows)
    def quantiles(items,key):
        ordered=sorted(items,key=lambda x:(x['total_return'],x[key]))
        return [dict(percentile=p,**ordered[int(np.floor(p/100*(len(ordered)-1)+.5))]) for p in (0,25,50,75,100)]
    table=quantiles(rows,'requested_start');unique_table=quantiles(list(results.values()),'actual_start')
    save('percentiles.json',dict(requested=table,unique=unique_table))
    lines=['# 季度起始日期扫描','',f'2020-01-01至2020-03-31共91个日历起点，顺延后{len(results)}个独立交易日起点；各10万元，统一截至{end.date()}。',
        '以首次实际入场日为锚，每隔3个日历月对应日调仓，休市顺延；不是原版固定季度月初日程。',
        '按累计收益从低到高取最近实际样本，不对指标做插值。持有期略有不同，附年化。', '',
        '| 收益位置 | 请求起点 | 实际入场 | 累计收益 | 年化 | 最大回撤 | Sharpe | 期末资产 |',
        '|---|---|---|---:|---:|---:|---:|---:|']
    for x in table:
        lines.append('| %d%% | %s | %s | %.2f%% | %.2f%% | %.2f%% | %.3f | %.2f |'%(x['percentile'],x['requested_start'],x['actual_start'],x['total_return']*100,x['annualized']*100,-x['drawdown']*100,x['sharpe'],x['final_equity']))
    lines+=['','假期起点会重复映射到同一策略路径，主表按91个请求日期计权；去重后的结果见percentiles.json。',
            '新日期因子逐日计算，重叠月初因子与旧缓存校验；原固定季度净值回归测试到0.01元内。',
            '本地日线成交代理、固定股票池、除权近似等限制仍存在。不能从这张表事后挑最高收益日期作为已验证策略。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(table,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
