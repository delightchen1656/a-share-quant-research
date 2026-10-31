"""Replay the registered Hushen1 entry over an explicit audited date range."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

import numpy as np
import pandas as pd
import engine as e

HOME = Path(__file__).resolve().parents[1]
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
DATA = ROOT / 'K线数据/沪深'


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end', default=None)
    parser.add_argument('--cash', type=float, default=100000)
    parser.add_argument('--cost-policy', choices=['open_003_guaranteed','unified_cash_cost','strict_daily_limits'], default='open_003_guaranteed')
    args = parser.parse_args()
    refresh = read(sorted((DATA/'metadata').glob('refresh_*.json'))[-1])
    target = args.end or refresh['target']
    assert refresh['status'] == 'ok' and target <= refresh['target']
    assert not list((ROOT/'K线数据/更新备份与审计').rglob('*.lock')), 'Market update in progress'
    sys.path.insert(0,str(ROOT/'tools'))
    from committed_market import select_commit
    audit_path, audit, _ = select_commit(DATA,ROOT/'K线数据/更新备份与审计')
    assert audit['status'] == 'ok' and audit['target'] == refresh['target']
    migration = read(HOME/'research/migration.json')
    entry = HOME/'supermind_hushen_1.py'
    assert sha(entry) == migration['entry_sha256'], 'Registered strategy hash changed'
    if args.cost_policy=='open_003_guaranteed':
        registration=migration['local_execution_baseline']
        assert registration['scenario']==args.cost_policy
        assert sha(HOME/registration['policy_file'])==registration['policy_sha256'],'Execution baseline policy changed without registration'
    out = HOME/'results/holdout_restricted'/('range_'+args.start.replace('-', '')+'_to_'+target.replace('-', '')+'_'+args.cost_policy)
    out.mkdir(parents=True, exist_ok=True)
    work = out/'runtime_inputs'
    work.mkdir(exist_ok=True)
    if args.cost_policy=='unified_cash_cost':
        write(out/'cash_cost_policy.json', read(HOME/'backtest/cash_cost_policy.json'))
    if args.cost_policy=='open_003_guaranteed':
        write(out/'execution_baseline.json', read(HOME/'backtest/execution_baseline.json'))
    write(out/'RUN_STARTED.json', dict(start=args.start, end=target, initial_cash=args.cash, strategy_sha256=sha(entry), audit_sha256=sha(audit_path),scenario=args.cost_policy,engine_sha256=sha(HOME/'backtest/engine.py'),ledger_sha256=sha(HOME/'backtest/ledger.py')))
    cal = pd.read_csv(DATA/'metadata'/('trade_calendar_'+refresh['target'].replace('-', '')+'.csv'))
    dates = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.iloc[:, 1].astype(str).eq('1')].iloc[:, 0]))
    dates = dates[(dates >= '2018-01-01') & (dates <= target)]
    assert dates[-1] == pd.Timestamp(target)
    actual = dates[dates >= args.start][0]
    source = e.r.mod(entry, 'explicit_range_strategy')
    assert (source.COUNT, source.INTERVAL, source.EXPOSURE) == (5, 20, .98)
    meta = pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv').set_index('symbol')
    signal_dates = dates[(dates >= dates[dates.get_loc(actual)-1-source.SMOOTH]) & (dates < target)]
    paths = sorted((DATA/'raw').glob('*/*.parquet'))
    symbols = [p.stem for p in paths]
    values = {k: np.full((len(signal_dates), len(symbols)), np.nan, dtype=np.float32) for k in e.r.FEATURES}
    eligible = np.zeros((len(signal_dates), len(symbols)), dtype=bool)
    records = []
    for j, path in enumerate(paths):
        assert source.mainboard(path.stem) and path.stem in meta.index
        x = pd.read_parquet(path)
        x.date = pd.to_datetime(x.date)
        assert not x.date.duplicated().any(), path.stem
        x = x.loc[x.date <= target].set_index('date').sort_index()
        x = x[e.FIELDS[:10]].apply(pd.to_numeric, errors='raise')
        f, ok, _ = e.r.features(x)
        u = meta.loc[path.stem]
        ok &= ok.index >= pd.Timestamp(u.ipoDate)
        if pd.notna(u.outDate):
            ok &= ok.index < pd.Timestamp(u.outDate)
        for k in e.r.FEATURES:
            values[k][:, j] = f[k].reindex(signal_dates).to_numpy()
        eligible[:, j] = ok.reindex(signal_dates, fill_value=False).to_numpy()
        records.append(dict(symbol=path.stem, sha256=sha(path), max_date=str(x.index.max().date())))
        if (j+1) % 600 == 0:
            print('INPUTS', j+1, len(paths), flush=True)
    ranked = {k: pd.DataFrame(v, index=signal_dates, columns=symbols).where(eligible).rank(axis=1, pct=True, method='average').astype(np.float32) for k, v in values.items()}
    score = (-.35*ranked['cap']-.20*ranked['vol']+.25*ranked['overnight']-.20*ranked['intraday']).rolling(5, min_periods=3).mean().astype(np.float32).where(eligible)
    ranks = {str(d.date()): row.dropna().sort_values(ascending=False, kind='mergesort').head(100).index.tolist() for d, row in score.iterrows()}
    frozen = read(HOME/'results/latest/rankings_original.json')
    parity = []
    for d in dates[(dates >= actual) & (dates <= target)]:
        i = dates.get_loc(d)
        if d == actual or (i-1) % source.INTERVAL == 0:
            key = str(dates[i-1].date())
            assert ranks[key], ('No ranking', key)
            if key in frozen:
                same = ranks[key] == frozen[key]
                parity.append(dict(date=key, identical=same))
                assert same, ('Frozen ranking mismatch', key)
    write(work/'inputs.json', dict(files=records))
    write(work/'rankings_original.json', ranks)
    pd.DataFrame(dict(date=dates)).to_parquet(work/'calendar.parquet', index=False)
    write(out/'SIGNAL_AUDIT.json', dict(frozen_overlap=parity, recomputed_from_raw=True, strategy_sha256=sha(entry)))
    e.HERE = work
    e.r.HERE = work
    e.r.DATA = DATA
    e.r.Q = dict(e.r.Q, end=target)
    code = (HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'", "HERE/'calendar.parquet'")
    exec(compile(code, str(HOME/'backtest/engine.py'), 'exec'), e.__dict__)
    market = e.Market()
    # Keep additional responses local to this replay; also reuse audited tracking receipts.
    market.actions.own = work/'additional_actions.json'
    market.actions.extra = read(market.actions.own) if market.actions.own.exists() else {}
    track_actions = HOME/'tracking/ledger_inputs/additional_actions.json'
    if track_actions.exists():
        for k, v in read(track_actions).items():
            market.actions.cache.setdefault(k, v)
    market.actions.cache.update(market.actions.extra)
    print('SIMULATE', actual.date(), target, flush=True)
    try:
        result, account = e.simulate(market, args.start, target, scenario=args.cost_policy, initial=args.cash, save='replay')
    finally:
        market.actions.close()
    assert result['unresolved_actions'] == 0, result['issues']
    assert result['reference_differences'] == 0, result['reference']
    nav = pd.DataFrame(account.curve)
    nav.to_csv(out/'daily_nav.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(account.trades).to_csv(out/'trades.csv', index=False, encoding='utf-8-sig')
    holdings = []
    for s, p in account.holdings.items():
        holdings.append(dict(symbol=s, quantity=p['qty'], close=p['last'], market_value=p['qty']*p['last'], lots=p['lots']))
    write(out/'holdings.json', holdings)
    write(out/'summary.json', result)
    execution_note=('当前理想化基线：买入开盘价×1.003、卖出开盘价×0.997，分位取整，足额成交；卖出净款当日可用。忽略成交量、涨跌停撮合和日内价格范围约束；缺少真实开盘价停止，资金/整手/T+1仍校验。不是平台或券商成交保证。' if args.cost_policy=='open_003_guaranteed' else '历史执行口径：'+args.cost_policy)
    lines = ['# 沪深1指定区间本地回放', '', f"申请起点：{args.start}；实际入场：{result['actual_start']}；截止：{target}；初始现金：{args.cash:,.2f}元。", '', '原四因子固定5只目标、98%仓位、20交易日调仓；费用扣除，末日未强制平仓。',execution_note, '', '| 指标 | 结果 |', '|---|---:|', f"| 期末资产 | {result['final_equity']:,.2f}元 |", f"| 累计收益 | {result['total_return']:.2%} |", f"| 年化收益 | {result['cagr']:.2%} |", f"| 最大回撤 | {result['max_drawdown']:.2%} |", f"| Sharpe（无风险利率0） | {result['sharpe']:.3f} |", f"| 成交笔数 | {result['trades']} |", f"| 总成本（含股息税） | {result['total_cost']:,.2f}元 |", f"| 期末现金 | {result['final_cash']:,.2f}元 |", '', '年化采用实际入场日至末日的自然日跨度；后边界历史回放，不是独立未见盲测。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write(out/'RUN_COMPLETE.json', dict(status='complete', summary_sha256=sha(out/'summary.json'), inputs_sha256=sha(work/'inputs.json'), entry_sha256=sha(entry), script_sha256=sha(Path(__file__))))
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    print('COMPLETE', out, flush=True)


if __name__ == '__main__':
    main()
