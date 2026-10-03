"""Predeclared 72-candidate validation search with one-calendar-month minimum holds."""
from pathlib import Path
from datetime import datetime
import hashlib
import itertools
import json
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss
from threadpoolctl import threadpool_limits
import backtest as base

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'medium_term'
PLAN = dict(initial_cash=100000, data_start='2020-01-01', initial_training_end='2022-12-31',
            validation_start='2023-01-01', validation_end='2024-12-31', final_start='2025-01-01',
            retrain='quarterly expanding, labels fully observed before prediction quarter',
            min_hold='one calendar month from actual execution date',
            families=['logistic', 'hist_gradient_boosting'], horizons=[21,42,63],
            positive_label_return=.05, entry_thresholds=[.45,.55,.65],
            exit_thresholds=[.30,.40], trend_filter=[False,True],
            candidate_count=72, max_validation_drawdown=.45, minimum_validation_closed_positions=2,
            selection='highest validation net total return among eligible candidates; drawdown breaks ties',
            prior_test_exposure='2025+ prices and short-horizon results seen in earlier research; not pristine holdout',
            base_costs={k:base.CONFIG[k] for k in ['commission','minimum_commission','slippage',
                       'dividend_tax_assumption','prior_day_volume_participation']})

def make_features(raw, qfq, horizon):
    x, _, _, _ = base.features(raw, qfq)
    for n in [120]:
        x[f'return_{n}'] = qfq.close.pct_change(n)
        x[f'ma_gap_{n}'] = qfq.close / qfq.close.rolling(n).mean() - 1
        x[f'drawdown_{n}'] = qfq.close / qfq.close.rolling(n).max() - 1
    x['volatility_60'] = qfq.close.pct_change().rolling(60).std()
    x['amount_trend'] = raw.amount.rolling(20).mean() / raw.amount.rolling(60).mean() - 1
    future_return = qfq.open.shift(-(horizon+1)) / qfq.open.shift(-1) - 1
    y = (future_return > PLAN['positive_label_return']).astype(float).where(future_return.notna())
    end = pd.Series(raw.index, index=raw.index).shift(-(horizon+1))
    return x.replace([np.inf,-np.inf], np.nan), y, end

def estimator(family):
    if family == 'logistic':
        return make_pipeline(StandardScaler(), LogisticRegression(C=.1, max_iter=2000, random_state=42))
    return HistGradientBoostingClassifier(max_iter=100, learning_rate=.04, max_depth=2,
                                          max_leaf_nodes=4, min_samples_leaf=40,
                                          l2_regularization=10, early_stopping=False, random_state=42)

def predict(raw, qfq, family, horizon, start, finish=None, save=False):
    x, y, label_end = make_features(raw,qfq,horizon)
    test = raw.loc[start:finish].index
    p = pd.Series(np.nan, index=raw.index, name='probability')
    audit = []
    for quarter in test.to_period('Q').unique():
        dates = test[test.to_period('Q') == quarter]
        train = x.notna().all(axis=1) & y.notna() & (label_end < dates[0])
        assert train.sum() >= 300 and y[train].nunique() == 2
        model = estimator(family)
        with threadpool_limits(limits=1):
            model.fit(x[train], y[train])
            p.loc[dates] = model.predict_proba(x.loc[dates])[:,1]
        audit.append(dict(family=family, horizon=horizon, quarter=str(quarter), rows=int(train.sum()),
                          train_end=str(x.index[train][-1].date()),
                          training_label_end=str(label_end[train].max().date()),
                          prediction_start=str(dates[0].date()), prediction_end=str(dates[-1].date())))
        if save:
            folder = OUT / 'models'
            folder.mkdir(exist_ok=True)
            joblib.dump(model, folder / f'{quarter}.joblib')
    return p,pd.DataFrame(audit),y

def target(probability, qfq, entry, exit_, trend):
    allowed = qfq.close > qfq.close.rolling(120).mean()
    holding = False
    result = []
    for date,p in probability.items():
        if np.isfinite(p):
            if holding and (p <= exit_ or (trend and not allowed.loc[date])):
                holding = False
            elif not holding and p >= entry and (not trend or allowed.loc[date]):
                holding = True
        result.append(int(holding))
    return pd.Series(result,index=probability.index)

