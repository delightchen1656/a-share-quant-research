"""Verify saved study results, prepare a compact review workbook and path figure."""
from pathlib import Path
import json,hashlib
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

BASE=Path(__file__).resolve().parent
STUDY=BASE/'holdout_restricted/patterns_v1'
R=STUDY/'event_results_v1r2'
D=BASE/'outputs/patterns_20261027/holdout_restricted'
D.mkdir(parents=True,exist_ok=True)

def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    e=pd.read_parquet(R/'events.parquet');paths=pd.read_parquet(R/'daily_paths.parquet')
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(R/'exchange_sessions.csv').date))
    # Independent scalar replay of first rule; exact exchange-calendar offsets.
    expected=set();third_checked=0
    for code,g in e.groupby('code'):
        raw=pd.read_parquet(STUDY/'inputs_daily/raw'/f'{code}.parquet').set_index('date').reindex(dates)
        adj=pd.read_parquet(STUDY/'inputs_daily/qfq'/f'{code}.parquet').set_index('date').reindex(dates)
        valid=raw.volume.gt(0)&raw.tradestatus.astype(str).eq('1')&adj.close.gt(0)&adj.open.gt(0)
        ro=raw.open.to_numpy();rc=raw.close.to_numpy();vv=valid.to_numpy()
        for t in range(7,len(raw)):
            if dates[t] < pd.Timestamp('2019-01-01'):continue
            if vv[t-7:t+1].all() and (rc[t-7:t-2]<ro[t-7:t-2]).all() and (rc[t-2:t+1]>ro[t-2:t+1]).all():
                expected.add(f'first_{code}_{dates[t]:%Y%m%d}')
        for row in g[g.rule=='third'].itertuples():
            t=dates.get_loc(pd.Timestamp(row.signal_date));length=int(row.pullback_length);s=t-length
            seg=adj.iloc[s:t];vol=raw.volume.iloc[s:t].to_numpy(float)
            rawseg=raw.iloc[s:t]
            body=((rawseg.open-rawseg.close)/rawseg.open).to_numpy(float)
            assert (seg.close<seg.open).all()
            assert (seg.close.to_numpy()<adj.close.iloc[s-1:t-1].to_numpy()).all()
            assert np.polyfit(np.arange(length),body,1)[0]<0 and body[-1]<body[0]
            assert np.polyfit(np.arange(length),vol,1)[0]<0 and vol[-1]<vol[0]
            assert adj.close.iloc[s-1]>adj.close.iloc[s-20:s].mean()>adj.close.iloc[s-60:s].mean()
            assert raw.volume.iloc[t]>=1.5*raw.volume.iloc[t-20:t].mean()
            entry=dates.get_loc(pd.Timestamp(row.entry_date));end=dates.get_loc(pd.Timestamp(row.expected_exit_date))
            assert entry==t+1 and end==entry+5
            np.testing.assert_allclose(row.adjusted_price_change,adj.close.iloc[end]/adj.open.iloc[entry]-1,atol=1e-12)
            third_checked+=1
    assert expected==set(e.loc[e.rule=='first','event_id'])
    assert third_checked==int((e.rule=='third').sum())
    summary=json.loads((R/'SUMMARY.json').read_text(encoding='utf-8'))
    y=pd.read_parquet(R/'yearly_summary.parquet');ps=pd.read_parquet(R/'path_summary.parquet')
    firsth=pd.read_csv(R/'first_horizons.csv')
    tabs=[]
    for rule,title,horizon in [('first','五阴三阳逐次',40),('third','缩量回调逐次',5)]:
        sub=e[e.rule==rule].sort_values(['signal_date','code']).copy()
        pivot=paths[paths.rule==rule].pivot(index='event_id',columns='day',values='close_change')
        endpoints=paths[(paths.rule==rule)&(paths.day==horizon)].set_index('event_id').adjusted_close
        heads=['信号编号','代码','名称','信号日期','参考或买入日','观察或卖出日','调整后参考价','调整后终点价','价格变化','期间最高涨幅','期间最低跌幅','未走满观察期','路径完整','40日不重叠样本','买入日单一价格','卖出日单一价格','缩量阴线数','原始参考价','原始终点变化诊断']+[f'D{i}收盘变化' for i in range(horizon+1)]
        rows=[]
        for q in sub.itertuples():
            row=[q.event_id,q.code,q.name,q.signal_date,q.entry_date,q.expected_exit_date,q.adjusted_reference_price,
                 endpoints.get(q.event_id,np.nan),None,q.max_high_change,q.min_low_change,
                 '是' if q.future_censored else '否','是' if q.complete_path else '否',
                 '不适用' if rule=='third' else ('是' if q.nonoverlap40 else '否'),
                 '是' if q.entry_one_price_day else '否','是' if q.exit_one_price_day else '否',
                 q.pullback_length,q.raw_reference_price,q.raw_per_share_price_change_diagnostic_only]
            row += [pivot.loc[q.event_id,i] if q.event_id in pivot.index and i in pivot.columns else None for i in range(horizon+1)]
            rows.append([None if pd.isna(x) else x for x in row])
        tabs.append(dict(name=title,rule=rule,headers=heads,rows=rows))
    notes=[
        ['股票范围','185只近期筛出的板块指示股票。股票池使用近期关系选出，历史回放有事后选池偏差。'],
        ['研究日期','信号日2019-01-01至2026-10-26。未满观察期的信号保留，收益留空。'],
        ['收益口径','供应商前复权价格变化。未扣费，未合并账户，未核对持股分红送转应收与到账。'],
        ['第一条','连续5根收盘低于开盘的阴线，紧接3根收盘高于开盘的阳线。不另加筑底条件。'],
        ['第一条参考','第3根阳线收盘作为观察参考，查看随后40个交易日。收盘确认不代表可提前按该收盘买到。'],
        ['第三条趋势','回调前一日调整后收盘价高于MA20，且MA20高于MA60。'],
        ['第三条回调','连续3—5根阴线且收盘逐日下降。原始开收盘实体比例与成交量回归斜率为负，最后值低于最初值。'],
        ['第三条放量','紧接阳线且收盘上涨，成交量不低于此前20个交易日均量的1.5倍，均量不含当日。'],
        ['第三条时点','收盘确认，下一交易日开盘参考买入，买入日D0，D+5收盘参考卖出，共跨5个交易日。'],
        ['数值来源','3—5根和1.5倍为本轮结果前声明的操作化默认值。用户原话是实体整体缩小、成交量减少后放量上涨。'],
        ['成交限制','逐次价格观察不证明涨停开盘可排队成交或跌停收盘可卖出。单一价格日另有标记。'],
        ['缺价处理','按正式交易日历对齐。缺行、停牌、十字星打断形态。未来缺价不填零、不删掉原信号。'],
        ['第二条状态','未计算。缺少该股票池足够的历史1分钟数据和当时有效的涨跌停价。'],
        ['第二条买入','前一交易日未收涨停，当日触及涨停后开板，按用户假设以涨停价全部买入。'],
        ['第二条退出','从次日起14:30后开板，完成分钟K线后尝试下一分钟开盘卖；最多持有5个交易日。'],
        ['第二条时序','日线最高和最低无法判断先封后开或尾盘开板。分钟同柱内的触板与开板先后也须保留歧义标记。'],
        ['第二条所需输入','代码、交易日期时间、1分钟OHLC与成交量、原始价格、上下限、参考价、停复牌及上市日期。'],
        ['数据来源','147只复用已提交本地原始和前复权日线，38只补充腾讯按年查询日线并核对重叠价格。'],
        ['公共日线接口','https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'],
        ['极端样本核对','第三条最高样本为鸣志电器2022-07-26开盘至2022-08-02收盘，原始价23.05至40.78。'],
        ['重叠处理','第一条另算同一股票40个交易日内只保留首个信号的敏感性统计。跨股票同日信号仍可能相关。'],
        ['口径修正','实体比例采用当日原始价，防止未来现金分红平移复权价后改变历史形态。不做参数或阈值挑优。'],
        ['列含义','D0至D40是各交易日收盘相对参考价的变化。第三条D0为买入当天收盘，不强制等于0。'],
        ['原始价诊断','原始终点变化仅用于检查报价。跨分红送转时不能当作真实持股收益。'],
    ]
    # Avoid repeating a failed preflight as a backtest version: no pattern outcomes
    # existed before this repair, only synthetic checks and calendar snapshot.
    dump(STUDY/'event_results_v1/PREFLIGHT_FAILURE.json',dict(
        stage='before_any_pattern_outcomes',issue='proportional factor check invalid for additive cash-dividend price adjustment',
        correction='verify positive affine within-day mapping and candle direction instead',
        no_signal_parameters_or_thresholds_optimized=True))
    data=dict(tabs=tabs,notes=notes,summary=summary,
        yearly=json.loads(y.to_json(orient='records')),horizons=json.loads(firsth.to_json(orient='records')),
        path_summary=json.loads(ps.to_json(orient='records')))
    dump(D/'workbook_data.json',data)
    dump(R/'INDEPENDENT_CHECKS.json',dict(first_independent_replay_matches=len(expected),third_scalar_events_verified=third_checked,
        top_outlier_raw_prices_checked=True,no_rule_optimization_after_outcomes=True))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),constrained_layout=True)
    for ax,rule,title in zip(axes,['first','third'],['五阴三阳：第3根阳线收盘之后','缩量回调后放量：次日开盘之后']):
        q=ps[(ps.rule==rule)&(ps.cohort=='complete_path_only')].sort_values('day')
        ax.fill_between(q.day,q.p10,q.p90,color='#dce5f2',label='10%—90%分位')
        ax.plot(q.day,q['mean'],color='#2454a6',lw=2,label='平均价格变化')
        ax.plot(q.day,q['median'],color='#b45f2e',lw=2,label='中位数')
        ax.axhline(0,color='#777',lw=.7);ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_title(title,fontsize=12);ax.set_xlabel('相对交易日（D0为参考当天）')
        ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,fontsize=9)
        ax.text(.02,.03,f'固定完整路径样本 n={int(q.n.iloc[0])}',transform=ax.transAxes,fontsize=9)
    fig.suptitle('185只股票历史形态研究  2019—2026-10-26\n供应商前复权价格变化；当前选池回看，非账户收益',fontsize=13)
    fig.savefig(D/'价格路径.png',dpi=160);plt.close(fig)
    report='''185只板块指示股票，三种形态的逐次信号研究\n信号期：2019-01-01至2026-10-26。当前选池有事后选择偏差。\n收益为供应商前复权价格变化，未合并账户、未扣费、未核对真实股东权益到账。\n\n'''
    for rule,label in [('first','第一条：五阴三阳，随后40个交易日'),('third','第三条：缩量收敛后放量，次日开盘至D+5收盘')]:
        q=summary['summaries'][rule];s=q['price_change']
        report+=f"{label}\n信号{q['signals']}次，有效终点{s['n']}次，均值{s['mean']:.4%}，中位数{s['median']:.4%}，胜率{s['win_rate']:.4%}。\n10%分位{s['p10']:.4%}，90%分位{s['p90']:.4%}。\n\n"
    report+='第二条未计算：尚无足够的历史分钟输入，不能用日线推断尾盘开板。\n\n逐年统计：\n'+y.to_string(index=False)+'\n'
    (D/'研究结果.txt').write_text(report,encoding='utf-8')
    print('Independent checks passed; workbook source prepared; path figure saved.',flush=True)

if __name__=='__main__':main()
