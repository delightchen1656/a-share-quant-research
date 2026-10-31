"""Daily intraday-high and closing paths around entry, fixed basic signals."""
import json
import numpy as np
import pandas as pd
from study import SOURCE,ROOT,digest

OUT=ROOT/'results_v6_first5'


def main():
    OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v4_decline_first/events.parquet')
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hs={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    assert digest(SOURCE/'calendar.parquet')==m['calendar_sha256']
    dates=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    pos={day:i for i,day in enumerate(dates)}
    rows=[];peaks=[]
    for code,g in d.groupby('code'):
        frames=[]
        for mode in ['qfq','raw']:
            p=SOURCE/mode/(code+'.parquet');assert digest(p)==hs[f'{mode}/{code}.parquet']
            z=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
            z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');assert z.date.max()<='2024-12-31'
            frames.append(z)
        q,r=frames;assert q.date.equals(r.date)
        good=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)
        q=q.loc[good].set_index('date');r=r.loc[good].set_index('date')
        for _,e in g.iterrows():
            k=pos[e.date];entry_day=dates[k+1];entry=float(q.loc[entry_day,'open']);raw_entry=float(r.loc[entry_day,'open'])
            path=q.loc[q.index.isin(dates[k+1:k+61])]
            peak_day=path.high.idxmax();peak_offset=pos[peak_day]-(k+1)
            peaks.append(dict(code=code,date=e.date,peak_date60=peak_day,peak_buy_offset60=peak_offset,
                peak_at_buy_first5=peak_offset<=4,peak_at_after_buy1to5=1<=peak_offset<=5))
            for b in range(6):
                day=dates[k+1+b];observed=day in q.index
                previous=dates[k+1:k+b+2];cum=q.loc[q.index.isin(previous)]
                complete=len(cum)==len(previous)
                row=dict(code=code,name=e['name'],signal_date=e.date,buy_date=entry_day,date=day,
                    is_leader=bool(e.is_leader),buy_offset=b,entry_qfq=entry,entry_raw=raw_entry,
                    observed=observed,cumulative_complete=complete,
                    cumulative_high_return=float(cum.high.max()/entry-1) if complete else np.nan,
                    peak_at_buy_first5=peak_offset<=4,peak_at_after_buy1to5=1<=peak_offset<=5)
                for field in ['open','high','low','close']:
                    row[f'{field}_qfq']=float(q.loc[day,field]) if observed else np.nan
                    row[f'{field}_raw']=float(r.loc[day,field]) if observed else np.nan
                    row[f'{field}_return']=float(q.loc[day,field]/entry-1) if observed else np.nan
                rows.append(row)
    path=pd.DataFrame(rows);pk=pd.DataFrame(peaks)
    assert len(path)==len(d)*6
    assert path.groupby(['code','signal_date']).buy_offset.nunique().eq(6).all()
    observed=path.loc[path.observed]
    assert (observed.high_qfq >= observed.close_qfq-1e-8).all()
    assert np.allclose(path.loc[path.buy_offset==0,'open_return'],0)
    for _,g in path.loc[path.cumulative_complete].groupby(['code','signal_date']):
        assert (np.diff(g.sort_values('buy_offset').cumulative_high_return)>=-1e-8).all()
    path.to_parquet(OUT/'daily_paths.parquet',index=False);pk.to_parquet(OUT/'peak_timing.parquet',index=False)
    summary=[]
    for pool,pm in [('样本池',pd.Series(True,index=path.index)),('龙头子样本',path.is_leader)]:
        for selection,sm in [('基础信号',pd.Series(True,index=path.index)),
                             ('60日最高点在买入当天至第4日（事后筛选）',path.peak_at_buy_first5),
                             ('60日最高点在买入后第1至5日（事后筛选）',path.peak_at_after_buy1to5)]:
            for b,g in path.loc[pm&sm].groupby('buy_offset'):
                valid=g.loc[g.observed];cum=g.loc[g.cumulative_complete]
                summary.append(dict(pool=pool,selection=selection,buy_offset=int(b),n=len(g),observed=len(valid),
                    mean_high=float(valid.high_return.mean()),median_high=float(valid.high_return.median()),
                    mean_close=float(valid.close_return.mean()),median_close=float(valid.close_return.median()),
                    close_p10=float(valid.close_return.quantile(.10)),close_p90=float(valid.close_return.quantile(.90)),
                    positive_close=float((valid.close_return>0).mean()),
                    mean_cumulative_high=float(cum.cumulative_high_return.mean()),cumulative_n=len(cum),
                    cumulative_touch10=float((cum.cumulative_high_return>=.1-1e-9).mean())))
    result=dict(summary=summary,boundary='2024-12-31',
        entry='Signal next official session open; B0=buy day, B1=one official session AFTER buy, B5=five after buy.',
        daily_high='Actual day high / entry -1, may be negative if whole later bar is below entry; not clipped to zero.',
        cumulative_high='Highest high from B0 up to Bn / entry -1; no implicit sell at that high.',
        missing='Missing/halts never forward-filled. Daily means use observed rows, cumulative means require every session observed.',
        scope='Same v4 fixed basic complete60 signals after consecutive inferred-limit exclusion: 4641 total, 881 leaders.',
        caveat='Observed adjusted price path not account P&L; future peak-timing subsets are ex-post descriptions and must not be used as entry screens. Retrospective 947-stock cohort, no fresh blind validation.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：买入后前几日最高价与收盘价',
        '沿用基础超跌信号并排除连续疑似跌停：样本池4641条、龙头881条；不再叠加任何价格/长期位置筛选。',
        '买入按信号次一正式交易日开盘。B0=买入当天，B1—B5=买入之后第1—5个正式交易日（为避免差一日，同时列B0）。',
        '全部涨跌幅相对同一个买入开盘价。每只价格不同，汇总用涨跌幅；逐事件原始/前复权开高低收与买价保存在daily_paths.parquet。',
        '当日最高是当天high相对买价，可为负；累计最高为B0到该日high最大值，不等于实际可实现收益。',
        '停牌/缺价不填造；当日用有报价样本，累计要求该段每个正式交易日有报价。',
        '截到2024年底；当前龙头归属回看、原947股票样本范围，不是全量主板与盲测。',
        '额外给60日最高点恰在前5日的事后分组，不能在买入时按未来最高点筛选。']
    for pool in ['样本池','龙头子样本']:
        lines+=['',pool]
        for selection in dict.fromkeys(x['selection'] for x in summary):
            lines+=['',selection,'交易日 | 有报价/总数 | 当日最高平均涨幅 | 收盘平均涨幅 | 收盘中位数 | 累计最高平均涨幅 | 累计触及10%']
            for x in summary:
                if x['pool']==pool and x['selection']==selection:
                    lines.append(f"B{x['buy_offset']} | {x['observed']}/{x['n']} | {x['mean_high']:.2%} | {x['mean_close']:.2%} | {x['median_close']:.2%} | {x['mean_cumulative_high']:.2%} | {x['cumulative_touch10']:.2%}")
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    for x in summary:
        if x['pool']=='龙头子样本' and x['selection']=='基础信号':print(json.dumps(x,ensure_ascii=False))


if __name__=='__main__':main()
