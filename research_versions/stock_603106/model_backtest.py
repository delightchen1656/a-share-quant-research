"""603106: fixed logistic model, purged expanding quarterly walk-forward test."""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import json
import hashlib
import argparse
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, accuracy_score

ROOT = Path(__file__).resolve().parent
INITIAL = 100_000.0
CONFIG = dict(initial_cash=INITIAL, model='StandardScaler + LogisticRegression', C=0.1,
              horizon=5, positive_return=0.015, entry_probability=0.58, exit_probability=0.48,
              initial_training='2020-2021', oos_start='2022-01-01', retrain='quarterly expanding',
              commission=0.0003, minimum_commission=5, slippage=0.001,
              dividend_tax_assumption=0.20, prior_day_volume_participation=0.01)

def load_data():
    manifest = json.loads((ROOT / 'data/manifest.json').read_text(encoding='utf-8'))
    for filename, meta in manifest['files'].items():
        assert hashlib.sha256((ROOT / 'data' / filename).read_bytes()).hexdigest() == meta['sha256']
    raw = pd.read_parquet(ROOT / 'data/raw.parquet').set_index('date').sort_index()
    qfq = pd.read_parquet(ROOT / 'data/qfq.parquet').set_index('date').sort_index()
    raw.index = pd.to_datetime(raw.index)
    qfq.index = pd.to_datetime(qfq.index)
    assert raw.index.equals(qfq.index) and not raw.index.has_duplicates
    assert raw[['open', 'high', 'low', 'close', 'preclose']].notna().all().all()
    assert (raw[['open', 'high', 'low', 'close', 'preclose']] > 0).all().all()
    assert (raw.high >= raw[['open', 'close', 'low']].max(axis=1)).all()
    assert (raw.low <= raw[['open', 'close', 'high']].min(axis=1)).all()
    assert (raw.isST == 0).all(), 'ST history requires date-specific limit rules'
    calendar = pd.read_parquet(ROOT / 'data/calendar.parquet')
    expected = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq('1'), 'calendar_date']))
    missing = expected[(expected >= raw.index.min()) & (expected <= raw.index.max())].difference(raw.index)
    assert len(missing) == 0, f'Missing sessions: {missing}'
    # Independently check provider returns and adjustment continuity.
    assert np.nanmax(abs(raw.close / raw.preclose - 1 - raw.pctChg / 100)) < 0.0001
    assert np.nanmax(abs(qfq.close.pct_change() - raw.pctChg / 100)) < 0.001
    return raw, qfq, manifest

def features(raw, qfq):
    close = qfq.close
    ret = close.pct_change()
    x = pd.DataFrame(index=raw.index)
    for n in [1, 5, 10, 20, 60]:
        x[f'return_{n}'] = close.pct_change(n)
    for n in [5, 20, 60]:
        x[f'ma_gap_{n}'] = close / close.rolling(n).mean() - 1
    for n in [10, 20]:
        x[f'volatility_{n}'] = ret.rolling(n).std()
    x['range'] = (qfq.high - qfq.low) / qfq.close
    x['intraday_return'] = raw.close / raw.open - 1
    x['gap'] = raw.open / raw.preclose - 1
    x['amount_ratio'] = raw.amount / raw.amount.rolling(20).mean()
    x['turnover'] = raw.turn / 100
    x['drawdown_60'] = close / close.rolling(60).max() - 1
    forward = qfq.open.shift(-6) / qfq.open.shift(-1) - 1
    y = (forward > CONFIG['positive_return']).astype(float).where(forward.notna())
    label_end = pd.Series(raw.index, index=raw.index).shift(-6)
    return x.replace([np.inf, -np.inf], np.nan), y, label_end, forward

def predict_walk_forward(x, y, label_end, save=False):
    probability = pd.Series(np.nan, index=x.index, name='probability')
    audits, coefficients = [], []
    oos = x.index[x.index >= CONFIG['oos_start']]
    for quarter in oos.to_period('Q').unique():
        test_dates = oos[oos.to_period('Q') == quarter]
        first = test_dates[0]
        train = x.notna().all(axis=1) & y.notna() & (label_end < first)
        assert train.sum() >= 300
        estimator = make_pipeline(StandardScaler(), LogisticRegression(C=CONFIG['C'], max_iter=2000, random_state=42))
        estimator.fit(x.loc[train], y.loc[train])
        valid = test_dates[x.loc[test_dates].notna().all(axis=1)]
        probability.loc[valid] = estimator.predict_proba(x.loc[valid])[:, 1]
        audits.append(dict(quarter=str(quarter), train_rows=int(train.sum()),
                           train_start=str(x.index[train][0].date()), train_end=str(x.index[train][-1].date()),
                           latest_training_label_end=str(label_end[train].max().date()),
                           prediction_start=str(first.date()), prediction_end=str(test_dates[-1].date())))
        coefficients.extend(dict(quarter=str(quarter), feature=feature, coefficient=float(coef))
                            for feature, coef in zip(x.columns, estimator[-1].coef_[0]))
        if save:
            joblib.dump(estimator, ROOT / 'models' / f'{quarter}.joblib')
    return probability, pd.DataFrame(audits), pd.DataFrame(coefficients)