def run(raw, signals, name, start, end=None, slippage=.001, save=False):
    curve,trades,blocked,actions = base.simulate(raw,signals,name,slippage=slippage,
                                              start=start,end=end,min_hold_months=1)
    result = base.metrics(curve,trades)
    sells = trades[trades.side.eq('SELL')] if len(trades) else pd.DataFrame()
    if len(sells):
        assert all(pd.Timestamp(row.date) >= pd.Timestamp(row.entry_date) + pd.DateOffset(months=1)
                   for row in sells.itertuples())
    result['closed_positions'] = int((sells.shares_after == 0).sum()) if len(sells) else 0
    result['min_holding_days'] = int(sells.holding_calendar_days.min()) if len(sells) else None
    result['median_holding_days'] = float(sells.holding_calendar_days.median()) if len(sells) else None
    result['max_holding_days'] = int(sells.holding_calendar_days.max()) if len(sells) else None
    result['period_start'] = str(curve.index[0].date())
    result['period_end'] = str(curve.index[-1].date())
    result['open_shares'] = int(curve.shares.iloc[-1])
    if save:
        curve.to_csv(OUT / f'{name}_equity.csv')
        trades.to_csv(OUT / f'{name}_trades.csv',index=False)
        blocked.to_csv(OUT / f'{name}_blocked_orders.csv',index=False)
        actions.to_csv(OUT / f'{name}_corporate_actions.csv',index=False)
    return result,curve,trades

