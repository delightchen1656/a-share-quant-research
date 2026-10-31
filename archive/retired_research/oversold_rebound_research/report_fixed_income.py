"""Freeze and describe the development-selected fixed rule without OOS claims."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from study import ROOT,SOURCE,digest
from study_fixed_income import OUT


def main():
    m=json.loads((OUT/'summary.json').read_text(encoding='utf8'));w=m['winner']
    if not w:raise RuntimeError('No qualifying rule; do not fabricate a winner')
    c=w['config'];r=w['persisted_result'];s=r['summary'];folder=OUT/r['key']
    trades=pd.read_parquet(folder/'trades.parquet');nav=pd.read_parquet(folder/'daily_nav.parquet')
    assert s['capital']==100000 and s['slots']==5
    assert s['delayed_exits']==0 and s['trades']==210
    assert abs(100000+trades.pnl.sum()-s['final_equity'])<.01
    assert trades.buy_offset.between(1,3).all()
    old=json.loads((ROOT/'results_v11_filtered_horizons/summary.json').read_text(encoding='utf8'))
    baseline=next(x for x in old['results'] if x['horizon']==3 and x['summary']['pool']=='sample' and x['summary']['capital']==100000)
    rule=dict(name='方向2_低价深超跌_10万5槽_B3_v1',status='FROZEN_RESEARCH_CANDIDATE_NOT_PRODUCTION',
        selected_using='Explored2021-2024 development results; all these years participated in choosing it. Not independent validation.',
        universe='Existing947-stock mainboard basic oversold-signal cohort, not all-mainboard census; no leader-only constraint; no previous95% ML gate.',
        filters=dict(base='Existing v1 oversold-bullish basic event plus consecutive suspected limit-down exclusion',
                     raw_signal_close_lt=10,adjusted_signal_close_div_ma20_lte=.90),
        account=dict(capital=100000,slots=5,slot_budget_including_buy_fee=20000,lot_size=100,tie_order='code ascending',
                     entry='Next official session open, guaranteed-fill assumption',take_profit=.05,
                     forced_close_buy_offset=3,buy_day_offset=0,T_plus_1=True,stop_loss=None),
        fees='Commission .0003 min5 both sides; historical transfer/stamp schedules as account_backtest.py',
        special_events_excluded=m['excluded_specials'],
        exclusions_are_ex_post=True,
        hashes={str(p.relative_to(ROOT)):digest(p) for p in [ROOT/'study.py',ROOT/'exclude_limit_streaks.py',ROOT/'account_backtest.py',ROOT/'study_fixed_income.py',ROOT/'results_v5_long_position/events.parquet']},
        market_manifest_sha256=digest(SOURCE/'MANIFEST.json'),development_summary_sha256=digest(OUT/'summary.json'))
    (OUT/'FROZEN_RULE.json').write_text(json.dumps(rule,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2固定研发候选：低价深超跌，10万元5槽，5%止盈，B3收盘退出',
      '这是一条研发期选出的固定候选，尚非独立盲测结果，也未上线。所有2021—2024年份都参与了这次固定规则选择。',
      '先前严格用往年选参数的两轮滚动方案仍有亏损年份；本固定候选不能冒充当年之前已经确定的历史实盘规则。',
      '本轮比较96个配置，24个满足每年盈利、每年至少6笔成交、全期最大回撤不超过15%；按最低年度收益优先挑选。存在多重比较和过拟合风险。',
      '', '冻结规则：',
      '1. 沿用现有基础超跌转阳信号，并排除信号前连续至少2日疑似跌停的形态。',
      '基础条件：信号前20个有效日跌至少15%、前5日跌至少8%；信号收盘低于MA20和MA60，近3日低点距20日低点不超过2%；阳线实体占振幅至少40%、上影不超过30%，收盘距近3日低点不超过12%。同股10个有效日冷却。',
      '2. 额外要求信号日未复权收盘价<10元；前复权收盘价/MA20<=0.90。',
      '3. 使用该947股票白名单中的全部基础信号，不限龙头，不再套原95%触及模型。',
      '4. 初始10万元、5槽，每槽固定2万元含买入费用。按信号次一正式交易日开盘买入，100股向下取整；满槽跳过，同日按代码升序。',
      '5. 买入当天B0不卖，B1起达到买价上方5%止盈；开盘越过目标按开盘卖；B3未止盈则收盘卖出。本候选不加固定比例价格止损。',
      '6. 按此前授权假设开盘保证成交，不将盘中/收盘回款提前用于同日开盘；佣金万三最低5元及历史税费、分红送转记账保持不变。',
      '', '2021—2024研发期实际账户结果（所有年份参与挑选）：',
      '年份 | 年度收益 | 年内最大回撤 | 年末权益 | 年内买入笔数']
    for y in r['yearly']:lines.append(f"{y['year']} | {y['return_pct']:.2%} | {-y['max_drawdown']:.2%} | {y['end_equity']:.2f} | {r['yearly_trades'].get(str(y['year']),r['yearly_trades'].get(y['year'],0))}")
    lines += [f"累计收益{s['total_return']:.2%}，年化{s['annualized_return']:.2%}，全期最大回撤{-s['max_drawdown']:.2%}，期末{s['final_equity']:.2f}。",
      f"候选信号{s['signals']}，成交{s['trades']}，跳过{s['skipped']}；5%止盈{s['takeprofit']}笔，B3强平{s['forced']}笔，止盈比例{s['takeprofit']/s['trades']:.2%}，净盈利交易比例{s['net_win_rate']:.2%}。",
      '5%止盈命中率不等于此前40日+3%触及率，两者退出幅度和观察期限都不同。',
      '', '与原3%止盈、B3强平、原高准确率筛选器对比：',
      '年份 | 原规则收益 | 本候选收益']
    for a,b in zip(baseline['yearly'],r['yearly']):lines.append(f"{a['year']} | {a['return_pct']:.2%} | {b['return_pct']:.2%}")
    lines += [f"原规则累计{baseline['summary']['total_return']:.2%}，全期回撤{-baseline['summary']['max_drawdown']:.2%}；本候选累计{s['total_return']:.2%}，全期回撤{-s['max_drawdown']:.2%}。",
      '本候选较弱年份收益提高，但2021收益降低、全期回撤增大，不是每个指标全面优于原规则。',
      '', '边界与异常：',
      '只读截至2024年底白名单；未读取2025—2026年结果。价格保证成交为理想假设；不是已核验的市场容量结论。',
      '已按用户指示事后剔除到期缺价特殊事件，清单：'+json.dumps(m['excluded_specials'],ensure_ascii=False),
      '异常剔除使用了后续可交易性信息，不能作为入场时已知的过滤条件。当前股票池回看及既有箱体股票子样本偏差仍存在。',
      '资金/逐笔损益已对账；最终210笔退出全部在B1—B3，无延迟退出。',
      '冻结清单：FROZEN_RULE.json。后续若审计边界后数据，应只报告冻结候选结果，不把该结果反馈调参。']
    (OUT/'固定规则与逐年收益.txt').write_text('\n'.join(lines),encoding='utf8')
    details=['代码 | 股票 | 信号日 | 买入日 | 买股数 | 买价 | 卖出日 | 原因 | 净损益 | 净收益率']
    for e in trades.sort_values(['buy_date','code']).itertuples():details.append(f'{e.code} | {e.name} | {e.signal_date} | {e.buy_date} | {e.buy_qty} | {e.buy_price:.2f} | {e.sell_date} | {e.reason} | {e.pnl:.2f} | {e.return_pct:.2%}')
    (OUT/'逐笔交易.txt').write_text('\n'.join(details),encoding='utf8')
    (OUT/'VERIFICATION.json').write_text(json.dumps(dict(cash_pnl_reconciled=True,exit_days_B1_to_B3=True,no_delayed_exit=True,
        train_proxy_not_presented_as_actual=True,development_selection_not_presented_as_OOS=True,
        frozen_rule_sha256=digest(OUT/'FROZEN_RULE.json')),indent=2),encoding='utf8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(12,4.7))
    axes[0].plot(pd.to_datetime(nav.date),(nav.equity/100000-1)*100,label='低价深超跌候选')
    oldnav=pd.read_parquet(ROOT/'results_v11_filtered_horizons/B3'/baseline['key']/'daily_nav.parquet')
    axes[0].plot(pd.to_datetime(oldnav.date),(oldnav.equity/100000-1)*100,label='原高准确率筛选器+B3',alpha=.8)
    axes[0].set_ylabel('累计账户收益（%）');axes[0].legend(fontsize=8);axes[0].grid(alpha=.15)
    years=[y['year'] for y in r['yearly']];x=list(range(4))
    axes[1].bar([a-.18 for a in x],[y['return_pct']*100 for y in baseline['yearly']],width=.36,label='原规则')
    axes[1].bar([a+.18 for a in x],[y['return_pct']*100 for y in r['yearly']],width=.36,label='研发候选')
    axes[1].set_xticks(x,years);axes[1].set_ylabel('年度收益（%）');axes[1].legend(fontsize=8);axes[1].grid(axis='y',alpha=.15)
    fig.suptitle('10万元5槽：固定低价深超跌候选\n2021—2024均参与规则筛选，此图为研发期结果，非独立盲测',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.88]);fig.savefig(OUT/'固定候选收益对比.png',dpi=140);plt.close(fig)
    print(OUT/'固定规则与逐年收益.txt')


if __name__=='__main__':main()
