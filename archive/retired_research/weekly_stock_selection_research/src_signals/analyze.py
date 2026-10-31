"""Registered signal means; not an executable portfolio or additional parameter search."""
from pathlib import Path
import sys
import json
import hashlib
import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BASE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BASE/'src'))
from portfolio import Quotes
from common import tick
OUT=BASE/'audits/holdout_restricted/signal_average_v3'
NAMES={'random10':'固定随机10只','liquidity10':'流动性优先','momentum20':'20日动量',
       'reversal5':'5日短期反转','lowvol20':'20日低波动','volume_expansion':'量能扩张',
       'range_high':'靠近20日高位','simple_composite':'简单多因子组合','ridge':'岭回归',
       'hist_gradient_boosting':'梯度提升模型','eligible_pool':'同期候选池均值','sse':'同期上证'}
TIMING={'Friday':'上周五开盘→周二收盘','Monday':'周一开盘→周二收盘'}
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def bootstrap_mean_interval(values):
    # Fixed five-observation circular blocks preserve short serial dependence.
    x=np.asarray(values,float)
    x=x[np.isfinite(x)]
    if len(x)<5:
        return [None,None]
    rng=np.random.default_rng(26027)
    starts=rng.integers(0,len(x),size=(2000,int(np.ceil(len(x)/5))))
    ix=(starts[:,:,None]+np.arange(5))%len(x)
    means=x[ix.reshape(2000,-1)[:,:len(x)]].mean(axis=1)
    return np.quantile(means,[.025,.975]).tolist()


