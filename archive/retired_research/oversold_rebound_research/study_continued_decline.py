"""Compare continued declines against ALL other fixed basic signals, pre-2025 only."""
import json
import numpy as np
import pandas as pd
from study import SOURCE, ROOT, digest

OUT=ROOT/'results_v3_continued_decline'


def features(q,r):
    good=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)
    q=q.loc[good].reset_index(drop=True);r=r.loc[good].reset_index(drop=True)
    c=q.close;v=r.volume;up=r.close>r.open
    ma20=c.rolling(20).mean();ma60=c.rolling(60).mean()
    f=pd.DataFrame({'date':q.date.astype(str)})
    f['ma20_slope5']=ma20/ma20.shift(5)-1
    f['ma60_slope10']=ma60/ma60.shift(10)-1
    f['pre_return60']=c.shift(1)/c.shift(61)-1
    f['pre_return120']=c.shift(1)/c.shift(121)-1
    f['ma20_ma60_gap']=ma20/ma60-1
    f['down_volume_share20']=v.where(~up,0).shift().rolling(20).sum()/v.shift().rolling(20).sum()
    f['up_volume_ratio20']=v.where(up).shift().rolling(20,min_periods=1).mean()/v.where(~up).shift().rolling(20,min_periods=1).mean()
    f['new_lows10']=(q.low<q.low.shift().rolling(10).min()).shift().rolling(10).sum()
    f['signal_return']=r.close/r.preclose-1
    f['signal_recovery']=(c-q.low.rolling(3).min())/(c.shift(5)-q.low.rolling(3).min()).replace(0,np.nan)
    f['signal_close_rank']=(r.close-r.low)/(r.high-r.low).replace(0,np.nan)
    f['volatility20']=c.pct_change(fill_method=None).shift().rolling(20).std()
    return f,q


def metrics(g):
    return dict(n=len(g),continued=int(g.continued.sum()),continued_rate=float(g.continued.mean()),
        touch10=float((g.max_up60>=.10).mean()),fall30=float((g.max_down60<=-.30).mean()),
        mean_close60=float(g.close60.mean())) if len(g) else dict(n=0)


