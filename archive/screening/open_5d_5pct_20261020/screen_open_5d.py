"""直接筛选本地沪深日线：t开盘买入，t+1..t+5触及+5%，及触及日以前跌幅<5%。

运行：quant_env\Scripts\python.exe -B tools/screen_open_5d.py
回撤基准为买入价，不是滚动最高价。首次触及当天整日最低价计入。
仅用raw价格，不调整现金分红；开盘非涨停不等于保证真实成交。
"""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'sh_sz_market_research/data_pipeline/data'

def screen(bars):
    """日历对齐后计算；完整观察t至t+5，t日最高价不算目标。"""
    entry = (bars.open * 100).round()
    target_day = pd.Series(0, index=bars.index, dtype='int8')
    floor = (bars.low * 100).round().where(bars.tradestatus.eq(1))
    target_floor = pd.Series(np.nan, index=bars.index)
    complete = bars[['open','high','low','close','tradestatus']].notna().all(axis=1)
    for k in range(1, 6):
        complete &= bars[['high','low','close','tradestatus']].shift(-k).notna().all(axis=1)
        active = bars.tradestatus.shift(-k).eq(1)
        low = (bars.low.shift(-k) * 100).round().where(active)
        floor = pd.concat([floor, low], axis=1).min(axis=1)
        touch = active & ((bars.high.shift(-k) * 100).round() * 100 >= entry * 105)
        first = target_day.eq(0) & touch
        target_day.loc[first] = k
        target_floor.loc[first] = floor.loc[first]
    x = target_day.gt(0)
    y = x & (target_floor * 100 > entry * 95)
    return pd.DataFrame({'complete':complete,'x':x,'y':y,'first_hit_offset':target_day,
                         'min_low_through_hit':target_floor / 100,
                         'max_loss_through_hit':(1-target_floor/entry).clip(lower=0)},index=bars.index)

def selftest():
    def sample():
        return pd.DataFrame({'open':[10.]*6,'high':[10.2]*6,'low':[9.8]*6,
                             'close':[10.]*6,'tradestatus':[1]*6})
    a=sample();a.loc[0,'high']=11;assert not screen(a).iloc[0].x
    a=sample();a.loc[5,'high']=10.5;assert screen(a).iloc[0].y
    a.loc[5,'low']=9.5;assert screen(a).iloc[0].x and not screen(a).iloc[0].y
    a.loc[5,'low']=9.51;assert screen(a).iloc[0].y
    a.loc[0,'low']=9.49;assert not screen(a).iloc[0].y
    a=sample();a.loc[1,'high']=10.5;a.loc[2,'low']=8;assert screen(a).iloc[0].y
    a.loc[1,'low']=9.5;assert not screen(a).iloc[0].y
    a=sample();a.loc[5,'high']=10.49;assert not screen(a).iloc[0].x
    assert not screen(a).iloc[1].complete
    a.loc[5,'high']=11;a.loc[5,'tradestatus']=0;assert not screen(a).iloc[0].x
    return 10

