"""Report and freeze tuned v2 with development-selection and cleanup caveats."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from study import ROOT,SOURCE,digest
from tune_fixed_income import OUT,GRID,config_key


def main():
    m=json.loads((OUT/'summary.json').read_text(encoding='utf8'));c=m['winner']['config'];r=m['persisted_result'];s=r['summary'];b=m['baseline']
    rows=json.loads((OUT/'comparison.json').read_text(encoding='utf8'));lookup={config_key(x['config']):x for x in rows}
    neighbors=[]
    for field,values in GRID.items():
        j=values.index(c[field])
        for k in [j-1,j+1]:
            if 0<=k<len(values):
                other=dict(c);other[field]=values[k];neighbors.append(lookup[config_key(other)])
    nn=m['winner']['neighborhood'];nn['min_max_drawdown']=min(-x['result']['summary']['max_drawdown'] for x in neighbors);nn['max_max_drawdown']=max(-x['result']['summary']['max_drawdown'] for x in neighbors)
    rule=dict(name='方向2_低价深超跌_10万7槽_B3_v2',status='FROZEN_RESEARCH_CANDIDATE_NOT_PRODUCTION',
        filters=dict(base='Same basic oversold-bullish signal and suspected-limit-streak exclusions',
                     raw_signal_close_lt=c['price'],adjusted_signal_close_div_MA20_lte=1-c['deviation']),
        account=dict(capital=100000,slots=c['slots'],fixed_slot_budget=100000/c['slots'],buy_lot_size=100,
          buy='Signal next official session open, guaranteed fill assumption',T_plus_1=True,
          take_profit=c['take_profit'],forced_close_buy_offset=c['forced_day'],buy_day_offset=0,
          stop_loss=c['stop_loss'],priority='code ascending; held stock not added; no future-proceeds opening reuse'),
        fees='Same commission .0003/min5 and historical stamp/transfer schedules',
        special_events_excluded=m['excluded_specials'],exclusions_are_ex_post=True,
        selection=dict(period='2021-2024 development, all years used for parameter selection',
          combinations=m['grid_count'],qualification='All annual returns>0, >=10 entries/year, total daily DD<=12%',
          actual_tier=m['selected_tier'],neighborhood=nn),
        hashes={str(p.relative_to(ROOT.parent)):digest(p) for p in [ROOT/'account_backtest.py',ROOT/'tune_fixed_income.py',ROOT/'verify_fixed_tuning.py',ROOT/'results_v5_long_position/events.parquet',SOURCE/'MANIFEST.json']},
        summary_sha256=digest(OUT/'summary.json'),production_changed=False,post2024_data_read=False)
    (OUT/'FROZEN_RULE.json').write_text(json.dumps(rule,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：低价深超跌固定候选v2，本轮参数优化',
      '仍只用截至2024年底数据。2021—2024全部参与参数选择，是研发期结果，不是独立盲测或已证实的未来收益。',
      f"本轮{m['grid_count']}组组合；合格{m['qualified']}组；四个年度收益均不低于旧候选且全期回撤不更高的有{m['all_year_dominant']}组。",
      '参数范围：'+json.dumps(GRID,ensure_ascii=False),
      '选法：每年正收益、每年至少10笔、全期回撤不超过12%；优先逐年收益不低于旧候选且全期回撤不更高，再按最低年度收益、累计收益、回撤排序；有稳定邻域时优先稳定邻域。',
      '不存在“所有参数训练于2021年之前”的说法。本轮是反复研发，已选择过这些年份，因此多重比较与过拟合风险不能靠邻域检查消除。',
      '', '冻结候选参数：',
      f"现有基础超跌转阳信号中，信号日未复权收盘<{c['price']}元，前复权收盘/MA20<={1-c['deviation']:.2f}；不限龙头、不使用原95%触及模型。",
      f"初始10万元，{c['slots']}槽，每槽固定{100000/c['slots']:.2f}元含买入费用；次日开盘买，100股向下取整；同日按代码排序、满槽跳过。",
      f"B0为买入当天不卖。B1起达到买价上方{c['take_profit']:.0%}止盈；未止盈则B{c['forced_day']}收盘强平；额外价格止损：{c['stop_loss']}。",
      '开盘越过目标按开盘卖。佣金万三最低5元及历史印花税/过户费、分红与送转的真实股数/支付记账维持原口径。',
      '', '同一异常排除口径，逐年实际账户结果：',
      '年份 | 原v1收益 | 新v2收益 | 原年内回撤 | 新年内回撤 | 新年末权益 | 新年内买入笔数']
    for a,y in zip(b['yearly'],r['yearly']):
        count=r['yearly_trades'].get(str(y['year']),r['yearly_trades'].get(y['year'],0))
        lines.append(f"{y['year']} | {a['return_pct']:.2%} | {y['return_pct']:.2%} | {-a['max_drawdown']:.2%} | {-y['max_drawdown']:.2%} | {y['end_equity']:.2f} | {count}")
    old=b['summary']
    lines += ['',f"累计收益：{old['total_return']:.2%}→{s['total_return']:.2%}；年化：{old['annualized_return']:.2%}→{s['annualized_return']:.2%}。",
      f"全期最大回撤：{-old['max_drawdown']:.6%}→{-s['max_drawdown']:.6%}，实质上都约10.12%，不能宣传为有意义的回撤下降。",
      f"期末{s['final_equity']:.2f}，成交{s['trades']}笔，6%止盈{s['takeprofit']}笔、强平{s['forced']}笔；净盈利交易比例{s['net_win_rate']:.2%}，旧候选{old['net_win_rate']:.2%}。",
      '止盈目标已从5%提高到6%，止盈笔数占比不能直接当成原40日+3%触及率进行比较。',
      '', '相邻参数检查（仍在同一研发数据内）：',
      f"检查{nn['n']}组单参数相邻组合，四年全为正收益的比例{nn['positive_year_fraction']:.2%}。",
      f"相邻组合最低年度收益中位数{nn['median_worst_year']:.2%}，范围{nn['min_worst_year']:.2%}至{nn['max_worst_year']:.2%}；全期回撤范围{nn['min_max_drawdown']:.2%}至{nn['max_max_drawdown']:.2%}。",
      '这是参数敏感性描述，不能当作独立检验或未来收益置信区间。',
      '', '异常样本与公平对照：',
      '排除事件：'+json.dumps(m['excluded_specials'],ensure_ascii=False),
      '较上一版新发现002069/2022-04-27到期缺价，按用户授权统一事后排除；旧v1在完全相同排除口径下已重跑，期末权益差为'+str(m['baseline_original_equity_difference'])+'元。',
      '该异常清理依据买入之后的报价可用性，不能作为买入前规则。保证成交仍是用户指定理想假设，不是市场容量验证。',
      '股票池仍为既有947股票回溯子样本，并非沪深主板全市场历史普查；不自动使用未来退市情况删股。',
      '未读取2025及之后的行情/后验结果；未修改查看器、生产选择或其他策略。旧冻结候选保留。',
      '逐笔账本已核验现金/盈亏一致、无延迟退出、退出全部不超过B3。FROZEN_RULE.json记录参数与代码/输入哈希。']
    (OUT/'调参结果与冻结规则.txt').write_text('\n'.join(lines),encoding='utf8')
    folder=OUT/r['key'];t=pd.read_parquet(folder/'trades.parquet');nav=pd.read_parquet(folder/'daily_nav.parquet')
    detail=['代码 | 股票 | 信号日 | 买入日 | 买股数 | 买价 | 卖出日 | 出场原因 | 净损益 | 净收益率']
    for e in t.sort_values(['buy_date','code']).itertuples():detail.append(f'{e.code} | {e.name} | {e.signal_date} | {e.buy_date} | {e.buy_qty} | {e.buy_price:.2f} | {e.sell_date} | {e.reason} | {e.pnl:.2f} | {e.return_pct:.2%}')
    (OUT/'逐笔交易.txt').write_text('\n'.join(detail),encoding='utf8')
    assert abs(100000+t.pnl.sum()-s['final_equity'])<.01
    assert t.buy_offset.between(1,c['forced_day']).all()
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    oldnav=pd.read_parquet(OUT/'baseline_common'/b['key']/'daily_nav.parquet')
    fig,axes=plt.subplots(1,2,figsize=(12,4.7))
    for label,frame in [('v1原候选',oldnav),('v2调参候选',nav)]:axes[0].plot(pd.to_datetime(frame.date),(frame.equity/100000-1)*100,label=label,lw=1.2)
    axes[0].set_ylabel('累计账户收益（%）');axes[0].legend(fontsize=9);axes[0].grid(alpha=.16)
    x=list(range(4))
    axes[1].bar([a-.18 for a in x],[y['return_pct']*100 for y in b['yearly']],width=.36,label='v1')
    axes[1].bar([a+.18 for a in x],[y['return_pct']*100 for y in r['yearly']],width=.36,label='v2')
    axes[1].set_xticks(x,[y['year'] for y in r['yearly']]);axes[1].set_ylabel('年度收益（%）');axes[1].legend();axes[1].grid(axis='y',alpha=.16)
    fig.suptitle('10万元：5槽/5%止盈/深超跌10% → 7槽/6%止盈/深超跌8%\n2021—2024均参与调参；研发期结果，非独立盲测',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.88]);fig.savefig(OUT/'调参前后收益对比.png',dpi=140);plt.close(fig)
    print(OUT/'调参结果与冻结规则.txt')


if __name__=='__main__':main()