def main():
    OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v2_no_limit_streaks/events.parquet')
    d=d.loc[~d.reject_consecutive2 & d.complete60].copy()
    manifest=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hashes={x['relative_path'].replace('\\','/'):x['sha256'] for x in manifest['files']}
    assert digest(SOURCE/'calendar.parquet')==manifest['calendar_sha256']
    dates=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    pos={day:i for i,day in enumerate(dates)}
    extra=[];labels=[];verified=False
    for code,events in d.groupby('code'):
        frames=[]
        for mode in ['qfq','raw']:
            p=SOURCE/mode/(code+'.parquet');assert digest(p)==hashes[f'{mode}/{code}.parquet']
            z=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
            z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');assert z.date.max()<='2024-12-31'
            frames.append(z)
        q,r=frames;assert q.date.equals(r.date)
        f,validq=features(q,r);f['code']=code;extra.append(f)
        if not verified:
            for cut in ['2020-06-30','2022-04-29','2024-06-28']:
                mask=q.date<=cut
                a,_=features(q.loc[mask],r.loc[mask]);b,_=features(q,r)
                pd.testing.assert_frame_equal(a,b.loc[b.date<=cut].reset_index(drop=True))
                mq,mr=q.copy(),r.copy()
                for col in ['open','high','low','close','volume']:
                    mq.loc[~mask,col]*=100;mr.loc[~mask,col]*=100
                b,_=features(mq,mr)
                pd.testing.assert_frame_equal(a,b.loc[b.date<=cut].reset_index(drop=True))
            verified=True
        ix=validq.set_index('date')
        for _,e in events.iterrows():
            k=pos[e.date];path=ix.loc[ix.index.isin(dates[k+1:k+61])]
            entry=float(ix.loc[dates[k+1],'open'])
            y=np.log(path.close.to_numpy()/entry)
            x=np.array([pos[a]-k for a in path.index]);slope=float(np.polyfit(x,y,1)[0])
            below=float((path.close<entry).mean())
            labels.append(dict(code=code,date=e.date,below_entry_share=below,path_slope=slope,
                entry_gap=entry/float(ix.loc[e.date,'close'])-1,
                continued=bool(e.close20<0 and e.close60<=-.10 and below>=.70 and slope<0),
                end_negative=bool(e.close60<0),
                no_rebound=bool(e.max_up60<.05 and e.close60<=-.10)))
    d=d.merge(pd.concat(extra),on=['code','date'],validate='one_to_one').merge(pd.DataFrame(labels),on=['code','date'],validate='one_to_one')
    d.to_parquet(OUT/'events.parquet',index=False)
    # Prespecified interpretable conditions, not searched for an optimal threshold.
    rules={
      'MA60近10日下跌至少3%':d.ma60_slope10<=-.03,
      'MA20近5日下跌至少5%':d.ma20_slope5<=-.05,
      '此前60日跌幅至少30%':d.pre_return60<=-.30,
      '此前120日跌幅至少40%':d.pre_return120<=-.40,
      'MA20低于MA60至少10%':d.ma20_ma60_gap<=-.10,
      '前20日阴线量占比至少65%':d.down_volume_share20>=.65,
      '近10日创10日新低至少4次':d.new_lows10>=4,
      '信号量不足前20日均量':d.volume_ratio<1,
      '信号量达到前20日均量1.5倍':d.volume_ratio>=1.5,
      '信号日涨幅不足2%':d.signal_return<.02,
      '信号收盘低于MA20至少10%':d.below_ma20<=-.10,
      '前3日缩量至0.8倍以下':d.last3_volume_ratio<=.8,
      '次日开盘高开至少3%（开盘时信息）':d.entry_gap>=.03,
    }
    rule_features=dict(zip(rules,['ma60_slope10','ma20_slope5','pre_return60','pre_return120',
        'ma20_ma60_gap','down_volume_share20','new_lows10','volume_ratio','volume_ratio',
        'signal_return','below_ma20','last3_volume_ratio','entry_gap']))
    columns=['ma60_slope10','ma20_slope5','pre_return60','pre_return120','ma20_ma60_gap',
        'down_volume_share20','up_volume_ratio20','new_lows10','volume_ratio','last3_volume_ratio',
        'signal_return','signal_recovery','body','upper','lower','below_ma20','below_ma60','volatility20','entry_gap']
    comparisons=[];medians=[];summaries=[];yearly=[]
    for pool,pm in [('样本池',pd.Series(True,index=d.index)),('龙头子样本',d.is_leader)]:
        g=d.loc[pm]
        summaries.append(dict(pool=pool,**metrics(g),end_negative=int(g.end_negative.sum()),no_rebound=int(g.no_rebound.sum())))
        for col in columns:medians.append(dict(pool=pool,feature=col,
            continued_median=float(g.loc[g.continued,col].median()),other_median=float(g.loc[~g.continued,col].median())))
        for name,mask in rules.items():
            known=d[rule_features[name]].notna()
            for period,p in [('全部',pd.Series(True,index=d.index)),('2018—2021',d.year<=2021),('2022—2024',d.year>=2022)]:
                a=d.loc[pm&p&known&mask];b=d.loc[pm&p&known&~mask]
                comparisons.append(dict(pool=pool,rule=name,period=period,yes=metrics(a),no=metrics(b),
                    missing_excluded=int((pm&p&~known).sum())))
        for year,h in g.groupby('year'):yearly.append(dict(pool=pool,year=int(year),**metrics(h)))
    result=dict(definition='D20 close < D1 open; D60 close <= D1 open*0.90; >=70% observed closes below entry; log close slope negative.',
        boundary='2024-12-31',summary=summaries,comparisons=comparisons,medians=medians,yearly=yearly,
        verification='Input hashes verified; trailing features prefix and 100x future perturbation invariant at 3 cutoffs.',
        limitations=['Prior 947-stock box-selected cohort, retrospective leader membership; not mainboard census.',
                    'Descriptive association, repeated stocks and overlapping market episodes; periods are not fresh blind tests.',
                    'Entry gap known only at D1 open; other predictors known at D0 close.',
                    'Other group includes weak/rebounding/mixed outcomes; not only handpicked winners.',
                    'Price path not executable economic/account returns; missing sessions omitted in below-entry share.'])
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：基础信号后仍然下跌的共性研究',
        '范围：原有947股票白名单；保留基础信号并剔除连续疑似跌停，不叠加深乖离/放量筛选。只读2024年底以前数据。',
        '基准：信号次一正式交易日开盘。',
        '主要定义：D20收盘低于买价、D60收盘至少低10%、60日中至少70%有效收盘低于买价、日收盘对数趋势斜率为负，同时满足。',
        '辅助口径另给D60收盘亏损、最高未触及5%且D60至少跌10%的数量，不混同为持续下跌。',
        '条件来自信号日前数据；次日高开单独标注。没有按未来跌停或未来收益筛选输入信号。',
        '对照是全部其他基础信号，包括弱反弹和混合走势，不仅是涨得好的样本。',
        '分组比较逐因子排除缺失，不把不足120日历史等缺失值当成条件不满足；缺失数详见summary.json。',
        '以下属于探索性描述，时间分段也不是全新盲测；股、市场日期聚集和60日重叠会影响独立性。']
    for pool in ['样本池','龙头子样本']:
        s=next(a for a in summaries if a['pool']==pool)
        lines+=['',pool,json.dumps(s,ensure_ascii=False),'条件 | 满足:数量/持续跌比例 | 不满足:数量/持续跌比例 | 满足:触及10%/跌超30%']
        for x in comparisons:
            if x['pool']==pool and x['period']=='全部':
                a,b=x['yes'],x['no']
                lines.append(f"{x['rule']} | {a['n']}/{a['continued_rate']:.2%} | {b['n']}/{b['continued_rate']:.2%} | {a['touch10']:.2%}/{a['fall30']:.2%}")
        lines+=['','分时间段：条件 | 期间 | 满足:数量/持续跌比例 | 不满足:数量/持续跌比例']
        for x in comparisons:
            if x['pool']==pool and x['period']!='全部':
                a,b=x['yes'],x['no']
                if a['n'] and b['n']:lines.append(f"{x['rule']} | {x['period']} | {a['n']}/{a['continued_rate']:.2%} | {b['n']}/{b['continued_rate']:.2%}")
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    print('\n'.join(lines[:8]));print(json.dumps(summaries,ensure_ascii=False))
    for x in comparisons:
        if x['pool']=='龙头子样本':print(json.dumps(x,ensure_ascii=False))


if __name__=='__main__':main()
