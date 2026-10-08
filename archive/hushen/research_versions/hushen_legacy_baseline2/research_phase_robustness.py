"""Quarterly phase robustness, bounded search; no platform baseline changes."""
import json
import numpy as np
import pandas as pd
import group_research as g
from start_date_robustness import measure
from robust_policy_search import summarize

OUT = g.HERE/'phase_robust_search_100k'
CONFIGS = ['control', 'equal_weight', 'risk_power_half', 'risk_power_1_5', 'wide_cap_band', 'smooth_regime']
LABELS = ['原规则', '等权持仓', '弱化风险权重', '强化风险权重', '扩大防守市值区间', '平滑强弱切换']


def save(name, obj):
    (OUT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def aggregate(rows):
    phases = {str(p): summarize([r for r in rows if r['phase'] == p]) for p in range(3)}
    return dict(overall=summarize(rows), phases=phases,
                worst_phase_p10=min(x['p10'] for x in phases.values()))


def main():
    OUT.mkdir(exist_ok=True)
    save('protocol.json', dict(configs=CONFIGS, labels=LABELS, capital=100000,
        schedule='Every 3 months from entry MONTH; month first sessions only, NOT exact day anchors.',
        dev='24 independent monthly starts 2020-2021, 24 months each, observations before 2024.',
        audit='8 monthly starts Jan-Aug 2024, 24 months each; already observed history.',
        selection='Improve minimum of the 3 phase P10 annual returns; no phase P10 below its control; overall median >= control-1pp and worst drawdown >= control-2pp. Freeze winner before audit, otherwise control.',
        final_gate='Same audit criteria plus both dev and audit minimum phase P10 improvement at doubled commission/minimum commission/slippage; no reselection.',
        warnings=['Repeated historical research and overlapping windows; not pristine OOS.',
                  'Daily-open proxy, approximate corporate actions and fixed universe; platform parity unresolved.',
                  'No new candidate automatically replaces formal baseline.']))
    f = g.features()
    idx = pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet')
    idx['date'] = pd.to_datetime(idx.date)
    idx = idx.sort_values('date')
    ranks = {n: {} for n in CONFIGS}
    for d, frame in f.groupby('execute_date'):
        x = frame.sort_values('symbol').copy()
        hist = idx[idx.date <= x.signal_date.iloc[0]]
        ratio = hist.close.iloc[-1]/hist.close.tail(120).mean()-1
        strong = ratio > 0
        attack = .25*g.bt.rank01(x.amount20.to_numpy(), True)+.2*g.bt.rank01(x.near_high.to_numpy())+.55*g.bt.rank01(x.dividend.to_numpy())
        for name in CONFIGS:
            q = x.copy()
            if name == 'smooth_regime':
                # Fixed +/-5% band; all-stock defensive ranks avoid missing scores.
                alpha = float(np.clip(.5+ratio/.10, 0, 1))
                defense = .55*q.dividend.rank(pct=True)+.3*(1-q.downside.rank(pct=True))+.15*(1-q.turn20.rank(pct=True))
                q['score'] = alpha*attack+(1-alpha)*defense
            elif strong:
                q['score'] = attack
            else:
                if name == 'wide_cap_band':
                    pct = q.float_cap_proxy.rank(pct=True)
                    q = q[(pct >= .25) & (pct < .75)]
                else:
                    q = q[q.float_cap_proxy_group == 1]
                q = g.score(q, 'quality')
            if name == 'equal_weight': q['downside'] = 1.
            elif name == 'risk_power_half': q['downside'] = q.downside.pow(.5)
            elif name == 'risk_power_1_5': q['downside'] = q.downside.pow(1.5)
            ranks[name][d] = q.sort_values(['score', 'symbol'], ascending=[False, True])
    union = set().union(*(set(x.head(24).symbol) for rr in ranks.values() for x in rr.values()))
    panel = g.bt.load_daily_panel(union)
    original = {n: getattr(g.bt, n) for n in ('START','END','INITIAL_CASH','SLIPPAGE','COMMISSION','MIN_COMMISSION','apply_corporate_action')}
    def action(cash, positions, day, previous):
        cash = original['apply_corporate_action'](cash, positions, day, previous)
        for s, qty in positions.items():
            if s not in day.index or s not in previous: continue
            pre = float(day.loc[s, 'preclose'])
            if np.isfinite(pre) and pre > 0 and 1+1e-8 < previous[s]/pre <= 1.02:
                cash += qty*(previous[s]-pre)
        return cash
    g.bt.apply_corporate_action = action
    g.bt.INITIAL_CASH = 100000.
    starts = dict(dev=[d for d in ranks['control'] if d.year in (2020,2021)],
                  audit=[d for d in ranks['control'] if d.year == 2024 and d.month <= 8])
    previous = json.loads((g.HERE/'start_date_robustness_100k/results.json').read_text(encoding='utf-8'))
    rows = []
    def run(name, start, split, stress=False):
        g.bt.START = start
        g.bt.END = start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        assert split != 'dev' or g.bt.END < pd.Timestamp('2024-01-01')
        phase = (start.month-1)%3
        rr = {d:x for d,x in ranks[name].items() if start <= d <= g.bt.END and (d.month-1)%3 == phase}
        for field in ('SLIPPAGE','COMMISSION','MIN_COMMISSION'):
            setattr(g.bt, field, original[field]*(2 if stress else 1))
        c,t = g.bt.simulate(rr,.05,8,24,.8,1.5,panel,min_adjustment=3000)
        assert (c.cash >= -.01).all()
        assert (t[t.side == 'BUY'].quantity%100 == 0).all()
        assert t[t.side == 'BUY'].merge(t[t.side == 'SELL'], on=['date','symbol']).empty
        if name == 'control' and not stress:
            ref = next(x for x in previous if x['schedule']=='entry_month_phase_quarters' and x['horizon']=='24_months' and x['start']==str(start.date()))
            assert abs(c.equity.iloc[-1]-ref['final_equity']) < .01, 'control mismatch'
        row = dict(name=name, start=str(start.date()), end=str(c.date.iloc[-1].date()), split=split, phase=phase,
                   stress=stress, **measure(c), fees=float((t.commission+t.stamp_tax).sum()), orders=len(t))
        rows.append(row)
        save('results.json',rows)
        return row
    def qualifies(a,b):
        return (a['worst_phase_p10'] > b['worst_phase_p10']
                and all(a['phases'][p]['p10'] >= b['phases'][p]['p10'] for p in b['phases'])
                and a['overall']['median'] >= b['overall']['median']-.01
                and a['overall']['drawdown'] >= b['overall']['drawdown']-.02)
    try:
        dev = {}
        for name in CONFIGS:
            dev[name] = aggregate([run(name,d,'dev') for d in starts['dev']])
            print('DEV',name,dev[name]['overall'],'worst phase P10',dev[name]['worst_phase_p10'],flush=True)
        eligible = [n for n in CONFIGS[1:] if qualifies(dev[n],dev['control'])]
        winner = max(eligible,key=lambda n:dev[n]['worst_phase_p10']) if eligible else 'control'
        save('frozen_selection.json',dict(winner=winner,eligible=eligible,dev=dev))
        audit,stress = {},{}
        for name in dict.fromkeys(['control',winner]):
            audit[name] = aggregate([run(name,d,'audit') for d in starts['audit']])
            for split in ('dev','audit'):
                stress[name+'_'+split] = aggregate([run(name,d,split,True) for d in starts[split]])
            print('AUDIT',name,audit[name]['overall'],flush=True)
        passed = winner!='control' and qualifies(audit[winner],audit['control'])
        passed = passed and all(stress[winner+'_'+s]['worst_phase_p10'] > stress['control_'+s]['worst_phase_p10'] for s in ('dev','audit'))
        result = dict(winner=winner,passed=bool(passed),dev=dev,audit=audit,stress=stress,runs=len(rows),platform_parity=False)
        save('summary.json',result)
        lines=['# 季度月份稳健性研究','', '10万元独立起跑，8只股票、80%目标仓位；日线近似，不是平台分钟复现。',
               '开发24个起点，各持有24个月；三个季度月份组各8个窗口。后段审计每组仅2—3个窗口，证据较弱。',
               '相较上一轮，本轮不挑日程，要求候选在三组季度安排下都不降低年化P10。','',
               '| 方案 | 开发年化中位数 | 开发年化P10 | 最差季度组年化P10 | 最差回撤 |',
               '|---|---:|---:|---:|---:|']
        for name,label in zip(CONFIGS,LABELS):
            s=dev[name];q=s['overall']
            lines.append('| %s | %.2f%% | %.2f%% | %.2f%% | %.2f%% |'%(label,q['median']*100,q['p10']*100,s['worst_phase_p10']*100,q['drawdown']*100))
        lines += ['', '开发冻结候选：'+winner, '是否通过后段及费用压力条件：'+str(bool(passed)), '',
                  '| 审计方案 | 年化中位数 | 最差季度组年化P10 | 最差回撤 |', '|---|---:|---:|---:|']
        for name,x in audit.items():
            lines.append('| %s | %.2f%% | %.2f%% | %.2f%% |'%(name,x['overall']['median']*100,x['worst_phase_p10']*100,x['overall']['drawdown']*100))
        lines += ['', '保留正式基准；不依照审计结果另选候选。历史已反复观察，窗口重叠，不能视为独立样本外。',
                  '本轮只检验月初与季度月份，不声称任意交易日起跑有效。固定股票池、除权近似和成交口径仍是限制。']
        (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('DONE',len(rows),'winner',winner,'pass',passed,flush=True)
    finally:
        for k,v in original.items():setattr(g.bt,k,v)


if __name__ == '__main__':main()