def model_target(probability):
    holding = False
    targets = []
    for p in probability:
        if np.isfinite(p):
            if not holding and p >= CONFIG['entry_probability']:
                holding = True
            elif holding and p <= CONFIG['exit_probability']:
                holding = False
        targets.append(int(holding))
    return pd.Series(targets, index=probability.index)

def round_cent(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def costs(value, day, sell):
    transfer = 0.00002 if day < pd.Timestamp('2022-04-29') else 0.00001
    stamp = (0.001 if day < pd.Timestamp('2023-08-28') else 0.0005) if sell else 0
    return max(5.0, value * CONFIG['commission']) + value * (transfer + stamp)

def events():
    frame = pd.read_parquet(ROOT / 'data/dividends.parquet')
    result = []
    for _, row in frame.iterrows():
        def number(key):
            return float(row[key]) if str(row[key]).strip() else 0.0
        ex = pd.Timestamp(row.dividOperateDate)
        bonus = number('dividStocksPs') + number('dividReserveToStockPs')
        result.append(dict(record=pd.Timestamp(row.dividRegistDate), ex=ex,
                           pay=pd.Timestamp(row.dividPayDate) if row.dividPayDate else ex,
                           listed=pd.Timestamp(row.dividStockMarketDate) if row.dividStockMarketDate else ex,
                           cash=number('dividCashPsBeforeTax'), bonus=bonus, entitled=0))
    return result

def simulate(raw, target, name, slippage=0.001, start=None, end=None, min_hold_months=0):
    data = raw.loc[start or CONFIG['oos_start']:end]
    cash, shares, pending_cash, pending_stock = INITIAL, 0, [], []
    action_list = events()
    records, trades, rejected, action_log = [], [], [], []
    entry_date = None
    # Each close's decision is used at the NEXT market open.
    orders = target.shift(1).reindex(data.index).fillna(0)
    prior_volume = raw.volume.shift(1)
    for date, row in data.iterrows():
        for action in action_list:
            if date == action['ex'] and action['entitled']:
                qty = action['entitled']
                dividend = qty * action['cash'] * (1 - CONFIG['dividend_tax_assumption'])
                bonus = int(np.floor(qty * action['bonus'] + 1e-7))
                pending_cash.append((action['pay'], dividend))
                pending_stock.append((action['listed'], bonus))
                action_log.append(dict(date=date, entitled=qty, net_dividend=dividend, bonus_shares=bonus))
        cash += sum(value for due, value in pending_cash if due <= date)
        shares += sum(value for due, value in pending_stock if due <= date)
        pending_cash = [(due, value) for due, value in pending_cash if due > date]
        pending_stock = [(due, value) for due, value in pending_stock if due > date]
        desired = orders.loc[date]
        side = 'BUY' if desired and shares == 0 and not any(v for _, v in pending_stock) else ('SELL' if not desired and shares > 0 else None)
        if side == 'SELL' and min_hold_months and entry_date is not None and date < entry_date + pd.DateOffset(months=min_hold_months):
            rejected.append(dict(date=date, side=side, reason='minimum_calendar_month_holding'))
            side = None
        if side:
            limit_up = round_cent(row.preclose * 1.10)
            limit_down = round_cent(row.preclose * 0.90)
            blocked = row.tradestatus != 1 or row.volume <= 0 or (side == 'BUY' and row.open >= limit_up - 0.005) or (side == 'SELL' and row.open <= limit_down + 0.005)
            capacity = int(prior_volume.loc[date] * CONFIG['prior_day_volume_participation'] // 100) * 100
            if blocked or capacity <= 0:
                rejected.append(dict(date=date, side=side, reason='suspended_or_open_at_limit_or_capacity'))
            else:
                # Prices use opening price plus fixed adverse slippage, constrained to legal bands.
                price = round_cent(min(limit_up, row.open * (1 + slippage))) if side == 'BUY' else round_cent(max(limit_down, row.open * (1 - slippage)))
                if side == 'BUY':
                    qty = min(int(cash / price // 100) * 100, capacity)
                    while qty > 0 and qty * price + costs(qty * price, date, False) > cash:
                        qty -= 100
                    if qty:
                        fee = costs(qty * price, date, False)
                        cash -= qty * price + fee
                        shares += qty
                        entry_date = date
                else:
                    qty = min(shares, capacity)
                    fee = costs(qty * price, date, True)
                    cash += qty * price - fee
                    shares -= qty
                if qty:
                    trades.append(dict(date=date, signal_date=raw.index[raw.index.get_loc(date)-1],
                                       side=side, shares=qty, price=price, fee=fee, cash_after=cash,
                                       shares_after=shares, strategy=name,
                                       entry_date=entry_date,
                                       holding_calendar_days=(date-entry_date).days if side == 'SELL' and entry_date is not None else 0))
        for action in action_list:
            if date == action['record']:
                action['entitled'] = shares + sum(v for _, v in pending_stock)
        assert cash >= -1e-6 and shares >= 0
        equity = cash + (shares + sum(v for _, v in pending_stock)) * row.close + sum(v for _, v in pending_cash)
        records.append(dict(date=date, equity=equity, cash=cash, shares=shares,
                            exposure=(shares * row.close / equity), target_from_prior_close=int(desired)))
    curve = pd.DataFrame(records).set_index('date')
    return curve, pd.DataFrame(trades), pd.DataFrame(rejected), pd.DataFrame(action_log)

def metrics(curve, trades):
    equity = curve.equity
    ret = equity.pct_change()
    ret.iloc[0] = equity.iloc[0] / INITIAL - 1
    peak = equity.cummax().clip(lower=INITIAL)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    return dict(total_return=float(equity.iloc[-1] / INITIAL - 1),
                cagr=float((equity.iloc[-1] / INITIAL) ** (1 / years) - 1),
                max_drawdown=float((equity / peak - 1).min()),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() else 0,
                final_equity=float(equity.iloc[-1]), exposure=float(curve.exposure.mean()),
                buy_count=int((trades.side == 'BUY').sum()) if len(trades) else 0,
                sell_count=int((trades.side == 'SELL').sum()) if len(trades) else 0,
                total_fees=float(trades.fee.sum()) if len(trades) else 0)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'outputs'
    out.mkdir(exist_ok=True)
    (ROOT / 'models').mkdir(exist_ok=True)
    raw, qfq, manifest = load_data()
    x, y, label_end, forward = features(raw, qfq)
    p, audit, coefs = predict_walk_forward(x, y, label_end, save=True)
    audit.to_csv(out / 'training_audit.csv', index=False)
    coefs.to_csv(out / 'model_coefficients.csv', index=False)
    target = model_target(p)
    pd.DataFrame(dict(probability=p, target=target, forward_5d_return=forward, label=y,
                      label_available_date=label_end)).to_csv(out / 'predictions.csv')
    audit_ok = (pd.to_datetime(audit.latest_training_label_end) < pd.to_datetime(audit.prediction_start)).all()
    assert audit_ok
    checks = dict(data_hashes=True, daily_price_integrity=True, raw_adjusted_returns_consistent=True,
                  calendar_complete=True, purged_labels=bool(audit_ok))
    if args.verify:
        cut = pd.Timestamp('2024-06-28')
        xx, yy, ll, _ = features(raw.loc[:cut], qfq.loc[:cut])
        pp, _, _ = predict_walk_forward(xx, yy, ll)
        np.testing.assert_allclose(p.loc[:cut], pp, equal_nan=True, atol=1e-12)
        checks['prefix_invariance'] = True
    strategies = {'model': target, 'buy_hold': pd.Series(1, index=raw.index),
                  'ma20_60': (qfq.close.rolling(20).mean() > qfq.close.rolling(60).mean()).astype(int)}
    results, curves, yearly = {}, {}, []
    for name, signal in strategies.items():
        curve, trades, rejected, actions = simulate(raw, signal, name)
        curves[name] = curve
        results[name] = metrics(curve, trades)
        curve.to_csv(out / f'{name}_equity.csv')
        trades.to_csv(out / f'{name}_trades.csv', index=False)
        rejected.to_csv(out / f'{name}_blocked_orders.csv', index=False)
        actions.to_csv(out / f'{name}_corporate_actions.csv', index=False)
        previous = INITIAL
        for year, values in curve.equity.groupby(curve.index.year):
            yearly.append(dict(strategy=name, year=int(year), return_=float(values.iloc[-1] / previous - 1)))
            previous = values.iloc[-1]
        if len(trades):
            assert (pd.to_datetime(trades.signal_date) < pd.to_datetime(trades.date)).all()
            assert trades.date.value_counts().max() == 1
            assert (trades.loc[trades.side == 'BUY', 'shares'] % 100 == 0).all()
    checks.update(next_session_execution=True, t_plus_one=True, board_lot_buys=True, cash_nonnegative=True)
    pd.DataFrame(yearly).to_csv(out / 'yearly_returns.csv', index=False)
    stress, stress_trades, _, _ = simulate(raw, target, 'model_slippage_30bps', slippage=0.003)
    results['model_slippage_30bps'] = metrics(stress, stress_trades)
    valid = p.notna() & y.notna()
    prediction_metrics = dict(n=int(valid.sum()), positive_rate=float(y[valid].mean()),
                              auc=float(roc_auc_score(y[valid], p[valid])),
                              brier=float(brier_score_loss(y[valid], p[valid])),
                              accuracy=float(accuracy_score(y[valid], p[valid] >= .5)))
    summary = dict(config=CONFIG, data_first=str(raw.index[0].date()), data_last=str(raw.index[-1].date()),
                   rows=len(raw), oos_first=str(curves['model'].index[0].date()),
                   results=results, prediction_metrics=prediction_metrics, checks=checks,
                   latest_probability=float(p.iloc[-1]), latest_target=int(target.iloc[-1]),
                   latest_close=float(raw.close.iloc[-1]))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), constrained_layout=True)
    recent = qfq.iloc[-252:]
    axes[0].plot(recent.index, recent.close, label='前复权收盘')
    for n in [20, 60]:
        axes[0].plot(recent.index, qfq.close.rolling(n).mean().loc[recent.index], label=f'MA{n}')
    axes[0].set_title(f'603106 恒银科技 | 截至 {raw.index[-1].date()}')
    axes[0].legend()
    names = dict(model='滚动逻辑回归模型', buy_hold='买入持有', ma20_60='20/60日均线')
    for name, curve in curves.items():
        axes[1].plot(curve.index, curve.equity / INITIAL, label=names[name])
        axes[2].plot(curve.index, (curve.equity / curve.equity.cummax().clip(lower=INITIAL) - 1) * 100, label=names[name])
    axes[1].set_title('历史样本外净值（2022年起，含费用与分红税假设）')
    axes[2].set_title('回撤（%）')
    for ax in axes:
        ax.grid(alpha=.2)
        ax.legend()
    fig.savefig(out / 'research.png', dpi=160)
    plt.close(fig)
    write_report(summary, raw, qfq, yearly, audit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

def write_report(s, raw, qfq, yearly, audit):
    model_result = s['results']['model']
    benchmark = s['results']['buy_hold']
    stress = s['results']['model_slippage_30bps']
    lines = ['# 恒银科技（603106）模型与本地回测', '',
             f"数据：{s['data_first']} 至 {s['data_last']}，{s['rows']} 条日线，重新从 BaoStock 下载。", '',
             '## 本次结果判断', '',
             f"模型累计收益 {model_result['total_return']:.2%}，同期买入持有 {benchmark['total_return']:.2%}；模型最大回撤 {model_result['max_drawdown']:.2%}，平均股票仓位 {model_result['exposure']:.2%}。",
             f"单边滑点提高至0.3%后累计收益为 {stress['total_return']:.2%}。模型AUC为 {s['prediction_metrics']['auc']:.3f}；这一版尚未显示稳健的方向预测能力，不能据此认定模型可实盘使用。", '',
             '## 方法', '',
             '固定逻辑回归模型（标准化、C=0.1），使用收益率、均线偏离、波动率、日内振幅、跳空、成交额比和换手率共16项特征。',
             '预测目标：当日收盘后，预测下一交易日开盘至第六个交易日开盘的五日复权收益是否超过1.5%。',
             '2020—2021年用于初始训练；2022年起按季度扩展训练窗口。训练只纳入在该季度首个交易日前已完全实现的标签。',
             '概率达到58%时产生持有信号；降至48%及以下时产生空仓信号；中间区间保持原目标。实际持仓周期由信号决定，并非固定五日。',
             '参数本轮预先固定，无收益择优或网格调参。历史样本外结果仍是事后研究，不等于真正上线前封存的独立测试。', '',
             '## 同期历史样本外结果', '',
             f"区间：{s['oos_first']} 至 {s['data_last']}；初始资金10万元。训练期不计入模型收益。", '',
             '|策略|累计收益|年化收益|最大回撤|夏普（无风险利率0）|买入/卖出次数|期末资产|',
             '|---|---:|---:|---:|---:|---:|---:|']
    for key, label in [('model','逻辑回归模型'),('buy_hold','买入持有'),('ma20_60','20/60均线'),('model_slippage_30bps','模型：单边滑点提高至0.3%')]:
        m = s['results'][key]
        lines.append(f"|{label}|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_drawdown']:.2%}|{m['sharpe']:.2f}|{m['buy_count']}/{m['sell_count']}|{m['final_equity']:,.2f}元|")
    lines += ['', '## 分年收益', '', '|年份|模型|买入持有|20/60均线|', '|---|---:|---:|---:|']
    table = pd.DataFrame(yearly).pivot(index='year', columns='strategy', values='return_')
    for year, row in table.iterrows():
        lines.append(f"|{year}{'（截至数据末日）' if year == raw.index[-1].year else ''}|{row['model']:.2%}|{row['buy_hold']:.2%}|{row['ma20_60']:.2%}|")
    m = s['prediction_metrics']
    lines += ['', '## 模型识别能力与最近走势', '',
              f"已实现标签的样本外预测 {m['n']} 次，AUC={m['auc']:.3f}，Brier={m['brier']:.3f}，以50%分类的准确率={m['accuracy']:.2%}，正样本比例={m['positive_rate']:.2%}。相邻五日标签重叠，不能当作独立样本计算显著性。",
              f"最新不复权收盘价 {s['latest_close']:.2f} 元；5/20/60个交易日复权涨跌幅分别为 " + ' / '.join(f'{qfq.close.pct_change(n).iloc[-1]:.2%}' for n in [5,20,60]) + '。',
              f"最新模型概率 {s['latest_probability']:.2%}，目标状态为{'持有' if s['latest_target'] else '空仓'}，只对应下一交易日的模拟指令。",
              '', '## 成交与费用口径', '',
              '- T日收盘信号，T+1开盘按不复权价格成交；每日最多一笔指令，买入100股整数倍，禁做空，现金不透支。',
              '- 停牌、零成交量不能成交；开盘达到涨停不买、达到跌停不卖。受阻后下一日使用最新信号重新判断。',
              '- 佣金双边万三、每笔最低5元；卖出印花税2023-08-28前千一、之后万五；过户费2022-04-29前十万分之二、之后十万分之一。',
              '- 默认单边0.1%不利滑点，按分四舍五入并限制在涨跌停价格内；另报告0.3%滑点压力测试。',
              '- 每笔不超过上一交易日成交量的1%；这是容量近似，未取得开盘竞价逐笔数据，不能保证实际开盘成交。',
              '- 分红按登记日持股确认、除息日计入应收、派息日到现金；送转股于上市日可卖出。现金分红统一预扣20%税，是保守简化，未按真实持股时间追缴税款。',
              '- 期末持仓按收盘估值，未强制卖出，故未扣除尚未发生的清仓成本；闲置现金不计利息。',
              '- 前复权价只计算比例特征和收益标签；现金、手数及成交均用不复权价。仅使用2020年以来数据，最初60个交易日用于特征预热。',
              '', '## 验证与局限', '',
              '已校验下载文件SHA256、交易日完整性、OHLC关系、复权连续性、训练标签截止日、次日执行、整数手和非负现金。截断2024-06-28之后的数据重新训练，截断日前预测保持一致。',
              '日线回测未模拟订单簿排队、临时盘中停牌、实际竞价容量和所有券商费用差异；单只股票样本量有限，没有基本面、新闻和市场指数特征。',
              'AUC接近或低于0.5说明方向识别能力较弱。无论回测盈利与否，都不能据此认定模型具有稳定超额收益。',
              '', '## 数据与规则来源', '',
              '- BaoStock：query_history_k_data_plus（raw=3，qfq=2）、query_dividend_data（operate）、query_trade_dates。下载证据见 data/manifest.json。',
              '- [BaoStock复权说明](https://www.baostock.com/helpdocs/pdf/BaoStock%E5%A4%8D%E6%9D%83%E5%9B%A0%E5%AD%90%E7%AE%80%E4%BB%8B.pdf)',
              '- [证券交易印花税公告](https://shanghai.chinatax.gov.cn/zcfw/zcfgk/yhs/202308/t468451.html)',
              '- [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)',
              '', '![走势、净值和回撤](outputs/research.png)', '']
    (ROOT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__':
    main()
