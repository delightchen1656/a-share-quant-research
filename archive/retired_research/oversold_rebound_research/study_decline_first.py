"""Refine continued-decline labels by the order of intraday +/-10% touches.

Daily highs/lows identify touch days, not within-day order. Ambiguity is explicit.
"""
import json
import numpy as np
import pandas as pd
from study import SOURCE, ROOT, digest
from study_continued_decline import metrics

OUT=ROOT/'results_v4_decline_first'


def first_order(path, entry):
    up=path.high.to_numpy() >= entry*1.10-1e-9
    down=path.low.to_numpy() <= entry*.90+1e-9
    ui=int(np.flatnonzero(up)[0]) if up.any() else None
    di=int(np.flatnonzero(down)[0]) if down.any() else None
    if ui is None:order='down_first' if di is not None else 'neither'
    elif di is None or ui<di:order='up_first'
    elif di<ui:order='down_first'
    else:
        opening=float(path.open.iloc[ui])
        if opening >= entry*1.10-1e-9:order='up_first'
        elif opening <= entry*.90+1e-9:order='down_first'
        else:order='same_day_unknown'
    return dict(touch_order=order,up10_date=str(path.index[ui]) if ui is not None else None,
                down10_date=str(path.index[di]) if di is not None else None)


def verify():
    def path(rows):return pd.DataFrame(rows,columns=['open','high','low'],index=[f'D{i+1}' for i in range(len(rows))])
    assert first_order(path([[100,111,99],[100,102,89]]),100)['touch_order']=='up_first'
    assert first_order(path([[100,101,89],[100,111,99]]),100)['touch_order']=='down_first'
    assert first_order(path([[100,111,89]]),100)['touch_order']=='same_day_unknown'
    assert first_order(path([[111,112,89]]),100)['touch_order']=='up_first'
    assert first_order(path([[89,111,88]]),100)['touch_order']=='down_first'
    assert first_order(path([[100,110,99]]),100)['touch_order']=='up_first'
    assert first_order(path([[100,105,95]]),100)['touch_order']=='neither'