def run(out):
    tests=selftest()
    if (out/'summary.json').exists():
        raise SystemExit('结果已存在，请用 --out 指定新的输出目录，避免覆盖。')
    out.mkdir(parents=True,exist_ok=True)
    meta=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv').set_index('symbol')
    calfile=sorted((DATA/'metadata').glob('trade_calendar_*.csv'))[-1]
    calendar=pd.read_csv(calfile)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date']))
    dates=dates[dates>='2018-01-01']
    files=sorted((DATA/'raw').glob('*/*.parquet'))
    stats=[];yearly=[];matches=[];part=0
    for j,path in enumerate(files):
        raw=pd.read_parquet(path);raw.date=pd.to_datetime(raw.date)
        assert not raw.date.duplicated().any(),str(path)
        for col in ['open','high','low','close','preclose','tradestatus','isST','volume']:
            raw[col]=pd.to_numeric(raw[col],errors='coerce')
        b=raw.set_index('date').sort_index().reindex(dates)
        result=screen(b)
        # 按分四舍五入：普通主板10%；风险警示旧制5%，2026-07-06起10%。
        previous=(b.preclose*100).round()
        rate=pd.Series(np.where(b.isST.eq(1)&(dates<'2026-07-06'),5,10),index=dates)
        upper=np.floor((previous*(100+rate)+50)/100)
        ipo=pd.Timestamp(meta.loc[path.stem,'ipoDate'])
        old_ipo=(dates==ipo)&(ipo<pd.Timestamp('2023-04-10'))
        no_limit=pd.Series(False,index=dates)
        if ipo>=pd.Timestamp('2023-04-10'):
            first5=dates[dates>=ipo][:5];no_limit.loc[first5]=True
        opened_limit=(b.open*100).round().ge(upper)&~no_limit
        basic=b.tradestatus.eq(1)&b.open.gt(0)&b.volume.gt(0)&b.preclose.gt(0)&b.isST.isin([0,1])
        # 旧制IPO首日/超出常规涨幅的特殊交易日单列，避免误判涨停。
        special=pd.Series(old_ipo,index=dates)|((b.high*100).round().gt(upper+1)&~no_limit)
        eligible=basic&~special&~opened_limit&result.complete
        result['eligible']=eligible
        result['symbol']=path.stem;result['entry_open']=b.open
        result['first_hit_date']=pd.NaT
        for k in range(1,6):
            m=result.first_hit_offset.eq(k)
            result.loc[m,'first_hit_date']=pd.Series(dates,index=dates).shift(-k).loc[m]
        rows={'symbol':path.stem,'raw_rows':len(raw),'eligible':int(eligible.sum()),
              'x':int((eligible&result.x).sum()),'y':int((eligible&result.y).sum()),
              'special_limit_unknown':int((basic&special).sum()),
              'open_limit_excluded':int((basic&~special&opened_limit).sum()),
              'incomplete_excluded':int((basic&~special&~opened_limit&~result.complete).sum())}
        stats.append(rows)
        q=result.loc[eligible].copy()
        for year,g in q.groupby(q.index.year):
            yearly.append({'year':int(year),'eligible':len(g),'x':int(g.x.sum()),'y':int(g.y.sum())})
        hits=q.loc[q.x].reset_index(names='entry_date')
        matches.append(hits)
        if len(matches)==100 or j==len(files)-1:
            pd.concat(matches,ignore_index=True).to_parquet(out/f'x_matches_{part:03d}.parquet',index=False)
            matches=[];part+=1;print('SCANNED',j+1,len(files),flush=True)
    stock=pd.DataFrame(stats);stock.to_csv(out/'by_stock.csv',index=False,encoding='utf-8-sig')
    annual=pd.DataFrame(yearly).groupby('year',as_index=False).sum()
    annual['x_rate']=annual.x/annual.eligible;annual['y_given_x']=annual.y/annual.x
    annual.to_csv(out/'by_year.csv',index=False,encoding='utf-8-sig')
    totals={c:int(stock[c].sum()) for c in stock.columns if c!='symbol'}
    totals.update({'stocks':len(files),'x_rate':totals['x']/totals['eligible'],
                   'y_given_x':totals['y']/totals['x'],'y_rate':totals['y']/totals['eligible'],
                   'synthetic_tests_passed':tests,'calendar_file':str(calfile),
                   'definition':'t开盘买入；只查t+1至t+5；high>=open_t*1.05为x；t至首次触及日low均>open_t*.95为y；按股票-买入日计次，完整6日窗口，非独立交易',
                   'limitations':'原始价格，不加现金分红；非涨停为历史日线规则筛选，非真实成交保证；特殊涨幅日/旧制IPO首日单列。此全库描述统计不反馈隔离优化代理。'})
    (out/'summary.json').write_text(json.dumps(totals,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(totals,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'screening_results/open_5d_5pct')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:print('PASS',selftest())
    else:run(args.out.resolve())
