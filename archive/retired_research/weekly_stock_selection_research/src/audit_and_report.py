"""Audit saved comparison only; no new methods or strategy parameter variants."""
import json
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from common import BASE,AUDIT,SPEC,FACTORS,fee,sha,dump
from execution import buy_order,sell_order
from portfolio import Quotes

NAMES={'random10':'固定随机10只','liquidity10':'流动性优先','momentum20':'20日动量追涨','reversal5':'5日短期反转',
       'lowvol20':'20日低波动','volume_expansion':'量能扩张','range_high':'靠近20日高位','simple_composite':'简单多因子组合',
       'ridge':'岭回归','hist_gradient_boosting':'梯度提升模型','sse_timing_gross':'上证相同时段（毛）'}


def main():
    out=AUDIT/'comparison'
    summary=pd.read_parquet(out/'summary.parquet')
    annual=pd.read_parquet(out/'annual.parquet')
    daily=pd.read_parquet(out/'daily_nav.parquet')
    tx=pd.read_parquet(out/'transactions.parquet')
    trades=pd.read_parquet(out/'trades.parquet')
    scores=pd.read_parquet(AUDIT/'selection_scores_top30.parquet')
    panel=pd.read_parquet(AUDIT/'weekly_factor_panel.parquet')
    events=json.loads((AUDIT/'company_events_conditional.json').read_text(encoding='utf-8'))
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    inputs=BASE/'inputs_pre2025'
    manifest=json.loads((inputs/'kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        if record['rows']:
            assert sha(inputs/'kline_dev_v1'/record['snapshot_file'])==record['snapshot_sha256']
    for source in collection['sources']:
        assert source['ok']
        assert sha(inputs/'corporate_provider_v1'/f"{source['symbol']}_{source['year']}.parquet")==source['sha256']
    q=Quotes()
    for row in tx.itertuples():
        date=pd.Timestamp(row.date)
        i=int(q.days.get_loc(date))
        bar=q.bar(row.symbol,i)
        before=q.bar(row.symbol,i-1)
        if row.side=='buy':
            assert date.weekday()==0 and row.qty%100==0
            assert row.price==bar['open'] and row.qty<=before['volume']*.01
            assert not bar['st'] and bar['active']
            assert row.symbol in set(scores.loc[scores.method.eq(row.method)&scores.monday.eq(row.date),'symbol'])
        else:
            assert date.weekday()==1 and row.price==bar['close'] and row.qty<=before['volume']*.01
            trade=trades.loc[trades.method.eq(row.method)].iloc[row.trade_id]
            assert row.date>trade.entry_date
        assert math.isclose(row.notional,row.qty*row.price,abs_tol=1e-7)
        assert math.isclose(row.fee,fee(row.notional,row.side,row.date),abs_tol=1e-7)
    for (method,trade_id),g in tx.groupby(['method','trade_id']):
        t=trades.loc[trades.method.eq(method)].iloc[trade_id]
        if t.status=='closed':
            assert g.loc[g.side.eq('sell'),'qty'].sum()==t.entry_qty+t.entitled_extra_shares
    # Refit only the already registered2023model as a reproducibility check.
    # Changing all2023outcomes cannot change training, since none are admitted.
    xs=panel.groupby('signal_date')[FACTORS].rank(pct=True,na_option='keep')
    train=panel.label_maturity_date.lt('2023-01-01')&panel.ordinary_quote_excess.notna()
    test=panel.year.eq(2023)
    altered=panel.ordinary_quote_excess.copy()
    altered.loc[test]=999.
    np.testing.assert_array_equal(altered.loc[train],panel.loc[train,'ordinary_quote_excess'])
    med=xs.loc[train].median()
    weights=(1/panel.loc[train].groupby('signal_date').symbol.transform('size')).to_numpy()
    weights/=weights.mean()
    scaler=StandardScaler().fit(xs.loc[train].fillna(med),sample_weight=weights)
    model=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,min_samples_leaf=200,learning_rate=.05,
                                      l2_regularization=10,early_stopping=False,random_state=26027)
    model.fit(scaler.transform(xs.loc[train].fillna(med)),panel.loc[train,'ordinary_quote_excess'],sample_weight=weights)
    verify=panel.loc[test,['signal_date','symbol']].copy()
    verify['score']=model.predict(scaler.transform(xs.loc[test].fillna(med)))
    verify=verify.sort_values(['signal_date','score','symbol'],ascending=[True,False,True])
    verify['rank']=verify.groupby('signal_date').cumcount()+1
    verify=verify.loc[verify['rank'].le(30)]
    stored=scores.loc[scores.year.eq(2023)&scores.method.eq('hist_gradient_boosting')]
    assert list(zip(verify.signal_date,verify.symbol,verify['rank']))==list(zip(stored.signal_date,stored.symbol,stored['rank']))
    np.testing.assert_allclose(verify.score,stored.score,rtol=1e-12,atol=1e-12)
    # Descriptive selection profiles: no outcome-based new filters or factor tuning.
    xs.columns=['percentile_'+c for c in xs.columns]
    profiles=[]
    merged=panel[['symbol','monday']].join(xs)
    for method,g in trades.groupby('method'):
        joined=g[['symbol','entry_date']].merge(merged,left_on=['symbol','entry_date'],right_on=['symbol','monday'],validate='one_to_one')
        profiles.append(dict(method=method,**joined.filter(like='percentile_').mean().to_dict()))
    profile=pd.DataFrame(profiles)
    profile.to_parquet(out/'selection_feature_profiles.parquet',index=False)
    delayed=[]
    concentration=[]
    for method,g in trades.groupby('method'):
        planned=pd.to_datetime(g.entry_date)+pd.Timedelta(days=1)
        late=pd.to_datetime(g.exit_date)>planned
        delayed.append(dict(method=method,delayed_trade_count=int(late.sum()),delayed_trade_pnl=float(g.loc[late,'pnl'].sum()),
                            scheduled_trade_pnl=float(g.loc[~late,'pnl'].sum()),
                            longest_holding_calendar_days=int((pd.to_datetime(g.exit_date)-pd.to_datetime(g.entry_date)).dt.days.max())))
        gains=g.sort_values('pnl',ascending=False)
        concentration.append(dict(method=method,total_pnl=float(g.pnl.sum()),top10_profit_sum=float(gains.head(10).pnl.sum()),
             top10_share_of_total_pnl=float(gains.head(10).pnl.sum()/g.pnl.sum()) if abs(g.pnl.sum())>0 else None))
    dump(out/'delayed_exit_diagnostics.json',delayed)
    dump(out/'profit_concentration.json',concentration)
    # Volume unit check: actual-trade-day average price amount/volume should be
    # near quoted price levels, not100times smaller as with hand-sized volume.
    ratios=[]
    for symbol in tx.symbol.unique()[::max(1,len(tx.symbol.unique())//80)]:
        values,valid,_,_=q.arrays(symbol)
        take=values[valid]
        if len(take):
            ratios.extend((take[:,5]/take[:,4]/take[:,3]).tolist())
    ratio=float(np.median(ratios))
    assert .8<ratio<1.2
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,ax=plt.subplots(figsize=(12,6),layout='constrained')
    ranked=summary.sort_values('cagr')
    x=np.arange(len(ranked))
    colors=['#b76546' if m=='hist_gradient_boosting' else '#537c9e' for m in ranked.method]
    ax.barh(x,ranked.cagr*100,color=colors)
    ax.set_yticks(x,[NAMES[m] for m in ranked.method])
    ax.axvline(0,color='#555',lw=.8)
    ax.set_xlabel('2021—2023全程年化收益（%；扣交易费用、红利税前）')
    ax.set_title('周一开盘买、周二收盘尝试卖：10种固定选股方式\n10只等权目标；零滑点；账户包含无法按期退出的延迟持仓；开发期条件模拟',fontsize=12)
    ax.grid(axis='x',alpha=.2)
    fig.savefig(out/'method_cagr.png',dpi=150)
    plt.close(fig)
    fig,axes=plt.subplots(2,1,figsize=(13,7),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[3,1]})
    show=['hist_gradient_boosting','reversal5','ridge','liquidity10','random10','sse_timing_gross']
    colors=['#b15d3c','#378773','#6a68a2','#507c9c','#888888','#b8a04d']
    for method,color in zip(show,colors):
        g=daily.loc[daily.method.eq(method)]
        curve=np.r_[1e6,g.equity.to_numpy()]
        dd=curve[1:]/np.maximum.accumulate(curve)[1:]-1
        axes[0].plot(pd.to_datetime(g.date),g.equity/1e6,label=NAMES[method],color=color,lw=1.2)
        if method in ['hist_gradient_boosting','reversal5']:
            axes[1].plot(pd.to_datetime(g.date),dd*100,color=color,label=NAMES[method],lw=1)
    axes[0].set_ylabel('账户权益/初始100万元')
    axes[1].set_ylabel('收盘回撤%')
    axes[0].set_title('独立周度选股：2021—2023跨年开发验证\n条件公司行动记账；含交易成本、未扣个人红利税；不是独立未见样本验收')
    axes[0].legend(fontsize=8,ncol=3)
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.savefig(out/'nav_and_drawdown.png',dpi=150)
    plt.close(fig)
    checks=dict(snapshot_files_verified=manifest['nonempty_files'],company_stockyears_verified=len(collection['sources']),
                actual_fills_checked=len(tx),all_buys_Monday_open=True,all_sales_Tuesday_close=True,
                all_actual_prices_costs_lots_and_share_totals_verified=True,
                late_sale_positions_retained=True,final2023model_scores_reproduced=True,
                future2023labels_invariant_for2023training=True,
                median_amount_volume_close_ratio=ratio,volume_unit_consistent_with_shares=True,
                no_post2023price_rows_in_development=True)
    dump(out/'final_validation.json',checks)
    decisions=json.loads((out/'candidate_decisions.json').read_text(encoding='utf-8'))
    passed=[NAMES[r['method']] for r in decisions if r['candidate_gate']]
    lines=['每周一开盘—周二收盘：独立股票筛选研究 v1','= '*36,'',
           '用户已停止方向5，当前研究新建根目录weekly_stock_selection_research。未读取或复用其他策略、模型、生产选择、旧因子及回测；K线/日历来自统一行情入口已提交原始资产，原始行情只读。',
           '这是一轮后验启发的开发研究：交易星期此前已用2015—2026指数数据选过，因此不能宣称完全盲研发或独立最终验收。',
           '', '一、先登记、后计算',
           '事前固定10种方法、10只目标持仓、股票池门槛、时间切分与执行成本，未根据结果改方向、种子、阈值、持股数或模型参数。全部失败方法保留。',
           '原始文件3396份，3312份有边界内记录；研发白名单2018-01-02至2023-12-29，共4382527行。没有读取2024及以后价格来挑方法。现有股票行情从2018起，不能称覆盖2015年以来完整股票历史；历史退市覆盖与存活偏差未核实。',
           '初始训练2018—2020；2021、2022、2023分别只用该年之前已经完整成熟的周度标签训练。原始日历和指数独立采集；不使用当前行业/上市状态映射回填历史。',
           '', '二、交易与信息时点',
           '固定周一开盘买入、周二收盘尝试全部卖出，端点休市则跳过该周。不在其他星期买卖；未能周二退出的持仓保留资金占用，下一周二再尝试，不能假装已经退出。',
           '使用前一实际交易日收盘信息（通常周五，遇休市可为周四），完全不用周一全日K线评分。100万元，最多10只，信号时权益的10%为新仓目标预算，100股整数手；持仓受阻时实际权重可能偏离等权。',
           '信号时正常交易、非ST、累计至少120条有效观测，股价至少3元，近20日有效报价覆盖至少90%，成交额中位数至少2000万元；这是已观察数据资格，不能当作真实上市120日。',
           '开盘涨停保守不买，收盘跌停保守不假设卖出；整笔量不超过前一交易日成交量1%。失败买入留现金，不用后来表现好的候补股替换。未核实的缺行不直接当停牌或0收益。',
           '按用户要求滑点0；佣金双边万三最低5元，过户费2022-04-29前双边十万分之二、后十万分之一，卖出印花税2023-08-28前千分之一、后万分之五。',
           '以下股票收益扣上述交易费用，但股东现金/送股红利为个人差别化红利税前口径，不冒充最终个人税后收益。上证参照为同一2021—2023时段、同一周度日期的零费用指数点位毛收益，资产/费用不同。',
           '', '三、首轮全部方法',
           '随机固定种子、流动性优先、20日动量、5日反转、20日低波动、量能扩张、20日高位、简单组合、岭回归、梯度提升。',
           '简单组合为动量高/波动低/流动性高三个横截面排名等权；模型使用预先登记12个量价因子的当期横截面百分位，预处理只拟合训练期。岭回归alpha10；梯度提升100轮、15叶、最小叶200、学习率0.05、L2=10、关闭提前停止，不做调参搜索。',
           '模型训练目标是可核对普通报价窗口的个股毛价差减同期指数价差，不是直接优化账户净收益。588514条普通标签，1461条公司参考价变化、300条买入报价缺失、177条卖出报价缺失保留未知，未变成开仓前过滤条件；训练标签可用性偏差仍需关注。',
           '', '四、跨年开发比较：2021—2023',
           '方法 | 交易费用后年化（红利税前） | 累计收益 | 收盘最大回撤 | 2021 | 2022 | 2023 | 条件记账完整']
    for r in summary.itertuples():
        a=annual.loc[annual.method.eq(r.method)].set_index('year')
        lines.append(f'{NAMES[r.method]} | {r.cagr:+.2%} | {r.cumulative_return:+.2%} | {r.maximum_drawdown:.2%} | {a.loc[2021,"annual_return"]:+.2%} | {a.loc[2022,"annual_return"]:+.2%} | {a.loc[2023,"annual_return"]:+.2%} | {r.conditional_account_complete}')
    lines += ['', '不能将本表2021—2023的年化与此前2015—2026指数10.55%直接比较；这里同时间上证参照约1.11%。',
              '按事前门槛保留的开发候选：'+('、'.join(passed) if passed else '无')+'。门槛是扣交易成本年化优于随机、流动性及指数参照，并至少2/3年分别超过两个股票基准；不是生产验收。',
              '梯度提升结果最高，但回撤39.11%，2021仅6.28%、2023达73.56%，收益并不均匀；反转法年化12.84%、回撤23.17%，结构更简单；岭回归2023亏损15.44%，跨年风险明显。',
              '本轮固定方向下，动量、近期高位、放量、低波动和简单线性组合均未通过，不根据已看结果把它们反向后再算新成功试验。',
              '', '五、执行成本与无法按时退出',
              '方法 | 买入/失败买入 | 交易费用总元 | 按期退出之外的延迟持仓笔数 | 延迟持仓盈亏元 | 最长日历持仓日']
    delay_map={r['method']:r for r in delayed}
    for r in summary.loc[summary.method.ne('sse_timing_gross')].itertuples():
        d=delay_map[r.method]
        lines.append(f'{NAMES[r.method]} | {int(r.buys)}/{int(r.cancelled_buys)} | {r.fees:.2f} | {d["delayed_trade_count"]} | {d["delayed_trade_pnl"]:+.2f} | {d["longest_holding_calendar_days"]}')
    lines += ['这说明“只在周一/周二下单”能遵守，但无法保证所有实际仓位只持有这两天；跌停、停牌、股份未上市会迫使持有其他日子的风险。收益包含这些真实约束，不能拿它当作纯两日可实现收益。',
              '另存fee_addback_fixed_fills_cumulative_return为在相同实际成交数量下加回费用的毛收益诊断；它没有重新复投费用，不能称为完整零成本复利策略。',
              '', '六、模型实际选股特征与收益集中度',
              '以下为实际买入股票在当期候选池的平均百分位，只描述偏好，不是单因子因果效果，未据此新增筛选规则。']
    hgb=profile.set_index('method').loc['hist_gradient_boosting']
    for feature in FACTORS:
        lines.append(f'{feature}：{hgb["percentile_"+feature]:.1%}')
    hgbc=[r for r in concentration if r['method']=='hist_gradient_boosting'][0]
    lines += [f"梯度提升前10笔盈利合计{hgbc['top10_profit_sum']:.2f}元，占全部净盈亏{hgbc['top10_share_of_total_pnl']:.2%}；完整逐笔明细保留。",
              '', '七、公司行动与独立核验',
              f'新采集{len(collection["sources"])}个实际持股股票-年份原始公司行动查询，全部成功；未借用方向5研究台账。归并{len(events)}条事件，{sum(not e["supported"] for e in events)}条未支持并保留原因；本次实际10个账户路径未触发未解决事件。',
              '普通事件按登记日收盘持股确权、除息日记应收/调整股数、现金支付后才可用、红股上市后才可卖。实际有3笔持仓获得送转股份，不能用送转后每股卖价除原买价当收益。',
              '单供应商历史记录与报价参考价的条件核对并不证明完整公司行动台账或真实交易成交；零返回不被当作完整性证据。结论仍是当前观察股票范围及这些记账假设下的条件估算。',
              f'3312个快照哈希、{len(collection["sources"])}份事件原始数据哈希、{len(tx)}条实际成交价格/数量/费用/星期/股份恒等式均核验；60组历史前缀因子及标签复算一致；2023梯度提升模型独立重拟合，全部前30排名与分数复现。',
              '', '八、当前结论与下一步边界',
              '本轮最有研究价值的是梯度提升与短期反转，岭回归作透明对照。先冻结当前候选及完整成本执行口径，再做新增时期的单向审计；本次未自动读取2024之后的股票行情。',
              '2024及之后的指数时点信息已经参与此前星期搜索，所以以后也不能把它包装成整体完全未观察的最终验证。历史退市覆盖、供应商版本、模型择优、延迟持仓和实际开收盘排队风险仍未消除，不做实盘部署。',
              '', '文件入口',
              'spec.json/registration.json/execution_details_v1.json固定研究规则；inputs_pre2025为独立白名单。',
              'weekly_factor_panel.parquet与training_audit.json是因子、标签可用性和模型时间边界；comparison/保存全部方法的逐年/逐日/逐笔和决策。',
              'comparison/method_cagr.png为全部方法年化；nav_and_drawdown.png为候选与基准曲线；selection_feature_profiles.parquet和profit_concentration.json为解释诊断。',
              '源说明：统一行情入口tools/daily_market_update.py仅复用已提交原始股票数据及只读指数查询；公司行动为新BaoStockoperate-year查询；不使用旧策略代码、模型或结果。']
    (AUDIT/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    public_note='本目录为用户新建的独立股票筛选研究，不恢复旧策略。\n研究规则、进度、完整结果与限制见 audits/holdout_restricted/research_v1/REPORT.txt。\n原行情只读；本目录白名单与来源保留，不是可随意删除的缓存。\n不下单、不部署、不修改生产基线。\n'
    (BASE/'README.txt').write_text(public_note,encoding='utf-8')
    files=[p for p in AUDIT.rglob('*') if p.is_file() and p.name!='artifact_registration.json']
    code=list((BASE/'src').glob('*.py'))
    dump(AUDIT/'artifact_registration.json',dict(spec_sha256=sha(AUDIT/'spec.json'),
         snapshot_manifest_sha256=sha(inputs/'kline_dev_v1/manifest.json'),
         files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(files+code)]))
    print(json.dumps(checks,ensure_ascii=False,indent=2),flush=True)
    print('HGB feature profiles',hgb.to_dict(),flush=True)
    print('delayed exits',json.dumps(delayed,ensure_ascii=False),flush=True)
    print('REPORT: '+str(AUDIT/'REPORT.txt'),flush=True)


if __name__=='__main__':
    main()
