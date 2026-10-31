"""Report whitelist-only continuation, without claiming context isolation."""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from study import ROOT,SOURCE,digest
from tune_pre2025_v3 import OUT,GRID,InputGuard


def main():
    guard=InputGuard();guard.install()
    m=json.loads((OUT/'summary.json').read_text(encoding='utf8'))
    audit=json.loads((OUT/'INPUT_ACCESS_AUDIT.json').read_text(encoding='utf8'))
    assert not audit['denied_actual_reads'] and not any('holdout_restricted' in x for x in audit['workspace_reads'])
    if m['winner'] is None:
        (OUT/'调参说明.txt').write_text('本轮没有满足既定改善条件的新候选，保留v2。只读边界内数据；不是独立盲测。',encoding='utf8');return
    w=m['winner'];c=w['config'];r=m['persisted_result'];b=m['baseline'];s=r['summary'];bs=b['summary']
    t=pd.read_parquet(OUT/r['key']/'trades.parquet');nav=pd.read_parquet(OUT/r['key']/'daily_nav.parquet')
    assert abs(100000+t.pnl.sum()-s['final_equity'])<.01 and t.buy_offset.between(1,c['forced_day']).all()
    assert not r['specials']
    freeze=dict(name='方向2_低价深超跌_10万5槽_B3_v3',status='FROZEN_RESEARCH_CANDIDATE_NOT_PRODUCTION',
        input_boundary='2024-12-31',calculation_guard='Posterior/restricted paths denied; explicit data allowlist and Parquet wrapper. Not an OS sandbox.',
        context_isolation=False,limitation='The parent conversation has seen posterior data; clean cognitive isolation cannot be claimed. No posterior files used by this calculation.',
        filters=dict(base='Same frozen basic oversold-bullish mainboard cohort and consecutive inferred-down-limit exclusion',
            raw_signal_close_lt=c['price'],adjusted_signal_close_div_MA20_lte=1-c['deviation']),
        account=dict(capital=100000,slots=c['slots'],fixed_slot_budget=100000/c['slots'],lot=100,T_plus_1=True,
            entry='Signal next official session open, user guaranteed-fill assumption',take_profit=c['take_profit'],
            forced_close_buy_offset=c['forced_day'],buy_day_offset=0,stop_loss=c['stop_loss'],priority='code ascending'),
        exclusions_are_ex_post=True,special_events_excluded=m['excluded_specials'],
        parameter_selection='All2021-2024 years participated; continued development, not independent validation.',
        neighborhood=w['neighborhood'],
        hashes={str(p.relative_to(ROOT.parent)):digest(p) for p in [ROOT/'account_backtest.py',ROOT/'tune_pre2025_v3.py',ROOT/'results_v5_long_position/events.parquet',SOURCE/'MANIFEST.json',OUT/'PROTOCOL.json']},
        summary_sha256=digest(OUT/'summary.json'))
    (OUT/'FROZEN_RULE.json').write_text(json.dumps(freeze,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：仅边界内数据的继续优化v3',
      '输入行情截止2024年底，计算未读取后验目录。父对话已看过后验，不能声称完全清洁的认知隔离或全新盲测。',
      '本轮方向来自后验之前的v15说明：MA20偏离8%和止盈6%位于网格边界，需扩边检查；没有使用后验指标、亏损股票或市场阶段来选择因子。',
      '本轮未调用后验代理、未读取其输出、未修改旧v2冻结文件。',
      '计算进程显式允许预2025白名单、边界内派生数据和旧v15研发结果；拒绝holdout_restricted路径，Parquet额外包裹检查。访问记录见INPUT_ACCESS_AUDIT.json。',
      '这是逻辑访问控制，不是操作系统沙箱；访问记录不能消除父上下文已经见过后验这一事实。',
      '', '候选网格：'+json.dumps(GRID,ensure_ascii=False),
      f"不同组合{m['candidates']}；符合每年正收益、每年至少10笔、全期回撤<=12%的有{m['qualified']}；逐年收益均不低于v2且全期回撤不更高的有{m['all_year_dominant']}。",
      '挑选准则沿用v15，优先最差年份及相邻参数稳定性，不以最新后验表现作为评分。',
      '', '冻结v3：',
      f"基础超跌转阳信号上，信号日原始收盘<{c['price']}元、前复权收盘/MA20<={1-c['deviation']:.2f}。不限龙头，不套原95%触及模型。",
      f"10万元、{c['slots']}槽，每槽固定{100000/c['slots']:.2f}元含买入费；下一正式交易日开盘，100股向下取整；代码顺序、现金/槽位约束不变。",
      f"B0买入当天不卖，B1起{c['take_profit']:.0%}止盈，否则B{c['forced_day']}收盘强平；价格止损{c['stop_loss']}。",
      '佣金万三最低5元及历史过户/印花税不变；原始股数、分红现金应收/支付和送转上市记账不变。',
      '', '研发期逐年结果（2021—2024全部参与选择，不是独立验证）：',
      '年份 | v2收益 | v3收益 | v2年内回撤 | v3年内回撤 | v3年末权益 | v3年内买入笔数']
    for old,y in zip(b['yearly'],r['yearly']):
        n=r['yearly_trades'].get(str(y['year']),r['yearly_trades'].get(y['year'],0))
        lines.append(f"{y['year']} | {old['return_pct']:.2%} | {y['return_pct']:.2%} | {-old['max_drawdown']:.2%} | {-y['max_drawdown']:.2%} | {y['end_equity']:.2f} | {n}")
    nn=w['neighborhood']
    lines += ['',f"累计收益{bs['total_return']:.2%}→{s['total_return']:.2%}，年化{bs['annualized_return']:.2%}→{s['annualized_return']:.2%}，期末{s['final_equity']:.2f}。",
      f"全期最大回撤{-bs['max_drawdown']:.2%}→{-s['max_drawdown']:.2%}，基本相同，部分年内回撤上升。",
      f"成交{s['trades']}笔：8%止盈{s['takeprofit']}笔、强平{s['forced']}笔；净盈利比例{s['net_win_rate']:.2%}。",
      f"相邻{nn['n']}组均四年正收益；相邻组合最差年度收益中位数{nn['median_worst_year']:.2%}，范围{nn['min_worst_year']:.2%}—{nn['max_worst_year']:.2%}。邻域也属于同一研发数据，不能当独立验证。",
      '止盈8%仍在扩展网格上边界，单价8元/5槽也位于局部网格边界，不能声称全局最优。',
      '', '公平性和适用范围：',
      'v2在完全相同事后异常排除口径下重跑，期末与旧v2差'+str(b['summary']['final_equity']-m['baseline_original']['summary']['final_equity'])+'元。',
      '异常排除清单：'+json.dumps(m['excluded_specials'],ensure_ascii=False),
      '这些排除含买入后可交易性信息，不是当时可知筛选条件。池子仍为既有947股回溯样本，不是全沪深历史普查；保证成交是用户指定理想条件。',
      '本轮计算没有读取或使用2025—2026后验文件，不能根据本轮研发曲线推论边界后表现。',
      '仅冻结研发候选，未修改生产选择、查看器或其他策略，也未启动新的行情更新器。']
    (OUT/'调参说明.txt').write_text('\n'.join(lines),encoding='utf8')
    detail=['代码 | 股票 | 信号日 | 买入日 | 买股数 | 买价 | 卖出日 | 原因 | 净损益 | 净收益率']
    for e in t.sort_values(['buy_date','code']).itertuples():detail.append(f'{e.code} | {e.name} | {e.signal_date} | {e.buy_date} | {e.buy_qty} | {e.buy_price:.2f} | {e.sell_date} | {e.reason} | {e.pnl:.2f} | {e.return_pct:.2%}')
    (OUT/'逐笔交易.txt').write_text('\n'.join(detail),encoding='utf8')
    (OUT/'VERIFICATION.json').write_text(json.dumps(dict(cash_pnl_reconciled=True,no_delayed_exit=True,
        all_exits_within_horizon=True,posterior_paths_in_calculation_log=False,
        context_isolation_claimed=False,baseline_equity_unchanged=abs(b['summary']['final_equity']-m['baseline_original']['summary']['final_equity'])<.01,
        source_engine_sha256=digest(ROOT/'account_backtest.py')),indent=2),encoding='utf8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    oldnav=pd.read_parquet(OUT/'baseline_common'/b['key']/'daily_nav.parquet')
    fig,axes=plt.subplots(1,2,figsize=(12,4.7))
    for name,frame in [('v2',oldnav),('v3',nav)]:axes[0].plot(pd.to_datetime(frame.date),(frame.equity/100000-1)*100,label=name,lw=1.2)
    axes[0].set_ylabel('累计账户收益（%）');axes[0].legend();axes[0].grid(alpha=.16)
    x=list(range(4))
    axes[1].bar([a-.18 for a in x],[y['return_pct']*100 for y in b['yearly']],width=.36,label='v2')
    axes[1].bar([a+.18 for a in x],[y['return_pct']*100 for y in r['yearly']],width=.36,label='v3')
    axes[1].set_xticks(x,[y['year'] for y in r['yearly']]);axes[1].set_ylabel('年度收益（%）');axes[1].legend();axes[1].grid(axis='y',alpha=.16)
    fig.suptitle('仅2024年底前输入：v2与v3研发期比较\n所有展示年份参与调参；当前上下文已见后验，不声称干净隔离或独立盲测',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.88]);fig.savefig(OUT/'研发期收益对比.png',dpi=140);plt.close(fig)
    assert not guard.denied
    (OUT/'REPORT_INPUT_AUDIT.json').write_text(json.dumps(dict(reads=sorted(guard.reads),parquet_reads=sorted(guard.parquet_reads),denied=guard.denied),ensure_ascii=False,indent=2),encoding='utf8')
    print(OUT/'调参说明.txt')


if __name__=='__main__':main()
