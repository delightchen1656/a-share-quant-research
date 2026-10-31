"""One fixed user hypothesis: prior box bullish daily volume exceeds signal volume."""
from pathlib import Path
import datetime,json
import numpy as np
import pandas as pd
from research import INPUT,OUT,verify_inputs,sha
from evaluate_positive_base_volume15 import counts

RESULT=OUT/'user_prior_bull_volume_exceeds_signal_v1'

def describe(box,signal_volume):
    assert len(box)==15 and signal_volume>0
    assert box[['open','close','volume']].notna().all().all()
    bullish=box[box.close.gt(box.open)]
    biggest=float(bullish.volume.max()) if len(bullish) else 0.
    date=bullish.volume.idxmax().strftime('%Y-%m-%d') if len(bullish) else None
    return dict(box_bullish_days=len(bullish),box_max_bull_volume=biggest,
        box_max_bull_volume_date=date,signal_volume=float(signal_volume),
        prior_bull_signal_volume_ratio=biggest/signal_volume,
        keep_user_rule=bool(biggest<=signal_volume))

def checks():
    dates=pd.bdate_range('2020-01-01',periods=15)
    box=pd.DataFrame({'open':np.full(15,10.),'close':np.full(15,10.),'volume':np.full(15,1000.)},index=dates)
    box.iloc[0,1]=9 # large-volume bearish candle does not count
    assert describe(box,200)['keep_user_rule'] # doji candles do not count either
    box.iloc[2,1]=11;box.iloc[2,2]=200
    assert describe(box,200)['keep_user_rule'] # equal volume is not greater
    box.iloc[2,2]=201
    assert not describe(box,200)['keep_user_rule']
    assert describe(box,200)['box_max_bull_volume_date']==dates[2].strftime('%Y-%m-%d')
    return dict(raw_bull_only=True,equality_kept=True,bearish_and_doji_ignored=True)

def main():
    verify_inputs();assert not (RESULT/'RESULT.json').exists(),'Preserve registered fixed-rule result.'
    RESULT.mkdir(parents=True,exist_ok=True)
    rule=dict(source='user_hypothesis_no_threshold_search',scope='existing_starred_box_volume12_signals_only',
        reject='max(raw V among raw close>open days in t-15..t-1)>raw V[t]',
        interpretation='at least one prior bullish candle single-day volume; not sum of bullish volumes',
        equality='keep when largest prior bullish volume equals signal volume',
        no_prior_bullish_days='keep',application='after baseline same-box dedup; no later-signal backfill',
        other_previous_experimental_filters_not_applied=True,no_production_change=True,
        cutoff='2024-12-31',post2024_labels_not_read=True,not_a_blind_test=True,
        registered_at=datetime.datetime.now().isoformat())
    (RESULT/'RULE.json').write_text(json.dumps(rule,ensure_ascii=False,indent=2),encoding='utf-8')
    f=pd.read_parquet(INPUT/'features.parquet')
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(INPUT/'exchange_sessions.csv').date))
    extras=[]
    for code,g in f.groupby('code'):
        raw=pd.read_parquet(INPUT/'raw'/f'{code}.parquet').set_index('date').reindex(dates)
        for row in g.itertuples():
            t=dates.get_loc(pd.Timestamp(row.signal_date))
            details=describe(raw.iloc[t-15:t],float(raw.volume.iloc[t]))
            extras.append(dict(event_id=row.event_id,**details))
    f=f.merge(pd.DataFrame(extras),on='event_id',validate='one_to_one')
    labels=pd.concat([pd.read_parquet(INPUT/'labels_trainval.parquet'),pd.read_parquet(OUT/'sealed_labels.parquet')])
    f=f.merge(labels.drop(columns='split'),on='event_id',validate='one_to_one')
    assert f.is_leader.all() and f.signal_date.le('2024-12-31').all() and f.label_end.le('2024-12-31').all()
    f['classification']=np.select([f.bad&~f.keep_user_rule,~f.bad&~f.keep_user_rule,f.bad&f.keep_user_rule],
        ['removed_below10','false_removed_reached10','kept_below10'],default='kept_reached10')
    cols=['code','name','signal_date','peak_return60','box_max_bull_volume_date','prior_bull_signal_volume_ratio']
    result=dict(rule_sha256=sha(RESULT/'RULE.json'),whitelist_sha256=sha(INPUT/'manifest.json'),
        all_pre2025=counts(f),by_year=[dict(year=int(y),**counts(g)) for y,g in f.groupby('year')],
        original37_cohort=counts(f[f.split.isin(['train','validation'])]),
        false_removals=f.loc[~f.bad&~f.keep_user_rule,cols].to_dict('records'),
        correct_removals=f.loc[f.bad&~f.keep_user_rule,cols].to_dict('records'),
        tests=checks(),viewer_unchanged=True,post2024_labels_not_read=True)
    c=result['all_pre2025'];assert c['bad_total']==26 and c['good_total']==32
    assert c['bad_removed']+c['good_removed']+c['retained']==58
    f.to_parquet(RESULT/'classified_events.parquet',index=False)
    (RESULT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['箱体内既有阳线放量超过信号日：单独检验','',
        '只针对原始1.2倍箱体信号里的★龙头。此前15日箱体内，存在原始收盘高于开盘的阳线，其单日量严格大于信号日量，则剔除。相等保留，不累计阳线成交量。',
        '不叠加之前的横盘上涨、1.5倍信号量过滤；不补选同箱后续信号。',
        '2019–2024年、截至2024年底完成60日观察的58次样本；2024已查看，仅历史检验，不称盲测。','',
        '年份 | 不足10%原数量 | 筛掉不足10% | 达到10%原数量 | 误删达到10% | 最后保留']
    for r in result['by_year']:
        lines.append(f"{r['year']} | {r['bad_total']} | {r['bad_removed']} | {r['good_total']} | {r['good_removed']} | {r['retained']}")
    lines+=['',f"合计：筛掉不足10% {c['bad_removed']}/{c['bad_total']}={c['bad_removal_rate']:.2%}；误删达到10% {c['good_removed']}/{c['good_total']}={c['good_false_removal_rate']:.2%}。",
        f"剩余{c['retained']}次：不足10%有{c['bad_kept']}次、达到10%有{c['good_kept']}次。达到10%比例从{c['good_share_before']:.2%}变为{c['good_share_after']:.2%}。",'',
        '误删达到10%的信号：']
    for r in result['false_removals']:
        lines.append(f"{r['signal_date']} {r['code']} {r['name']}：60日最高{r['peak_return60']:.2%}，箱体内{r['box_max_bull_volume_date']}阳线成交量为信号日{r['prior_bull_signal_volume_ratio']:.3f}倍。")
    lines+=['','正确筛掉不足10%的信号：']
    for r in result['correct_removals']:
        lines.append(f"{r['signal_date']} {r['code']} {r['name']}：60日最高{r['peak_return60']:.2%}，箱内阳线最大量/信号量={r['prior_bull_signal_volume_ratio']:.3f}。")
    lines+=['','60日最高点仅为事后价格观察，不代表实际成交收益。软件及非龙头信号未改。']
    (RESULT/'结果说明.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