def main():
    OUT.mkdir(exist_ok=True)
    (OUT / 'research_plan.json').write_text(json.dumps(PLAN,ensure_ascii=False,indent=2),encoding='utf-8')
    raw,qfq,manifest = base.load_data()
    # Candidate selection receives only data through 2024, never final-period bars.
    dev_raw,dev_qfq = raw.loc[:PLAN['validation_end']],qfq.loc[:PLAN['validation_end']]
    candidates, cache, audits = [],{},[]
    for family,horizon in itertools.product(PLAN['families'],PLAN['horizons']):
        p,a,_ = predict(dev_raw,dev_qfq,family,horizon,PLAN['validation_start'],PLAN['validation_end'])
        cache[(family,horizon)] = p
        audits.append(a)
        for entry,exit_,trend in itertools.product(PLAN['entry_thresholds'],PLAN['exit_thresholds'],PLAN['trend_filter']):
            signals = target(p,dev_qfq,entry,exit_,trend)
            stats,_,_ = run(dev_raw,signals,'candidate',PLAN['validation_start'],PLAN['validation_end'])
            candidates.append(dict(family=family,horizon=horizon,entry=entry,exit=exit_,trend=trend,**stats))
        print('Validation finished:',family,horizon,flush=True)
    table = pd.DataFrame(candidates)
    table['eligible'] = (table.max_drawdown >= -PLAN['max_validation_drawdown']) & (table.closed_positions >= PLAN['minimum_validation_closed_positions'])
    table = table.sort_values(['eligible','total_return','max_drawdown'],ascending=[False,False,False])
    table.to_csv(OUT / 'validation_candidates.csv',index=False)
    pd.concat(audits,ignore_index=True).to_csv(OUT / 'validation_training_audit.csv',index=False)
    if not table.eligible.any():
        raise RuntimeError('No candidate satisfies predeclared validation constraints; inspect validation_candidates.csv.')
    best = table[table.eligible].iloc[0]
    chosen = dict(family=str(best.family),horizon=int(best.horizon),entry=float(best.entry),
                  exit=float(best['exit']),trend=bool(best.trend))
    selection = dict(selected=chosen,selected_at=datetime.now().isoformat(),
                     validation_metrics=best.to_dict(),selection_data_end=PLAN['validation_end'],
                     input_manifest_sha256=hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest(),
                     code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT / 'selection_frozen.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Parameters frozen BEFORE final evaluation:',chosen,flush=True)
    # Evaluate only the frozen winner on 2025+; later quarterly fits may use then-known earlier labels.
    p,a,y = predict(raw,qfq,chosen['family'],chosen['horizon'],PLAN['final_start'],save=True)
    a.to_csv(OUT / 'final_training_audit.csv',index=False)
    assert (pd.to_datetime(a.training_label_end) < pd.to_datetime(a.prediction_start)).all()
    signal = target(p,qfq,chosen['entry'],chosen['exit'],chosen['trend'])
    pd.DataFrame(dict(probability=p,target=signal,label=y)).to_csv(OUT / 'final_predictions.csv')
    selected,curve,trades = run(raw,signal,'selected_final',PLAN['final_start'],save=True)
    benchmark,bcurve,_ = run(raw,pd.Series(1,index=raw.index),'buy_hold_final',PLAN['final_start'],save=True)
    simple,scurve,_ = run(raw,(qfq.close.rolling(20).mean()>qfq.close.rolling(60).mean()).astype(int),
                         'ma20_60_final',PLAN['final_start'],save=True)
    stressed,_,_ = run(raw,signal,'selected_slippage30bps',PLAN['final_start'],slippage=.003,save=True)
    vp = cache[(chosen['family'],chosen['horizon'])]
    vsignal = target(vp,dev_qfq,chosen['entry'],chosen['exit'],chosen['trend'])
    validation,vcurve,vtrades = run(dev_raw,vsignal,'selected_validation',PLAN['validation_start'],PLAN['validation_end'],save=True)
    val_benchmark,_,_ = run(dev_raw,pd.Series(1,index=dev_raw.index),'buy_hold_validation',PLAN['validation_start'],PLAN['validation_end'],save=True)
    valid = p.notna() & y.notna()
    classification = dict(realized_labels=int(valid.sum()),positive_rate=float(y[valid].mean()),
                          auc=float(roc_auc_score(y[valid],p[valid])),brier=float(brier_score_loss(y[valid],p[valid])))
    # Future-data truncation check on the selected final-period predictor.
    cut = pd.Timestamp('2025-09-30')
    prefix,_,_ = predict(raw.loc[:cut],qfq.loc[:cut],chosen['family'],chosen['horizon'],PLAN['final_start'])
    np.testing.assert_allclose(p.loc[:cut],prefix,equal_nan=True,atol=1e-12)
    years = []
    for name,c in [('selected',curve),('buy_hold',bcurve),('ma20_60',scurve)]:
        previous = base.INITIAL
        for year,values in c.equity.groupby(c.index.year):
            years.append(dict(strategy=name,year=int(year),return_=float(values.iloc[-1]/previous-1)))
            previous = values.iloc[-1]
    pd.DataFrame(years).to_csv(OUT/'yearly_returns.csv',index=False)
    summary = dict(plan=PLAN,chosen=chosen,validation=validation,validation_buy_hold=val_benchmark,
                   final=selected,final_buy_hold=benchmark,final_ma20_60=simple,final_slippage30bps=stressed,
                   classification=classification,latest_probability=float(p.iloc[-1]),latest_target=int(signal.iloc[-1]),
                   candidate_count=len(table),eligible_count=int(table.eligible.sum()),
                   checks=dict(prefix_invariance=True,purged_labels=True,minimum_calendar_month=True),
                   yearly_returns=years)
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    plot(raw,qfq,curve,bcurve,scurve,trades)
    report(summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

def plot(raw,qfq,curve,bcurve,scurve,trades):
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(3,1,figsize=(13,11),constrained_layout=True)
    sample=qfq.loc[PLAN['final_start']:]
    axes[0].plot(sample.index,sample.close,label='前复权收盘',color='gray')
    for side,marker,color in [('BUY','^','red'),('SELL','v','green')]:
        dates=pd.DatetimeIndex(trades.loc[trades.side.eq(side),'date']) if len(trades) else pd.DatetimeIndex([])
        axes[0].scatter(dates,qfq.close.reindex(dates),marker=marker,c=color,s=65,label=side,zorder=5)
    axes[0].set_title('恒银科技 | 中长线模型最终历史评估 | 买入至少满一个自然月')
    for label,c in [('所选模型',curve),('买入持有',bcurve),('20/60均线（月度持仓约束）',scurve)]:
        axes[1].plot(c.index,c.equity/10000,label=label)
        axes[2].plot(c.index,(c.equity/c.equity.cummax().clip(lower=base.INITIAL)-1)*100,label=label)
    axes[1].set_ylabel('账户资产（万元）')
    axes[2].set_ylabel('回撤（%）')
    for ax in axes:
        ax.legend()
        ax.grid(alpha=.2)
    fig.savefig(OUT/'research.png',dpi=160)
    plt.close(fig)

def report(s):
    c=s['chosen']
    lines=['# 恒银科技：10万元、至少持仓一个月的模型回测','',
           f"数据由本目录下载器重新获取，覆盖2020-01-02至{s['final']['period_end']}；与早期短线模型分别保存。",'',
           '## 划分与选模','',
           '- 2020—2022年：初始训练；前120个交易日用于特征预热。',
           '- 2023—2024年：滚动验证并选择参数；因此验证收益存在择优偏差，不应视为独立测试。',
           '- 2025年至数据末日：冻结参数后的最终历史评估，每段账户独立从10万元开始。',
           '- 各季度仅用当时已完整实现的标签重新训练。季度内不再训练，防止未来收益混入特征或标签。',
           '- 2025年以后的行情曾在此前短线研究中被查看，因此本次最终评估不是完全未接触的封存测试；本轮选参程序只接收2024年底以前数据。',
           f"- 预先声明72组候选（两种模型×三个预测周期×三个买入门槛×两个退出门槛×是否趋势过滤），其中{s['eligible_count']}组满足验证期最大回撤不超过45%、至少两次完整平仓的约束；从中选取扣费后累计收益最高者。",'',
           '## 选中的模型','',
           f"模型：{c['family']}；预测未来{c['horizon']}个交易日、从次日开盘起算的复权收益超过5%的概率。使用收益、均线偏离、波动率、成交额、换手等21个因果特征。",
           f"概率达到{c['entry']:.0%}发出持有信号，降至{c['exit']:.0%}及以下发出空仓信号；120日均线过滤{'启用' if c['trend'] else '关闭'}。启用时，买入还要求收盘高于120日均线，跌破则发出退出信号。",
           '实际买入后，满一个自然月前不允许卖出；到期后按最新收盘信号在次日开盘执行。预测周期不等于固定持仓周期，涨跌停或停牌可能延长持仓。一个月内不会因止损信号提前退出。',
           '参数冻结证据：selection_frozen.json；完整候选结果：validation_candidates.csv。','',
           '## 回测结果（均已计费用）','',
           '|阶段/策略|累计收益|年化收益|最大回撤|期末资产|买入/卖出|',
           '|---|---:|---:|---:|---:|---:|']
    for key,label in [('validation','验证期：所选模型'),('validation_buy_hold','验证期：买入持有'),
                      ('final','最终评估：所选模型'),('final_buy_hold','最终评估：买入持有'),
                      ('final_ma20_60','最终评估：20/60均线'),('final_slippage30bps','最终评估：模型滑点0.3%')]:
        m=s[key]
        lines.append(f"|{label}|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_drawdown']:.2%}|{m['final_equity']:,.2f}元|{m['buy_count']}/{m['sell_count']}|")
    m=s['final']
    lines+=['',f"最终评估区间：{m['period_start']} 至 {m['period_end']}。已平仓部分持有天数（自然日）：最短{m['min_holding_days']}、中位数{m['median_holding_days']}、最长{m['max_holding_days']}；期末剩余{m['open_shares']}股。",'',
            '## 最终评估交易明细','', '|买入日期|卖出日期|买入价|卖出价|股数|持有自然日|该轮账户收益|',
            '|---|---|---:|---:|---:|---:|---:|']
    trades=pd.read_csv(OUT/'selected_final_trades.csv')
    previous=base.INITIAL
    for row in trades.loc[trades.side.eq('SELL') & trades.shares_after.eq(0)].itertuples():
        buy=trades.loc[trades.side.eq('BUY') & trades.date.eq(row.entry_date)].iloc[0]
        lines.append(f"|{row.entry_date}|{row.date}|{buy.price:.2f}|{row.price:.2f}|{row.shares}|{row.holding_calendar_days}|{row.cash_after/previous-1:.2%}|")
        previous=row.cash_after
    lines+=['','价格为含模拟滑点的不复权成交价；该轮账户收益包含期间入账的税后分红及交易费用。',
            '', '## 逐年表现','', '|年份|所选模型|买入持有|20/60均线|','|---|---:|---:|---:|']
    table=pd.DataFrame(s['yearly_returns']).pivot(index='year',columns='strategy',values='return_')
    for year,row in table.iterrows():
        lines.append(f"|{year}{'（截至数据末日）' if year==int(m['period_end'][:4]) else ''}|{row['selected']:.2%}|{row['buy_hold']:.2%}|{row['ma20_60']:.2%}|")
    excess=m['total_return']-s['final_buy_hold']['total_return']
    lines+=['','## 结果判断','',
            f"最终评估模型累计收益{m['total_return']:.2%}，相对买入持有收益差{excess:+.2%}（百分点口径）。提高滑点后收益为{s['final_slippage30bps']['total_return']:.2%}。",
            f"最终评估AUC={s['classification']['auc']:.3f}，已实现标签{s['classification']['realized_labels']}个；月度标签大量重叠，不能当作独立观测做显著性推断。",
            '验证期最高收益并不保证以后最高收益。最终区间只有不足两年、单只股票且交易次数有限；结果只代表这一轮历史实验，不能视为稳定收益承诺。',
            f"最近预测概率{s['latest_probability']:.2%}，信号目标{'持有' if s['latest_target'] else '空仓'}；真实模拟持仓还受最低持有期约束。",'',
            '## 交易口径与验证','',
            '本金10万元、不融资、不做空。T日收盘信号、T+1日不复权开盘价成交，买入100股整数倍；开盘涨停不买、跌停不卖，停牌不交易。',
            '佣金双边万三且每笔最低5元；印花税与过户费按历史变更日期处理；默认单边不利滑点0.1%，压力情景0.3%；单笔容量按前一日成交量1%限制，未模拟真实竞价排队。',
            '现金分红依登记日确认、除息日计应收、派息日入账，统一按20%预扣分红税（保守近似）；送转股按上市日解禁。期末按收盘估值，不强制平仓，未计未来清仓费用。现金利息为0。',
            '已验证：数据校验值与交易日、训练标签隔离、截断未来数据后预测不变、最低一个自然月持仓、次日成交、现金守恒、涨跌停、停牌和公司行动边界测试。',
            '强制满月使快速下跌时无法提前止损；45%回撤限制只用于验证期选模，并非最终评估或未来交易的回撤保证。',
            '', '![交易点、净值及回撤](research.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':
    main()
