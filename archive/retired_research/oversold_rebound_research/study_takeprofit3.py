"""First +3% daily-high touch after assumed entry; distinguish T+1 eligible touch."""
import json
import numpy as np
import pandas as pd
from study import SOURCE,ROOT,digest

OUT=ROOT/'results_v7_takeprofit3'


def first_hit(path,entry,min_offset):
    hit=path.loc[(path.buy_offset>=min_offset)&(path.high>=entry*1.03-1e-9)]
    if len(hit):
        h=hit.iloc[0]
        return int(h.buy_offset),str(h.name)
    return None,None


def verify():
    p=pd.DataFrame(dict(buy_offset=[0,1,2],high=[104,102,103]),index=['a','b','c'])
    assert first_hit(p,100,0)==(0,'a')
    assert first_hit(p,100,1)==(2,'c')
    assert first_hit(p.iloc[:2],100,1)==(None,None)
    p.loc['b','high']=110
    assert first_hit(p,100,1)==(1,'b')


def summarize(g,field):
    counts=g[field].value_counts().to_dict();n=len(g);cum=0;rows=[]
    for day in range(60):
        count=int(counts.get(day,0));cum+=count
        rows.append(dict(day=day,count=count,share=count/n,cumulative_count=cum,cumulative_share=cum/n))
    missed=int(g[field].isna().sum());assert cum+missed==n
    return dict(n=n,hit=cum,hit_rate=cum/n,no_hit=missed,no_hit_rate=missed/n,by_day=rows,
        median_hit_day=float(g[field].median()),mean_hit_day=float(g[field].mean()))


def main():
    verify();OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v4_decline_first/events.parquet')
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hs={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    assert digest(SOURCE/'calendar.parquet')==m['calendar_sha256']
    dates=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist();pos={s:i for i,s in enumerate(dates)}
    rows=[]
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
            k=pos[e.date];buy=dates[k+1];entry=float(q.loc[buy,'open'])
            path=q.loc[q.index.isin(dates[k+1:k+61])].copy()
            path['buy_offset']=[pos[s]-(k+1) for s in path.index]
            any_day,any_date=first_hit(path,entry,0);eligible,eligible_date=first_hit(path,entry,1)
            rows.append(dict(code=code,name=e['name'],is_leader=bool(e.is_leader),signal_date=e.date,
                buy_date=buy,entry_qfq=entry,entry_raw=float(r.loc[buy,'open']),target_qfq=entry*1.03,
                first_touch_day=any_day,first_touch_date=any_date,
                first_t1_touch_day=eligible,first_t1_touch_date=eligible_date,
                observed_sessions=len(path),window_end=dates[k+60],
                buy_day_touch=any_day==0,
                buy_day_only=bool(any_day==0 and eligible is None)))
    data=pd.DataFrame(rows)
    assert len(data)==len(d) and data[['code','signal_date']].duplicated().sum()==0
    assert data.first_t1_touch_day.dropna().between(1,59).all()
    assert (data.first_t1_touch_day.fillna(100)>=data.first_touch_day.fillna(100)).all()
    data.to_parquet(OUT/'signals.parquet',index=False)
    result={}
    for pool,pm in [('样本池',pd.Series(True,index=data.index)),('龙头子样本',data.is_leader)]:
        g=data.loc[pm]
        result[pool]=dict(price_touch=summarize(g,'first_touch_day'),t1_eligible=summarize(g,'first_t1_touch_day'),
            buy_day_touch=int(g.buy_day_touch.sum()),buy_day_only=int(g.buy_day_only.sum()))
        lines=['代码 | 股票 | 信号日 | 买入日 | 买入原价 | 首次触及+3%日(B0起) | T+1首次触及日(B1起) | T+1触及日期 | 窗口结束']
        for _,e in g.sort_values(['first_t1_touch_day','signal_date','code'],na_position='last').iterrows():
            touch='未触及' if pd.isna(e.first_touch_day) else 'B'+str(int(e.first_touch_day))
            sale='未触及' if pd.isna(e.first_t1_touch_day) else 'B'+str(int(e.first_t1_touch_day))
            lines.append(f"{e.code} | {e['name']} | {e.signal_date} | {e.buy_date} | {e.entry_raw:.2f} | {touch} | {sale} | {e.first_t1_touch_date or '—'} | {e.window_end}")
        (OUT/(pool+'逐信号明细.txt')).write_text('\n'.join(lines),encoding='utf8')
    meta=dict(results=result,boundary='2024-12-31',
        rule='Assume entry at signal next official-session open; high >= entry*1.03 is touch. No stop loss. Keep original D1-D60 window=B0-B59.',
        t1='B0 touch only observational; eligible touch starts B1, even if B0 had already touched. Missing sessions skipped without fabricating bars or changing day numbering.',
        caveat='Touch-date proxy conditional on assumed successful entry. Not actual fills, net 3% after fees, or share/dividend economic-account simulation. Adjusted price path; current-universe/leader retrospective cohort.',
        verification='4 synthetic first-touch tests, quote/calendar hashes, event counts and ordering checks passed.')
    (OUT/'summary.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：固定3%止盈的首次触及时间',
      '基础信号、已排除连续疑似跌停，不叠加其他筛选。沿用原4641条信号，龙头881条，研发截止2024年底。',
      '假设信号次一正式交易日开盘成功买入；买入当天B0，下一交易日B1。沿用原信号后60日观察窗，即B0至B59。',
      '触及依据前复权盘中最高价≥买价×1.03。未加止损，不扣税费，不以3%净利润为目标，不将触及等同于已成交。',
      'A股买入当天不卖出，主结果按B1起首次触及统计；B0只触及但之后没再触及的归为未止盈。',
      '停牌/缺价不造K线、不移动正式交易日编号。逐事件为原始买价及触及日；不是账户复利回测。',
      'T+1历史规则参考：https://www.csrc.gov.cn/csrc/c100028/c1002481/content.shtml']
    for pool,s in result.items():
        a=s['t1_eligible'];lines+=['',pool,f"总数{a['n']}，B1起触及{a['hit']}（{a['hit_rate']:.2%}），未触及{a['no_hit']}；B0触及{s['buy_day_touch']}，其中仅B0触及{s['buy_day_only']}。",'交易日 | 首次可止盈数量 | 占全部 | 累计数量 | 累计占比']
        for x in a['by_day'][1:]:lines.append(f"B{x['day']} | {x['count']} | {x['share']:.2%} | {x['cumulative_count']} | {x['cumulative_share']:.2%}")
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    for pool,s in result.items():
        print(pool,{k:v for k,v in s.items() if k not in ['price_touch','t1_eligible']})
        a=s['t1_eligible'];print({k:v for k,v in a.items() if k!='by_day'})
        for lo,hi in [(1,1),(2,2),(3,3),(4,4),(5,5),(6,10),(11,20),(21,40),(41,59)]:
            count=sum(x['count'] for x in a['by_day'] if lo<=x['day']<=hi)
            print(lo,hi,count,round(count/a['n']*100,2))


if __name__=='__main__':main()