def main():
    validation=json.loads((OUT/'validation.json').read_text(encoding='utf-8'))
    assert validation['passed']
    assert not (OUT/'summary.parquet').exists(),'Retain completed diagnostics; no hidden retries'
    reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    for row in reg['files']:
        assert digest(BASE/row['path'])==row['sha256'],row['path']
    assert digest(OUT/'spec.json')==reg['spec_sha256']
    q=Quotes()
    summaries=[]
    years=[]
    curves=[]
    selections=[]
    label_counts=[]
    for endpoint,folder,entrycol in [('Friday','friday_open_v2','entry_day'),('Monday','research_v1','monday')]:
        root=BASE/'audits/holdout_restricted'/folder
        panel=pd.read_parquet(root/'weekly_factor_panel.parquet').rename(columns={entrycol:'entry_date'})
        panel=panel.loc[panel.year.isin([2021,2022,2023])].copy()
        scores=pd.read_parquet(root/'selection_scores_top30.parquet').rename(columns={entrycol:'entry_date'})
        top=scores.loc[scores['rank'].le(10)]
        assert top.groupby(['method','entry_date']).size().eq(10).all()
        merged=top.merge(panel[['symbol','entry_date','tuesday','ordinary_gross_quote_return','label_status']],
                         on=['symbol','entry_date','tuesday'],how='left',validate='many_to_one',indicator=True)
        assert merged['_merge'].eq('both').all()
        merged=merged.drop(columns='_merge')
        merged['endpoint']=endpoint
        entry_flags={}
        exit_flags={}
        # Observe constraints without deleting any originally selected signal.
        for row in merged[['symbol','entry_date','tuesday']].drop_duplicates().itertuples():
            i=q.days.get_loc(pd.Timestamp(row.entry_date))
            j=q.days.get_loc(pd.Timestamp(row.tuesday))
            b=q.bar(row.symbol,i)
            e=q.bar(row.symbol,j)
            entry_flags[(row.symbol,row.entry_date)]=bool(b['active'] and not b['st'] and b['open']<tick(b['preclose']*1.1)-.004)
            exit_flags[(row.symbol,row.entry_date)]=bool(e['active'] and e['close']>tick(e['preclose']*(.95 if e['st'] else .9))+.004)
        merged['opening_quote_allows_buy']=[entry_flags[(r.symbol,r.entry_date)] for r in merged.itertuples()]
        merged['Tuesday_quote_allows_exit']=[exit_flags[(r.symbol,r.entry_date)] for r in merged.itertuples()]
        selections.append(merged)
        pool=panel.groupby(['entry_date','tuesday','year']).agg(pool_mean=('ordinary_gross_quote_return','mean'),
            pool_total=('symbol','size'),pool_known=('ordinary_gross_quote_return','count'),index_mean=('market_return','first')).reset_index()
        for method,g in merged.groupby('method',sort=False):
            by=g.groupby(['entry_date','tuesday','year']).agg(signal_mean=('ordinary_gross_quote_return','mean'),
                 selected=('symbol','size'),known=('ordinary_gross_quote_return','count'),
                 failed_open=('opening_quote_allows_buy',lambda x:int((~x).sum())),
                 failed_exit=('Tuesday_quote_allows_exit',lambda x:int((~x).sum()))).reset_index()
            by=by.merge(pool,on=['entry_date','tuesday','year'],validate='one_to_one').sort_values('entry_date')
            by['mean_excess_pool']=by.signal_mean-by.pool_mean
            by['mean_excess_index']=by.signal_mean-by.index_mean
            by['cumulative_mean_sum']=by.signal_mean.cumsum()
            by['cumulative_excess_pool_sum']=by.mean_excess_pool.cumsum()
            by['method']=method
            by['endpoint']=endpoint
            curves.append(by)
            ci=bootstrap_mean_interval(by.mean_excess_pool)
            complete=by.known.eq(by.selected)
            known=g.ordinary_gross_quote_return.dropna()
            summaries.append(dict(endpoint=endpoint,method=method,signal_dates=len(by),selected=len(g),known=len(known),
                unknown=int(g.ordinary_gross_quote_return.isna().sum()),known_coverage=float(len(known)/len(g)),
                mean_signal_return=float(by.signal_mean.mean()),mean_excess_pool=float(by.mean_excess_pool.mean()),
                mean_excess_index=float(by.mean_excess_index.mean()),
                excess_pool_block_bootstrap_ci_low=ci[0],excess_pool_block_bootstrap_ci_high=ci[1],
                per_known_signal_median=float(known.median()),per_known_signal_win_rate=float(known.gt(0).mean()),
                positive_mean_windows=int(by.signal_mean.gt(0).sum()),complete_label_windows=int(complete.sum()),
                complete_window_only_mean=float(by.loc[complete,'signal_mean'].mean()),
                opening_quote_failures=int((~g.opening_quote_allows_buy).sum()),
                Tuesday_quote_exit_failures=int((~g.Tuesday_quote_allows_exit).sum())))
            for year,yg in by.groupby('year'):
                years.append(dict(endpoint=endpoint,method=method,year=int(year),dates=len(yg),
                                  mean_signal_return=float(yg.signal_mean.mean()),mean_excess_pool=float(yg.mean_excess_pool.mean()),
                                  selected=int(yg.selected.sum()),known=int(yg.known.sum())))
            label_counts.extend(dict(endpoint=endpoint,method=method,label_status=k,count=int(v)) for k,v in g.label_status.value_counts().items())
        for method,column in [('eligible_pool','pool_mean'),('sse','index_mean')]:
            by=pool.copy().sort_values('entry_date')
            by['signal_mean']=by[column]
            by['mean_excess_pool']=by.signal_mean-by.pool_mean
            by['cumulative_mean_sum']=by.signal_mean.cumsum()
            by['cumulative_excess_pool_sum']=by.mean_excess_pool.cumsum()
            by['method']=method
            by['endpoint']=endpoint
            curves.append(by)
            summaries.append(dict(endpoint=endpoint,method=method,signal_dates=len(by),
                                  mean_signal_return=float(by.signal_mean.mean()),mean_excess_pool=float(by.mean_excess_pool.mean())))
            for year,yg in by.groupby('year'):
                years.append(dict(endpoint=endpoint,method=method,year=int(year),dates=len(yg),
                                  mean_signal_return=float(yg.signal_mean.mean()),mean_excess_pool=float(yg.mean_excess_pool.mean())))
    summary=pd.DataFrame(summaries).sort_values(['endpoint','mean_signal_return'],ascending=[True,False])
    annual=pd.DataFrame(years)
    curve=pd.concat(curves,ignore_index=True)
    selected=pd.concat(selections,ignore_index=True)
    summary.to_parquet(OUT/'summary.parquet',index=False)
    annual.to_parquet(OUT/'annual_means.parquet',index=False)
    curve.to_parquet(OUT/'signal_curves.parquet',index=False)
    selected.to_parquet(OUT/'selected_signal_labels.parquet',index=False)
    (OUT/'label_counts.json').write_text(json.dumps(label_counts,ensure_ascii=False,indent=2),encoding='utf-8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    show=['hist_gradient_boosting','reversal5','ridge','liquidity10','random10','eligible_pool']
    colors=['#b65c3c','#2e8273','#786aa4','#4883ac','#999999','#ba9b3f']
    fig,axes=plt.subplots(2,2,figsize=(14,8),layout='constrained',sharex='col')
    for column,endpoint in enumerate(['Friday','Monday']):
        for method,color in zip(show,colors):
            g=curve.loc[curve.endpoint.eq(endpoint)&curve.method.eq(method)].sort_values('entry_date')
            axes[0,column].plot(pd.to_datetime(g.entry_date),g.cumulative_mean_sum*100,label=NAMES[method],color=color,lw=1.25)
            if method!='eligible_pool':
                axes[1,column].plot(pd.to_datetime(g.entry_date),g.cumulative_excess_pool_sum*100,label=NAMES[method],color=color,lw=1.25)
        axes[0,column].set_title(TIMING[endpoint])
        axes[0,column].set_ylabel('逐期平均涨跌幅累加（百分点）')
        axes[1,column].set_ylabel('相对候选池的逐期超额累加（百分点）')
        axes[0,column].legend(fontsize=8,ncol=2)
        for ax in axes[:,column]:
            ax.grid(alpha=.2)
            ax.axhline(0,color='#555',lw=.6)
    fig.suptitle('2021—2023信号平均收益线：每期前10只，期间等权\n普通报价标签的条件毛收益；未知标签保留计数；累加线不是复利净值',fontsize=13)
    fig.savefig(OUT/'signal_mean_curves.png',dpi=160)
    plt.close(fig)
    order=list(summary.loc[summary.endpoint.eq('Monday')&~summary.method.isin(['eligible_pool','sse'])].sort_values('mean_signal_return').method)
    fig,ax=plt.subplots(figsize=(12,7),layout='constrained')
    y=np.arange(len(order))
    for endpoint,offset,color in [('Friday',-.18,'#5288a3'),('Monday',.18,'#ba6d4e')]:
        data=summary.loc[summary.endpoint.eq(endpoint)].set_index('method')
        ax.barh(y+offset,data.loc[order,'mean_excess_pool']*100,height=.34,label=TIMING[endpoint],color=color)
    ax.set_yticks(y,[NAMES[m] for m in order])
    ax.set_xlabel('每期平均收益较同期候选池提升（百分点；毛收益，条件标签）')
    ax.set_title('十种固定筛法的信号提升：相对各自时点的候选池均值')
    ax.axvline(0,color='#555',lw=.8)
    ax.legend()
    ax.grid(axis='x',alpha=.2)
    fig.savefig(OUT/'signal_mean_lift.png',dpi=160)
    plt.close(fig)
    lines=['周五/周一开盘至周二收盘：信号平均收益诊断',
           '用户当前优先目标是提高信号平均收益；资金分配、重复买入和组合仓位暂不假定。两个入场时点分别统计，只用于信号诊断。',
           '初始训练2018—2020，逐年向前验证2021—2023；2024及以后股票行情未使用。此前星期搜索和周一结果已观察，所以是开发比较，不是独立最终验收。',
           '仅沿用10种固定筛法、12因子、前10只、原模型超参数，没有本轮追加阈值/持股数/参数优化。',
           '每期先对已知普通报价标签取股票等权平均，再对时点等权平均；曲线是逐期均值的算术累加，不是复利账户净值。',
           '收益是未扣费用/红利税的普通报价窗口毛价差。公司参考价变化、窗口报价缺失的标签保持未知，不能当0；这里没有为未知标签声称完整经济收益。',
           '所有选中信号均保留。开盘不能买/周二不能卖的标记单独统计，不悄悄删信号；该信号毛收益不能当作可实现交易收益。',
           '', '全部方法：平均每期信号毛收益、相对候选池提升、已知标签覆盖']
    for endpoint in ['Friday','Monday']:
        lines+=['',TIMING[endpoint]]
        for r in summary.loc[summary.endpoint.eq(endpoint)].itertuples():
            coverage=f'{r.known_coverage:.2%}' if np.isfinite(r.known_coverage) else '参照'
            lines.append(f'{NAMES[r.method]} | 每期均值{r.mean_signal_return:+.3%} | 较候选池{r.mean_excess_pool:+.3%} | 覆盖{coverage}')
    lines+=['','逐年：均为每期平均涨跌幅，不是年度账户收益']
    for endpoint in ['Friday','Monday']:
        for method in show:
            a=annual.loc[annual.endpoint.eq(endpoint)&annual.method.eq(method)].set_index('year')
            lines.append(f'{TIMING[endpoint]} {NAMES[method]} | '+' | '.join(f'{y}:{a.loc[y,"mean_signal_return"]:+.3%}(较池{a.loc[y,"mean_excess_pool"]:+.3%})' for y in [2021,2022,2023]))
    lines+=['','覆盖、执行约束与不确定性：未据此新增筛选规则']
    for r in summary.loc[~summary.method.isin(['eligible_pool','sse'])].itertuples():
        lines.append(f'{TIMING[r.endpoint]} {NAMES[r.method]} | {int(r.known)}/{int(r.selected)}已知 | 开盘报价不允许买{int(r.opening_quote_failures)} | 周二报价不允许卖{int(r.Tuesday_quote_exit_failures)} | 完整标签期均值{r.complete_window_only_mean:+.3%} | 较池均值95%块自助区间[{r.excess_pool_block_bootstrap_ci_low:+.3%},{r.excess_pool_block_bootstrap_ci_high:+.3%}]')
    lines+=['','解释边界：同期池参照为该时点所有符合资格股票的已知普通标签均值；不同周五/周一的池、日数不同。',
            '未知标签不均匀可能偏置均值，区间只描述当前样本，未校正多方法选择与历史存活偏差，不能作为确定盈利证据。',
            '下一轮应先固定候选及信号收益定义，再研究因子稳定性；资金与真实执行收益另行核验，不把本线换算成可实现年化。',
            '工程恢复：周五准备脚本曾覆盖四份周一中间表，已用不变的原脚本重建，全部53项原登记哈希恢复一致；原行情与原成交结果未改。',
            '入口：summary.parquet、annual_means.parquet、signal_curves.parquet、selected_signal_labels.parquet、validation.json；图signal_mean_curves.png和signal_mean_lift.png。']
    (OUT/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    registered=list(OUT.glob('*'))+list((BASE/'src_signals').glob('*.py'))
    registration=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        files=[dict(path=str(p.relative_to(BASE)),sha256=digest(p)) for p in sorted(registered) if p.is_file()])
    (OUT/'artifact_registration.json').write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
    print(summary[['endpoint','method','mean_signal_return','mean_excess_pool','known_coverage','opening_quote_failures','Tuesday_quote_exit_failures']].to_string(index=False),flush=True)
    print(annual.loc[annual.method.isin(['hist_gradient_boosting','reversal5','ridge','eligible_pool'])].to_string(index=False),flush=True)
    print('REPORT:',OUT/'REPORT.txt',flush=True)


if __name__=='__main__':
    main()
