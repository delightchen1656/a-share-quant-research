"""Matched retrospective comparison; frozen scores, no fitting or selection."""
from pathlib import Path
import importlib.util
import json
import hashlib
import math
import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'original_202001'
BASE = HERE.parents[1]

def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def dump(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def count_for(equity, step):
    if step is None:
        return 5
    count, threshold = 5, 200000.
    while count < 15 and equity >= threshold:
        count += 1
        threshold *= 2
    return count

def main():
    entry = HERE.parent / 'uploaded_source.py'
    source_hash = hashlib.sha256(entry.read_bytes()).hexdigest()
    dump('protocol.json', dict(start='2020-01-02', end='2026-09-30', initial_cash=100000,
        thresholds=[100000 * 2**i for i in range(11)], base_count=5, max_count=15, exposure=.98,
        sizing='Previous session closing equity, including cash and dividend receivables. Recompute only on original 20-session schedule; allow downgrades, no hysteresis.',
        preservation='Original score, retention buffer multiplier, drift, execution and accounting unchanged. No fitting, feedback selection or live orders.', source_sha256=source_hash))
    engine = mod(SOURCE / 'weekly_engine.py', 'dynamic_engine')
    engine.load_model = lambda k: engine.module(entry, 'original_export')
    p = mod(BASE / 'test2_retrain_2022/pipeline.py', 'feature_utils')
    p.HERE = SOURCE
    ledger = mod(SOURCE / 'ledger.py', 'shared_ledger')
    ranks = json.loads((SOURCE / 'rankings.json').read_text(encoding='utf-8'))
    old = BASE / 'start_date_study'
    dates = pd.DatetimeIndex(pd.read_parquet(old / 'benchmark.parquet').date)
    days, actions, outs = ledger.load(p, engine, ranks, dates, old)
    results, curves, trades, schedules = [], [], [], []
    checks = {'boundary_counts': all(count_for(v, s) == expected for v, s, expected in [
        (99999, 1., 5), (199999.99, 1., 5), (200000, 1., 6), (399999.99, 1., 6), (400000, 1., 7), (800000, 1., 8), (102400000, 1., 15)])}
    for name, step in [('fixed5', None), ('doubling', 1.)]:
        start = pd.Timestamp('2020-01-02')
        a = engine.Account('D11', start, actions, days, outs)
        for i in range(dates.get_loc(start), len(dates)):
            date = dates[i]
            due = a.m.g.alpha_first or (i - 1) % 20 == 0
            prior_equity = a.curve[-1]['equity'] if a.curve else 100000.
            old_count = a.m.COUNT
            if due:
                a.m.COUNT = count_for(prior_equity, step)
            before_targets = a.m.g.alpha_targets
            a.step(date, i, dates[i-1], ranks)
            assert (a.m.g.alpha_targets is not before_targets) == due
            assert due or a.m.COUNT == old_count
            if due:
                assert sum(q > 0 for q in a.m.g.alpha_targets.values()) <= a.m.COUNT
                schedules.append(dict(scenario=name, date=date, prior_equity=prior_equity,
                    count=a.m.COUNT, target_count=sum(q > 0 for q in a.m.g.alpha_targets.values())))
            a.curve[-1].update(scenario=name, holdings_limit=a.m.COUNT,
                              holdings_count=len(a.holdings))
        q = pd.DataFrame(a.curve)
        nav = q.equity.to_numpy()
        dd = 1 - nav / np.maximum.accumulate(np.r_[100000., nav])[1:]
        result = dict(scenario=name, start=start, end=dates[-1], final_equity=float(nav[-1]),
            total_return=float(nav[-1]/100000.-1), cagr=float((nav[-1]/100000.)**(365.25/((dates[-1]-start).days+1))-1),
            max_drawdown=float(dd.max()), trades=len(a.trades), fees=a.fees, dividend_tax=a.tax,
            avg_exposure=float(q.exposure.mean()), final_cash=a.cash,
            final_market_value=float(q.market_value.iloc[-1]), final_limit=a.m.COUNT,
            max_limit=int(q.holdings_limit.max()), final_holdings=len(a.holdings),
            max_actual_holdings=int(q.holdings_count.max()), unresolved_actions=len(a.issues),
            reference_differences=len(a.reference_diffs), capacity_rejections=a.capacity_hits)
        results.append(result)
        curves.extend(a.curve)
        trades.extend(dict(t, scenario=name) for t in a.trades)
        dump(name+'_action_issues.json', a.issues)
        dump(name+'_reference_differences.json', a.reference_diffs)
        checks[name+'_cash_actions'] = bool(q.cash.min() >= -.01 and not a.issues and not a.reference_diffs)
        checks[name+'_lots'] = all(t['qty'] % 100 == 0 for t in a.trades if t['qty'] > 0)
        print(json.dumps(result, default=str), flush=True)
    original = json.loads((SOURCE/'results.json').read_text(encoding='utf-8'))[0]
    checks['baseline_reproduced'] = all(np.isclose(results[0][k], original[k], rtol=0, atol=1e-8) for k in
        ['final_equity', 'cagr', 'max_drawdown', 'fees', 'dividend_tax', 'trades'])
    original_nav = pd.read_parquet(SOURCE/'daily_equity.parquet').equity.to_numpy()
    checks['baseline_every_day_reproduced'] = bool(np.array_equal(pd.DataFrame(curves).query("scenario == 'fixed5'").equity.to_numpy(), original_nav))
    checks['source_unchanged'] = hashlib.sha256(entry.read_bytes()).hexdigest() == source_hash
    dump('results.json', results)
    dump('validation.json', checks)
    pd.DataFrame(curves).to_parquet(HERE/'daily_equity.parquet', index=False)
    pd.DataFrame(trades).to_parquet(HERE/'trades.parquet', index=False)
    pd.DataFrame(schedules).to_parquet(HERE/'schedules.parquet', index=False)
    assert all(checks.values()), checks
    print('PASS', len(checks), flush=True)

if __name__ == '__main__':
    main()