def main():
    verify();OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v3_continued_decline/events.parquet')
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hs={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    assert digest(SOURCE/'calendar.parquet')==m['calendar_sha256']
    days=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    positions={x:i for i,x in enumerate(days)}
    rows=[]
    for code,g in d.groupby('code'):
        frames=[]
        for mode in ['qfq','raw']:
            p=SOURCE/mode/(code+'.parquet');assert digest(p)==hs[f'{mode}/{code}.parquet']
            z=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
            z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');assert z.date.max()<='2024-12-31'
            frames.append(z)
        q,r=frames;assert q.date.equals(r.date)
        q=q.loc[(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)].set_index('date')
        for _,e in g.iterrows():
            k=positions[e.date];entry=float(q.loc[days[k+1],'open'])
            path=q.loc[q.index.isin(days[k+1:k+61])]
            rows.append(dict(code=code,date=e.date,**first_order(path,entry)))
    d=d.rename(columns={'continued':'continued_old'}).merge(pd.DataFrame(rows),on=['code','date'],validate='one_to_one')
    d['continued']=d.continued_old & d.touch_order.eq('down_first')
    d['ambiguous_decline']=d.continued_old & d.touch_order.eq('same_day_unknown')
    d['excused_up_first']=d.continued_old & d.touch_order.eq('up_first')
    d.to_parquet(OUT/'events.parquet',index=False)
    # Unknown first-order signals excluded from comparisons, not classified as successes.
    known=d.touch_order.ne('same_day_unknown')
    rules={
      '距MA20不足10%':(d.below_ma20>-.10,d.below_ma20.notna()),
      '此前120日跌幅不足40%':(d.pre_return120>-.40,d.pre_return120.notna()),
      '前3日未缩量至0.8倍以下':(d.last3_volume_ratio>.8,d.last3_volume_ratio.notna()),
      '信号量不足前20日均量':(d.volume_ratio<1,d.volume_ratio.notna()),
      '信号量至少前20日均量1.5倍':(d.volume_ratio>=1.5,d.volume_ratio.notna()),
      'MA60近10日下跌至少3%':(d.ma60_slope10<=-.03,d.ma60_slope10.notna()),
      '阴线量占比至少65%':(d.down_volume_share20>=.65,d.down_volume_share20.notna()),
      '次日高开至少3%（开盘时信息）':(d.entry_gap>=.03,d.entry_gap.notna())}
    summary=[];comparisons=[]
    for pool,pm in [('样本池',pd.Series(True,index=d.index)),('龙头子样本',d.is_leader)]:
        g=d.loc[pm]
        summary.append(dict(pool=pool,n=len(g),old_decline=int(g.continued_old.sum()),
            excused_up_first=int(g.excused_up_first.sum()),ambiguous_decline=int(g.ambiguous_decline.sum()),
            all_same_day_unknown=int(g.touch_order.eq('same_day_unknown').sum()),new_decline=int(g.continued.sum()),
            new_decline_rate_of_all=float(g.continued.mean()),
            new_decline_rate_known=float(g.loc[g.touch_order.ne('same_day_unknown'),'continued'].mean()),
            **{'order_'+str(a):int(b) for a,b in g.touch_order.value_counts().items()}))
        for rule,(mask,valid) in rules.items():
            for period,periodmask in [('全部',pd.Series(True,index=d.index)),('2018—2021',d.year<=2021),('2022—2024',d.year>=2022)]:
                eligible=pm & valid & known & periodmask
                comparisons.append(dict(pool=pool,rule=rule,period=period,
                    yes=metrics(d.loc[eligible&mask]),no=metrics(d.loc[eligible&~mask]),
                    excluded_missing_or_unknown=int((pm & periodmask & (~valid|~known)).sum())))
    result=dict(summary=summary,comparisons=comparisons,
        definition='Existing continued-decline criterion plus first -10% touch before first +10%; use daily highs/lows and open to resolve opening gaps; otherwise same-day order unknown.',
        same_day_policy='Unknown excluded from yes/no comparisons; never treated as a success.',
        known_at_signal='Original trailing features unchanged; touch order is outcome labeling only.',
        boundary='2024-12-31',verification='7 synthetic order tests passed; input quote and calendar hashes verified.',
        caveat='This interprets down as the previous -10% threshold, not the first tick below entry. Price path, not account return. Existing 947-stock cohort, retrospective leaders, descriptive analysis, not fresh blind testing.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：先触及+10%的不算持续下跌失败',
      '买入基准保持信号次一正式交易日开盘，观察D1—D60，盘中高低价均参与。',
      '下跌沿用前轮10%阈值：保留原持续走弱定义，同时要求首次触及-10%早于首次触及+10%。',
      '先触及+10%之后再跌的，从旧持续走弱失败数中移出。先跌-10%后才涨10%的，仍保留。',
      '同日高低价同时触及两边：开盘已越过一边时按开盘判断；否则日线无法判断顺序，列为未知，不当成成功。',
      '这只是结局标签修正；未把后续触及顺序作为买入时可用的筛选因子。原基础信号和连续跌停排除规则不变。',
      '原持续走弱定义：D20收盘低于买价；D60至少跌10%；至少70%有效收盘低于买价；对数收盘趋势斜率为负。',
      '数据截至2024年底，原947股票白名单，当前龙头回看；非全量沪深、非全新盲测，前复权价格路径非账户收益。']
    for pool in ['样本池','龙头子样本']:
        lines+=['',pool,json.dumps(next(x for x in summary if x['pool']==pool),ensure_ascii=False),
          '条件 | 满足:数量/修正失败率 | 不满足:数量/修正失败率']
        for x in comparisons:
            if x['pool']==pool:
                a,b=x['yes'],x['no']
                if a['n'] and b['n']:lines.append(f"{x['period']} {x['rule']} | {a['n']}/{a['continued_rate']:.2%} | {b['n']}/{b['continued_rate']:.2%}")
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    for x in comparisons:
        if x['pool']=='龙头子样本' and x['period']=='全部':print(json.dumps(x,ensure_ascii=False))


if __name__=='__main__':main()
