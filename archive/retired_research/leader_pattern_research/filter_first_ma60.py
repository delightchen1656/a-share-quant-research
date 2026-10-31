"""One user-requested MA60 condition on the frozen five-yin/three-yang study."""
from pathlib import Path
import json,hashlib,datetime
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from analyze_patterns import stats

BASE=Path(__file__).resolve().parent
STUDY=BASE/'holdout_restricted/patterns_v1'
SOURCE=STUDY/'event_results_v1r2'
OUT=STUDY/'first_below_ma60_v1'
DELIVERY=BASE/'outputs/first_below_ma60_20261027/holdout_restricted'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    assert not OUT.exists(),'Preserve registered outcome; use a new explicit version for corrections'
    OUT.mkdir(parents=True);DELIVERY.mkdir(parents=True,exist_ok=True)
    dump(OUT/'SPEC.json',dict(registered_before_new_outcomes=True,
        user_request='五阴接三阳，并且低于M60均线，观察随后40个交易日',
        interpretation='Third positive candle close strictly below same-day MA60.',
        MA60='Arithmetic mean of60consecutive exchange-session adjusted closes ending at signal day; includes signal close; all60require valid active quotes.',
        period='2019-01-01 to2026-10-26',pool=185,additional_thresholds_or_search=False,
        output='Per-signal price changes and paths, not portfolio P&L; preserve existing frozen endpoints.',
        source_events_sha256=sha(SOURCE/'events.parquet'),
        caveat='Retrospective current-stock pool selected from recent relations; not a blind test. Adjusted quote return, not reconciled economic shareholder or net execution return.'))
    events=pd.read_parquet(SOURCE/'events.parquet')
    first=events.loc[events.rule.eq('first')].copy()
    paths=pd.read_parquet(SOURCE/'daily_paths.parquet')
    paths=paths.loc[paths.rule.eq('first')].copy()
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(SOURCE/'exchange_sessions.csv').date))
    manifest=json.loads((STUDY/'inputs_daily/manifest.json').read_text(encoding='utf-8'))
    checks={f['code']:f for f in manifest['files'] if f['mode']=='qfq'}
    records=[]
    for code,sub in first.groupby('code'):
        p=STUDY/'inputs_daily/qfq'/f'{code}.parquet'
        assert sha(p)==checks[code]['snapshot_sha256']
        q=pd.read_parquet(p).set_index('date').reindex(dates)
        close=pd.to_numeric(q.close,errors='coerce')
        valid=(pd.to_numeric(q.volume,errors='coerce')>0)&q.tradestatus.astype(str).eq('1')&close.gt(0)
        c=close.where(valid)
        ma=c.rolling(60,min_periods=60).mean()
        for row in sub.itertuples():
            t=dates.get_loc(pd.Timestamp(row.signal_date));value=ma.iloc[t]
            assert abs(close.iloc[t]-row.adjusted_reference_price)<1e-10
            below=bool(np.isfinite(value) and close.iloc[t]<value)
            # Independent scalar calculation checks exact window and no future use.
            if np.isfinite(value):
                np.testing.assert_allclose(value,c.iloc[t-59:t+1].to_numpy().sum()/60,atol=1e-12)
                assert below==bool(close.iloc[t]<(c.iloc[:t+1].tail(60).mean()))
                assert below==bool((close.iloc[t]*1.7+3)<(value*1.7+3))
            records.append(dict(event_id=row.event_id,signal_close=float(close.iloc[t]),
                ma60=float(value) if np.isfinite(value) else None,
                close_relative_ma60=float(close.iloc[t]/value-1) if np.isfinite(value) else None,
                ma60_available=bool(np.isfinite(value)),below_ma60=below))
    tagged=first.merge(pd.DataFrame(records),on='event_id',validate='one_to_one')
    chosen=tagged[tagged.below_ma60].copy()
    chosen_paths=paths[paths.event_id.isin(chosen.event_id)].copy()
    # Nonoverlap sensitivity is independently selected after applying this condition.
    chosen['filtered_nonoverlap40']=False
    for code,g in chosen.sort_values('signal_date').groupby('code'):
        last=-10000
        for idx,row in g.iterrows():
            t=dates.get_loc(pd.Timestamp(row.signal_date))
            if t>last:chosen.loc[idx,'filtered_nonoverlap40']=True;last=t+40
    for name,df in [('all_first_signals_tagged',tagged),('selected_events',chosen),('selected_daily_paths',chosen_paths)]:
        df.to_parquet(OUT/f'{name}.parquet',index=False)
    comparisons=[]
    for label,g in [('原规则',tagged),('加收盘低于MA60',chosen),('MA60可用且未低于',tagged[tagged.ma60_available&~tagged.below_ma60])]:
        comparisons.append(dict(label=label,signals=len(g),stocks=int(g.code.nunique()),
            censored=int(g.future_censored.sum()),mature_missing_exit=int((~g.future_censored&~g.exit_quote_available).sum()),
            full_paths=int(g.complete_path.sum()),**stats(g.adjusted_price_change)))
    yearrows=[];horizons=[]
    for label,g in [('原规则',tagged),('加收盘低于MA60',chosen)]:
        for year,s in g.groupby('year'):
            yearrows.append(dict(label=label,year=int(year),signals=len(s),**stats(s.adjusted_price_change)))
        pp=paths[paths.event_id.isin(g.event_id)]
        for day in [1,5,10,20,40]:horizons.append(dict(label=label,day=day,**stats(pp.loc[pp.day.eq(day),'close_change'])))
    # Equal-sized cohorts along each curve: retain every full-path signal.
    path_summary=[]
    for label,g in [('原规则',tagged),('加收盘低于MA60',chosen)]:
        ids=g.loc[g.complete_path,'event_id']
        pp=paths[paths.event_id.isin(ids)]
        for day,s in pp.groupby('day'):path_summary.append(dict(label=label,day=int(day),**stats(s.close_change)))
    summary=dict(comparison=comparisons,yearly=yearrows,horizons=horizons,
        missing_ma60=int((~tagged.ma60_available).sum()),
        filtered_nonoverlap40=stats(chosen.loc[chosen.filtered_nonoverlap40,'adjusted_price_change']),
        complete_path_only=stats(chosen.loc[chosen.complete_path,'adjusted_price_change']),
        path_summary=path_summary,
        checks=dict(stock_snapshot_hashes_verified=int(first.code.nunique()),scalar_ma60_windows_verified=len(records),
                    original_signals_retained=1008,original_endpoints_unchanged=True,threshold_search=False))
    dump(OUT/'SUMMARY.json',summary)
    # A compact workbook input keeps per-event reference prices and the full path.
    pivot=chosen_paths.pivot(index='event_id',columns='day',values='close_change')
    endpoints=chosen_paths.loc[chosen_paths.day.eq(40)].set_index('event_id').adjusted_close
    heads=['信号编号','代码','名称','信号日期','40日终点日期','调整后参考价','当日MA60','收盘偏离MA60','调整后终点价','40日价格变化','期间最高涨幅','期间最低跌幅','未满40日','路径完整','同股40日去重']+[f'D{i}收盘变化' for i in range(41)]
    rows=[]
    for r in chosen.sort_values(['signal_date','code']).itertuples():
        row=[r.event_id,r.code,r.name,r.signal_date,r.expected_exit_date,r.signal_close,r.ma60,r.close_relative_ma60,
             endpoints.get(r.event_id,np.nan),r.adjusted_price_change,r.max_high_change,r.min_low_change,
             '是' if r.future_censored else '否','是' if r.complete_path else '否','是' if r.filtered_nonoverlap40 else '否']
        row += [pivot.loc[r.event_id,d] if r.event_id in pivot.index and d in pivot.columns else None for d in range(41)]
        rows.append([None if pd.isna(x) else x for x in row])
    notes=[['筛选条件','在原五阴接三阳信号上，要求第3根阳线收盘价严格低于当日MA60。'],
        ['MA60口径','截至信号日最近60个交易日的调整后收盘算术均值，包含当日。60日内缺价则不选。'],
        ['观察期限','第3根阳线收盘为D0，查看其后40个交易日；参考时点与原研究一致。'],
        ['范围与日期','沿用185只股票及已冻结日线快照，信号日2019-01-01至2026-10-26。'],
        ['收益口径','供应商前复权价格变化，未扣费、未合并账户，未核对实际分红送转及到账。'],
        ['股票池偏差','股票池按近期关系筛选，历史回看有事后选择偏差。本轮是在看过原结果后增加条件，不是盲测。'],
        ['缺价处理','未满40日或40日终点无有效报价的收益留空，信号保留。每天路径的缺价也留空。'],
        ['去重处理','应用MA60条件后，同一股票40个交易日内只取首个信号，作为敏感性统计。'],
        ['成交限制','第三根阳线收盘确认后才知道信号。该收盘是观察价，不能据此认定可在同一收盘成交。'],
        ['数据来源','复用原研究冻结的本地日线及腾讯补充日线，原始与复权价格单位分别留存。'],
        ['补充日线接口','https://web.ifzq.gtimg.cn/appstock/app/fqkline/get']]
    dump(DELIVERY/'workbook_data.json',dict(summary=summary,headers=heads,rows=rows,notes=notes))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(11.5,4.2),constrained_layout=True)
    ps=pd.DataFrame(path_summary)
    for label,color in [('原规则','#888888'),('加收盘低于MA60','#2454A6')]:
        s=ps[ps.label.eq(label)].sort_values('day')
        axes[0].plot(s.day,s['mean'],label=f'{label}（n={int(s.n.iloc[0])}）',color=color,lw=2)
        axes[1].plot(s.day,s['median'],label=label,color=color,lw=2)
    for ax,title in zip(axes,['完整路径样本的平均价格变化','完整路径样本的中位数变化']):
        ax.set_title(title);ax.set_xlabel('信号后的交易日');ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.axhline(0,color='#555555',lw=.7);ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,fontsize=9)
    fig.suptitle('五阴接三阳，加收盘低于MA60：40日价格路径\n2019—2026-10-26；当前股票池回看，未扣费的复权价格变化',fontsize=12)
    fig.savefig(DELIVERY/'MA60价格路径对比.png',dpi=150);plt.close(fig)
    print(json.dumps(dict(comparison=comparisons,yearly=yearrows,missing_ma60=summary['missing_ma60'],nonoverlap=summary['filtered_nonoverlap40']),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
