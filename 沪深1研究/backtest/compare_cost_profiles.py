"""Compare costs on an existing hashed range snapshot; never regenerate ranks."""
from pathlib import Path
import argparse
import hashlib
import json

import numpy as np
import pandas as pd
import engine as e

HOME = Path(__file__).resolve().parents[1]


def read(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    args = parser.parse_args()
    out = args.snapshot.resolve()
    assert out.is_relative_to(HOME/'results/holdout_restricted')
    baseline = read(out/'original_cost_summary.json')
    unified = read(out/'summary.json')
    started = read(out/'RUN_STARTED.json')
    assert sha(HOME/'supermind_hushen_1.py') == started['strategy_sha256']
    root = HOME.parents[1]
    assert not list((root/'K线数据/更新备份与审计').rglob('*.lock'))
    target = baseline['end']
    assert target == unified['end'] and baseline['actual_start'] == unified['actual_start']
    work = out/'runtime_inputs'
    e.HERE = work
    e.r.HERE = work
    e.r.Q = dict(e.r.Q, end=target)
    code = (HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'", "HERE/'calendar.parquet'")
    exec(compile(code, str(HOME/'backtest/engine.py'), 'exec'), e.__dict__)
    market = e.Market()  # Verifies every raw file against the saved snapshot hash.
    market.actions.own = work/'additional_actions.json'
    market.actions.extra = read(market.actions.own) if market.actions.own.exists() else {}
    market.actions.cache.update(market.actions.extra)
    start, cash = baseline['requested_start'], baseline['initial_cash']
    try:
        reproduced, _ = e.simulate(market, start, target, initial=cash)
        for k in ['final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost']:
            assert np.isclose(reproduced[k], baseline[k], rtol=0, atol=1e-8), k
        third, account = e.simulate(market, start, target, initial=cash,
                                    params={'SLIP_ONE_SIDE': .002}, save='slippage_only_comparison')
    finally:
        market.actions.close()
    assert third['unresolved_actions'] == third['reference_differences'] == 0
    assert not getattr(account, 'settle_sale_next_session', False)
    assert not getattr(account, 'no_transfer_fee', False)
    assert not hasattr(account, 'fixed_stamp_rate')
    assert account.m.SLIP_ONE_SIDE == .002
    write(out/'slippage_only_summary.json', third)
    pd.DataFrame(account.curve).to_csv(out/'slippage_only_daily_nav.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(account.trades).to_csv(out/'slippage_only_trades.csv', index=False, encoding='utf-8-sig')
    profiles = [('原口径',baseline),('仅滑点改为0.2%',third),('统一现金与成本',unified)]
    write(out/'THREE_PROFILE_COMPARISON.json', dict(
        profiles={name: result for name,result in profiles},
        controlled_change={'SLIP_ONE_SIDE': {'old': .001, 'new': .002}},
        original_reproduced=True,
        input_sha256=sha(work/'inputs.json'), ranking_sha256=sha(work/'rankings_original.json'),
        strategy_sha256=sha(HOME/'supermind_hushen_1.py'),
        engine_sha256=sha(HOME/'backtest/engine.py'), ledger_sha256=sha(HOME/'backtest/ledger.py')))
    rows = [
        ('期末资产', 'final_equity', 'money'), ('累计收益','total_return','pct'),
        ('年化收益','cagr','pct'), ('最大回撤','max_drawdown','pct'),
        ('Sharpe','sharpe','number'), ('成交笔数','trades','integer'),
        ('佣金','commission','money'), ('过户费','transfer','money'),
        ('印花税','stamp','money'), ('股息税','dividend_tax','money'),
        ('总成本（含股息税）','total_cost','money'), ('平均仓位','average_exposure','pct')]
    lines = ['# 沪深1三组现金与成本口径对照','',
             f"初始{cash:,.0f}元；实际入场{baseline['actual_start']}，截止{target}；同一行情、排名、原四因子、5只目标、98%及20交易日调仓。",'',
             '| 指标 | 原口径 | 仅滑点改为0.2% | 统一现金与成本 |',
             '|---|---:|---:|---:|']
    for label, key, fmt in rows:
        vals = [r[key] for _, r in profiles]
        formatted = [(f'{v:.2%}' if fmt=='pct' else f'{v:,.2f}' if fmt=='money' else f'{v:.3f}' if fmt=='number' else str(int(v))) for v in vals]
        lines.append('| '+label+' | '+' | '.join(formatted)+' |')
    lines += ['', '原口径：卖出款当天可用、单边滑点0.1%、佣金万三最低5元、历史印花税和过户费。',
              '仅滑点组：唯一参数变化为SLIP_ONE_SIDE从0.001改为0.002；现金结算、税费、资金不足整手减量及成交量限制均沿原逻辑。',
              '统一组：卖出净款下一交易日可用、滑点0.2%、佣金万三最低5元、卖出印花税固定0.1%、无单列过户费。',
              '滑点按原日线撮合逻辑受限价、涨跌停、日内价格范围及分位取整约束；总成本不重复列入已体现在成交价中的滑点。股息税沿原FIFO规则。',
              '原口径已在本次相同行情快照上复现，核心指标绝对误差不超过1e-8；本次未修改生产策略参数或独立跟踪账户。']
    (out/'THREE_PROFILE_COMPARISON.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(third, ensure_ascii=False, default=str), flush=True)
    print('COMPLETE', out/'THREE_PROFILE_COMPARISON.md', flush=True)


if __name__ == '__main__':
    main()
