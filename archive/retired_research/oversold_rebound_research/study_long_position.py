"""Long-range price location and nominal price: fixed signals, no post-2024 reads."""
import json
import numpy as np
import pandas as pd
from study import SOURCE, ROOT, digest
from study_continued_decline import metrics

OUT=ROOT/'results_v5_long_position'


def event_features(q,r,day):
    # Truncate before all statistics; nominal price uses unadjusted raw series.
    q=q.loc[q.date<=day].reset_index(drop=True);r=r.loc[r.date<=day].reset_index(drop=True)
    good=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)
    q=q.loc[good].reset_index(drop=True);r=r.loc[good].reset_index(drop=True)
    c=float(q.close.iloc[-1]);date=pd.Timestamp(day);dt=pd.to_datetime(q.date)
    out={'raw_signal_close':float(r.close.iloc[-1]),'available_years':(date-dt.iloc[0]).days/365.25}
    for years in [1,2,3]:
        start=date-pd.DateOffset(years=years);win=q.loc[dt>=start]
        enough=dt.iloc[0]<=start+pd.Timedelta(days=7) and len(win)>=180*years
        lo=float(win.low.min());hi=float(win.high.max())
        out[f'position{years}y']=(c-lo)/(hi-lo) if enough and hi>lo else np.nan
        out[f'drawdown{years}y']=c/hi-1 if enough and hi>0 else np.nan
        # Was the high just before this decline near the long-range high?
        out[f'recent_peak_to_high{years}y']=float(q.high.iloc[-60:].max()/hi) if enough else np.nan
    hi=float(q.high.max());lo=float(q.low.min())
    out['position_available']=(c-lo)/(hi-lo) if hi>lo else np.nan
    out['drawdown_available']=c/hi-1
    return out


