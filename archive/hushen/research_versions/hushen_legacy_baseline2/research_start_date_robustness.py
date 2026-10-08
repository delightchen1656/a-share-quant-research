"""Diagnostic only: fresh cash per start, no parameter selection or promotion.

Uses existing month-start factors, NOT exact day-of-month anchored schedules.
Minute execution parity is not established. Old baseline files remain untouched.
"""
import json
import numpy as np
import pandas as pd
import group_research as g
from approximate_parity_gate import compare, LIMITS, EXPORT

OUT = g.HERE / 'start_date_robustness_100k'


def measure(curve):
    equity = np.r_[100000., curve.equity.to_numpy(float)]
    returns = equity[1:] / equity[:-1] - 1
    years = max((curve.date.iloc[-1] - curve.date.iloc[0]).days / 365.25, 1 / 365.25)
    return dict(final_equity=float(equity[-1]),
                annualized=float((equity[-1] / equity[0]) ** (1 / years) - 1),
                drawdown=float((equity / np.maximum.accumulate(equity) - 1).min()),
                sharpe=float(np.sqrt(252) * returns.mean() / returns.std(ddof=1))
                if returns.std(ddof=1) > 0 else 0.)


def main():
    OUT.mkdir(exist_ok=True)
    protocol = dict(capital=100000, tests='diagnostic; no tuning or winner selection',
        starts='every cached month-start 2020-01 through 2024-08; independent empty account',
        schedules=['original_fixed_quarters', 'entry_month_phase_quarters'],
        horizon='24 calendar months and common data endpoint, reported separately',
        caution=['Phase schedule uses first trading session of months, NOT exact deployed day-anchored version.',
                 'Overlapping windows are dependent, not independent validation samples.',
                 'All history previously inspected; no pristine out-of-sample claim.',
                 'Daily open execution proxy; no minute data; inherited corporate-action and universe limitations.',
                 'No optimization/promotion until platform parity gate is met.'],
        later_research='After parity: exact anchor dates, weekday/month-end offsets, 12/24/36-month windows; development through 2023, 2024 onward audit only. Prefer median and lower-tail performance, not best start.')
    (OUT/'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    # Recompute the existing independent gate from saved series, not screenshot totals.
    local = pd.read_csv(g.HERE/'approximate_parity_100k/include_small_corporate_actions_equity.csv', parse_dates=['date'])
    platform = pd.read_csv(EXPORT/'platform_daily_equity.csv', parse_dates=['date'])
    gate, _ = compare(local, platform)
    (OUT/'alignment_gate.json').write_text(json.dumps(dict(limits=LIMITS, result=gate), indent=2), encoding='utf-8')
    f = g.features()
    ranks = g.bt.ranked_months(f, (.25, .20, .55), (.65, .25, .10), 120)
    idx = pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date'] = pd.to_datetime(idx.date)
    idx = idx.sort_values('date')
    for day, x in list(ranks.items()):
        hist = idx[idx.date <= x.signal_date.iloc[0]]
        strong = bool(hist.close.iloc[-1] > hist.close.tail(120).mean())
        q = x if strong else g.score(x[x.float_cap_proxy_group == 1], 'quality')
        ranks[day] = q.sort_values(['score', 'symbol'], ascending=[False, True])
    union = set().union(*(set(x.head(24).symbol) for x in ranks.values()))
    panel = g.bt.load_daily_panel(union)
    old_start, old_cash, old_action = g.bt.START, g.bt.INITIAL_CASH, g.bt.apply_corporate_action
    def small_actions(cash, positions, day, previous):
        cash = old_action(cash, positions, day, previous)
        for symbol, qty in positions.items():
            if symbol not in day.index or symbol not in previous:
                continue
            pre = float(day.loc[symbol, 'preclose'])
            if np.isfinite(pre) and pre > 0 and 1 + 1e-8 < previous[symbol] / pre <= 1.02:
                cash += qty * (previous[symbol] - pre)
        return cash
    g.bt.INITIAL_CASH = 100000.
    g.bt.apply_corporate_action = small_actions
    starts = sorted(d for d in ranks if d <= pd.Timestamp('2024-08-31'))
    rows = []
    try:
        for i, start in enumerate(starts, 1):
            g.bt.START = start
            for mode in protocol['schedules']:
                phase = 0 if mode == 'original_fixed_quarters' else (start.month - 1) % 3
                rr = {d: x for d, x in ranks.items() if d >= start and (d.month - 1) % 3 == phase}
                curve, trades = g.bt.simulate(rr, .05, 8, 24, .8, 1.5, panel, min_adjustment=3000)
                if i == 1:
                    assert np.allclose(curve.equity, local.equity, atol=.01, rtol=0), 'control drift'
                assert curve.date.iloc[0] == start
                for horizon in ('24_months', 'common_end'):
                    z = curve[curve.date < start + pd.DateOffset(months=24)] if horizon == '24_months' else curve
                    t = trades[trades.date <= z.date.iloc[-1]]
                    row = dict(schedule=mode, start=str(start.date()), end=str(z.date.iloc[-1].date()),
                               horizon=horizon, **measure(z), orders=len(t),
                               fees=float((t.commission+t.stamp_tax).sum()),
                               mean_cash_fraction=float((z.cash/z.equity).mean()))
                    rows.append(row)
            (OUT/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print('START', i, len(starts), start.date(), flush=True)
    finally:
        g.bt.START, g.bt.INITIAL_CASH, g.bt.apply_corporate_action = old_start, old_cash, old_action
    summaries = []
    frame = pd.DataFrame(rows)
    for (mode, horizon), q in frame.groupby(['schedule', 'horizon']):
        summaries.append(dict(schedule=mode, horizon=horizon, count=len(q),
            median_annualized=float(q.annualized.median()), p10_annualized=float(q.annualized.quantile(.1)),
            worst_annualized=float(q.annualized.min()), best_annualized=float(q.annualized.max()),
            worst_drawdown=float(q.drawdown.min()), median_sharpe=float(q.sharpe.median()),
            loss_fraction=float((q.final_equity < 100000).mean())))
    (OUT/'summary.json').write_text(json.dumps(summaries, indent=2), encoding='utf-8')
    lines = ['# 基准2多起点诊断（非优化、非平台复现）', '',
        '平台近似对齐未通过，暂不选择或晋升新参数。数据终点为2026-09-11。',
        '每个起点重新投入10万元、空仓重跑，不是截取老净值曲线。',
        '月份相位版是研究对照，不是已交付的同日季度版。旧基准未修改。', '',
        '| 日程 | 窗口 | 起点数 | 年化中位数 | 年化P10 | 最差年化 | 最好年化 | 最差回撤 | Sharpe中位数 |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for x in summaries:
        lines.append('| %s | %s | %d | %.2f%% | %.2f%% | %.2f%% | %.2f%% | %.2f%% | %.3f |' % (
            x['schedule'], x['horizon'], x['count'], x['median_annualized']*100,
            x['p10_annualized']*100, x['worst_annualized']*100, x['best_annualized']*100,
            x['worst_drawdown']*100, x['median_sharpe']))
    lines += ['', '共同终点的持有期不同，仅作辅助；24个月窗口用于等期限比较。',
        '窗口重叠且历史已反复使用，不能把起点数当独立样本数。结果仍受日线撮合代理、除权近似和非完整时点股票池影响。',
        '下一步需取得平台序号1、4、5完整源码、设置、交易明细、每日持仓；先统一起止日期，定位首笔分歧，再做精确日期锚点测试和受限参数研究。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(summaries, indent=2), flush=True)


if __name__ == '__main__':
    main()
