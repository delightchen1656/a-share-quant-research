"""Bounded multi-entry-date research under an explicitly approximate local engine."""
import json
import numpy as np
import pandas as pd
import group_research as g
from start_date_robustness import measure

OUT = g.HERE / 'monthly_robust_tuning_100k'
BASE = dict(cadence='monthly', signal='regime', buffer=24, minimum=3000, count=8, power=1.)
CONFIGS = [
    dict(BASE, name='control', label='原月度8只'),
    dict(BASE, name='count6', label='月度6只', count=6),
    dict(BASE, name='count10', label='月度10只', count=10),
    dict(BASE, name='buffer16', label='保留区间16只', buffer=16),
    dict(BASE, name='buffer32', label='保留区间32只', buffer=32),
    dict(BASE, name='minimum5000', label='小额调整门槛5000元', minimum=5000),
    dict(BASE, name='risk_half', label='减弱风险权重', power=.5),
]


def dump(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def summarize(rows):
    q = pd.DataFrame(rows)
    return dict(count=len(q), median=float(q.annualized.median()), p10=float(q.annualized.quantile(.1)),
                worst=float(q.annualized.min()), drawdown=float(q.drawdown.min()),
                sharpe=float(q.sharpe.median()), fees=float(q.fees.median()))


def main():
    OUT.mkdir(exist_ok=True)
    dump('protocol.json', dict(configs=CONFIGS, cash=100000, holdings=8, exposure=.8,
        development='monthly starts 2020-2021; each 24 months, all observations end before 2024',
        audit='monthly starts Jan-Aug 2024, each 24 months; already-seen history, not pristine OOS',
        selection='Development only: P10 improvement, median >= control-1pp, worst MDD >= control-2pp; rank P10 then median. Freeze one finalist before audit. No audit-driven reselection.',
        stress='Finalist and control: double commission, minimum commission and slippage; stamp tax unchanged.',
        acceptance='Audit P10 improvement, median >= control-1pp, worst MDD >= control-2pp, and stress P10 improvement in both periods.',
        schedule_scope='Monthly first-session cache proxy, NOT exact next-session/day-of-month deployed version.',
        approximation='User authorizes provisional research despite failed parity. Keep small-corporate-action correction, 0.2% one-way slippage and original fees; no fitting to screenshot returns. Daily opening-price proxy, not minute replication.',
        limitations=['Fixed historical universe and approximate corporate actions.', 'Overlapping windows are dependent.',
                     'Month-start signals only; no claim of arbitrary day-of-month robustness.',
                     'No baseline overwrite, no automatic platform promotion.']))
    f = g.features()
    base = g.bt.ranked_months(f, (.25, .2, .55), (.65, .25, .1), 120)
    idx = pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date'] = pd.to_datetime(idx.date)
    idx = idx.sort_values('date')
    ranksets = {name: {} for name in ('regime', 'quality', 'trend')}
    for day, x in base.items():
        hist = idx[idx.date <= x.signal_date.iloc[0]]
        strong = hist.close.iloc[-1] > hist.close.tail(120).mean()
        q = x if strong else g.score(x[x.float_cap_proxy_group == 1], 'quality')
        ranksets['regime'][day] = q.sort_values(['score', 'symbol'], ascending=[False, True])
        ranksets['quality'][day] = g.score(x, 'quality')
        ranksets['trend'][day] = g.score(x, 'trend')
    union = set().union(*(set(x.head(32).symbol) for rr in ranksets.values() for x in rr.values()))
    panel = g.bt.load_daily_panel(union)
    original = {n: getattr(g.bt, n) for n in ('START', 'END', 'INITIAL_CASH', 'SLIPPAGE', 'COMMISSION', 'MIN_COMMISSION', 'apply_corporate_action')}
    def action(cash, positions, day, previous):
        cash = original['apply_corporate_action'](cash, positions, day, previous)
        for s, qty in positions.items():
            if s not in day.index or s not in previous:
                continue
            pre = float(day.loc[s, 'preclose'])
            if np.isfinite(pre) and pre > 0 and 1+1e-8 < previous[s]/pre <= 1.02:
                cash += qty*(previous[s]-pre)
        return cash
    g.bt.apply_corporate_action = action
    g.bt.INITIAL_CASH = 100000.
    rows = []
    starts = dict(dev=[d for d in base if d.year in (2020, 2021)],
                  audit=[d for d in base if d.year == 2024 and d.month <= 8])
    def run(cfg, start, split, stress=False, full=False):
        g.bt.START = start
        g.bt.END = original['END'] if full else start + pd.DateOffset(months=24) - pd.Timedelta(days=1)
        if split == 'dev':
            assert g.bt.END < pd.Timestamp('2024-01-01')
        for field in ('SLIPPAGE', 'COMMISSION', 'MIN_COMMISSION'):
            setattr(g.bt, field, original[field] * (2 if stress else 1))
        rr = {}
        for d, x in ranksets[cfg['signal']].items():
            if d < start or d > g.bt.END:
                continue
            mode = cfg['cadence']
            include = mode == 'monthly' or (mode in ('fixed', 'entry_fixed') and d.month in (1, 4, 7, 10))
            include |= mode == 'entry_fixed' and d == start
            include |= mode == 'bimonth' and (d.month-start.month) % 2 == 0
            if include:
                q = x.copy()
                q['downside'] = q.downside.pow(cfg['power'])
                rr[d] = q
        curve, trades = g.bt.simulate(rr, .05, cfg['count'], cfg['buffer'], .8, 1.5, panel, min_adjustment=cfg['minimum'])
        assert (curve.cash >= -.01).all()
        assert len(trades) and (trades[trades.side == 'BUY'].quantity % 100 == 0).all()
        assert trades[trades.side == 'BUY'].merge(trades[trades.side == 'SELL'], on=['date', 'symbol']).empty
        row = dict(name=cfg['name'], split=split, stress=stress, start=str(start.date()),
                   end=str(curve.date.iloc[-1].date()), **measure(curve), orders=len(trades),
                   fees=float((trades.commission+trades.stamp_tax).sum()))
        if cfg['name'] == 'control' and split == 'dev' and not stress:
            prior = json.loads((g.HERE/'robust_policy_search_100k/window_results.json').read_text(encoding='utf-8'))
            oldrow = next(z for z in prior if z['name']=='monthly' and z['split']=='dev' and not z['stress'] and z['start']==str(start.date()))
            assert abs(row['final_equity']-oldrow['final_equity']) < .01, 'monthly control mismatch'
        rows.append(row)
        dump('window_results.json', rows)
        if full:
            dump(cfg['name']+'_full_curve.json', json.loads(curve.to_json(orient='records', date_format='iso')))
            dump(cfg['name']+'_full_trades.json', json.loads(trades.to_json(orient='records', date_format='iso')))

        return row
    try:
        dev = {}
        for cfg in CONFIGS:
            results = [run(cfg, d, 'dev') for d in starts['dev']]
            dev[cfg['name']] = summarize(results)
            print('DEV', cfg['name'], dev[cfg['name']], flush=True)
        ref = dev['control']
        eligible = [c for c in CONFIGS[1:] if dev[c['name']]['p10'] > ref['p10']
                    and dev[c['name']]['median'] >= ref['median']-.01
                    and dev[c['name']]['drawdown'] >= ref['drawdown']-.02]
        winner = max(eligible, key=lambda c: (dev[c['name']]['p10'], dev[c['name']]['median'])) if eligible else CONFIGS[0]
        dump('frozen_development_selection.json', dict(winner=winner, dev=dev, eligible=[c['name'] for c in eligible]))
        finalists = [CONFIGS[0]] + ([winner] if winner['name'] != 'control' else [])
        audit, stress_results, full_results = {}, {}, {}
        for cfg in finalists:
            name = cfg['name']
            audit[name] = summarize([run(cfg, d, 'audit') for d in starts['audit']])
            for split in ('dev', 'audit'):
                stress_results[name+'_'+split] = summarize([run(cfg, d, split, True) for d in starts[split]])
            full_results[name] = run(cfg, min(base), 'full', full=True)
            print('FINALIST', name, audit[name], flush=True)
        n = winner['name']
        passed = n != 'control' and audit[n]['p10'] > audit['control']['p10'] and audit[n]['median'] >= audit['control']['median']-.01 and audit[n]['drawdown'] >= audit['control']['drawdown']-.02
        passed = passed and all(stress_results[n+'_'+s]['p10'] > stress_results['control_'+s]['p10'] for s in ('dev', 'audit'))
        result = dict(dev=dev, winner=n, audit=audit, stress=stress_results, full=full_results,
                      provisional_robustness_pass=bool(passed), platform_parity_pass=False)
        dump('summary.json', result)
        lines = ['# 月度策略有限调参（本地近似口径）', '',
                 '按用户要求在近似口径下继续研究；原平台对齐门槛仍未通过，不把研究通过当作平台复现。',
                 '开发24个起点（2020—2021每月），各持有24个月；审计8个起点（2024年1—8月），各持有24个月。',
                 '所有起点独立10万元空仓重跑。窗口重叠，历史已观察。', '',
                 '| 方案 | 开发年化中位数 | 开发年化P10 | 开发最差回撤 | 中位费用（元） |',
                 '|---|---:|---:|---:|---:|']
        for cfg in CONFIGS:
            x = dev[cfg['name']]
            lines.append('| %s | %.2f%% | %.2f%% | %.2f%% | %.2f |' % (cfg['label'], x['median']*100, x['p10']*100, x['drawdown']*100, x['fees']))
        lines += ['', '开发期冻结候选：'+winner['label'], '候选是否通过预设审计及费用压力条件：'+str(bool(passed)), '',
                  '| 方案 | 审计年化中位数 | 审计年化P10 | 审计最差回撤 | 双倍成本审计年化P10 |',
                  '|---|---:|---:|---:|---:|']
        for cfg in finalists:
            x = audit[cfg['name']]
            lines.append('| %s | %.2f%% | %.2f%% | %.2f%% | %.2f%% |' % (cfg['label'], x['median']*100, x['p10']*100, x['drawdown']*100, stress_results[cfg['name']+'_audit']['p10']*100))
        lines += ['', '未改正式基准。候选未通过则不按审计结果改选其他方案。',
                  '本研究仅检验月初信号；不是启动次交易日同日月度版的精确复现，也未验证每个交易日起跑。',
                  '调仓日分红与分钟撮合仍近似，当前股票池不完全点时，不能据此保证实盘收益。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        for field, value in original.items():
            setattr(g.bt, field, value)


if __name__ == '__main__':
    main()