def main():
    OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v4_decline_first/events.parquet')
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hs={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    rows=[];checked=False
    for code,g in d.groupby('code'):
        frames=[]
        for mode in ['qfq','raw']:
            p=SOURCE/mode/(code+'.parquet');assert digest(p)==hs[f'{mode}/{code}.parquet']
            z=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
            z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');assert z.date.max()<='2024-12-31'
            frames.append(z)
        q,r=frames;assert q.date.equals(r.date)
        for _,e in g.iterrows():
            vals=event_features(q,r,e.date)
            if not checked:
                a=event_features(q.loc[q.date<=e.date],r.loc[r.date<=e.date],e.date)
                mq,mr=q.copy(),r.copy()
                for col in ['open','high','low','close','volume']:
                    mq.loc[mq.date>e.date,col]*=100;mr.loc[mr.date>e.date,col]*=100
                b=event_features(mq,mr,e.date)
                np.testing.assert_allclose(list(vals.values()),list(a.values()),equal_nan=True)
                np.testing.assert_allclose(list(vals.values()),list(b.values()),equal_nan=True)
                checked=True
            rows.append(dict(code=code,date=e.date,**vals))
    d=d.merge(pd.DataFrame(rows),on=['code','date'],validate='one_to_one')
    d.to_parquet(OUT/'events.parquet',index=False)
    groups={
      '原始单价':pd.cut(d.raw_signal_close,[-np.inf,5,10,20,50,np.inf],right=False,labels=['<5元','5—10元','10—20元','20—50元','≥50元']),
    }
    for years in [1,2,3]:
        groups[f'{years}年区间位置']=pd.cut(d[f'position{years}y'],[-.00001,.2,.4,.6,.8,1.00001],right=True,labels=['底部0—20%','20—40%','40—60%','60—80%','顶部80—100%'])
        groups[f'距{years}年最高价回撤']=pd.cut(d[f'drawdown{years}y'],[-np.inf,-.6,-.4,-.2,0.00001],right=True,labels=['跌超60%','跌40—60%','跌20—40%','距高点不足20%'])
    bins=[];rules=[];yearly=[];summary=[]
    for pool,pm in [('样本池',pd.Series(True,index=d.index)),('龙头子样本',d.is_leader)]:
        pm=pm & d.touch_order.ne('same_day_unknown')
        summary.append(dict(pool=pool,**metrics(d.loc[pm]),history3y=int((pm&d.position3y.notna()).sum())))
        for feature,group in groups.items():
            for value in group.cat.categories:
                mask=pm & group.eq(value)
                bins.append(dict(pool=pool,feature=feature,bin=str(value),**metrics(d.loc[mask])))
        conds={
          '单价≥20元':(d.raw_signal_close>=20,d.raw_signal_close.notna()),
          '单价≥50元':(d.raw_signal_close>=50,d.raw_signal_close.notna()),
          '1年区间上半区':(d.position1y>=.5,d.position1y.notna()),
          '2年区间上半区':(d.position2y>=.5,d.position2y.notna()),
          '3年区间上半区':(d.position3y>=.5,d.position3y.notna()),
          '距3年高点不足30%':(d.drawdown3y>-.3,d.drawdown3y.notna()),
          '近60日曾接近3年高点（90%以上）':(d.recent_peak_to_high3y>=.9,d.recent_peak_to_high3y.notna()),
          '同3年历史样本中的单价≥20元':(d.raw_signal_close>=20,d.position3y.notna()),
        }
        for name,(flag,valid) in conds.items():
            for period,periodmask in [('全部',pd.Series(True,index=d.index)),('2018—2021',d.year<=2021),('2022—2024',d.year>=2022)]:
                eligible=pm & valid & periodmask
                rules.append(dict(pool=pool,rule=name,period=period,yes=metrics(d.loc[eligible&flag]),no=metrics(d.loc[eligible&~flag]),missing=int((pm & periodmask & ~valid).sum())))
            for year,g in d.loc[pm&valid].groupby('year'):
                mask=flag.loc[g.index]
                yearly.append(dict(pool=pool,rule=name,year=int(year),yes=metrics(g.loc[mask]),no=metrics(g.loc[~mask])))
    result=dict(summary=summary,bins=bins,rules=rules,yearly=yearly,boundary='2024-12-31',
      position_definition='(signal close - trailing low)/(trailing high - trailing low); adjusted OHLC, trailing calendar years including D0.',
      raw_price_definition='Unadjusted signal-day close, not current price or adjusted nominal price.',
      history_coverage='Available quotes start in 2018 at earliest; 3y requires full calendar span with 7-day endpoint tolerance and >=540 valid sessions; no padding. Available-history high is not lifetime high.',
      target='Original continued decline criterion AND -10% touched before +10%; intraday daily high/low, same-day ambiguity excluded.',
      verification='Manifest quote hashes and pre2025 date boundary verified; prefix/future perturbation checks passed.',
      caveat='Descriptive comparisons in retrospective box-selected 947-stock cohort/current leaders. Years overlap and outcomes clustered. No untouched validation or deployable filter claimed.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：长期位置、历史高点与原始单价',
      '沿用基础信号、连续疑似跌停排除、次日开盘基准和先+10%不算失败的先后顺序口径。',
      '区间位置=(信号收盘-过去N年最低)/(过去N年最高-过去N年最低)；使用前复权相对位置。单价使用当日未复权收盘。',
      '只读已审计白名单截至2024年底行情，最早2018年。不能称上市以来历史最高；1/2/3年历史不足分别排除，不补造。',
      '长期位置按日历年取窗，要求覆盖整段（起点容许7日）且每年至少180有效交易日。',
      '原始股价不等于估值/市值；长窗口组起始年份较晚，必须结合逐年及同覆盖样本比较。',
      '描述性研究，非全新盲测；未搜索最优切点，不改变现有筛选器。']
    for pool in ['样本池','龙头子样本']:
        lines+=['',pool,json.dumps(next(a for a in summary if a['pool']==pool),ensure_ascii=False),
          '分组 | 档位 | 数量 | 修正失败数/比例 | 触及10% | 跌超30%']
        for x in bins:
            if x['pool']==pool and x['n']:lines.append(f"{x['feature']} | {x['bin']} | {x['n']} | {x['continued']}/{x['continued_rate']:.2%} | {x['touch10']:.2%} | {x['fall30']:.2%}")
        lines+=['','条件 | 期间 | 满足数量/失败率 | 不满足数量/失败率 | 缺失数']
        for x in rules:
            if x['pool']==pool and x['yes']['n'] and x['no']['n']:
                a,b=x['yes'],x['no'];lines.append(f"{x['rule']} | {x['period']} | {a['n']}/{a['continued_rate']:.2%} | {b['n']}/{b['continued_rate']:.2%} | {x['missing']}")
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))
    for x in bins:
        if x['pool']=='龙头子样本':print(json.dumps(x,ensure_ascii=False))
    for x in rules:
        if x['pool']=='龙头子样本':print(json.dumps(x,ensure_ascii=False))


if __name__=='__main__':main()
