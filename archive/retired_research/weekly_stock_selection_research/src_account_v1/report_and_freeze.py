import json
import datetime
import shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import BASE,AUDIT,SPEC,sha,dump,fee,install_development_guard
from portfolio import Quotes
from execution import plan_buy
from account_validation import aggregate


def main():
    install_development_guard()
    summary=pd.read_parquet(AUDIT/'summary.parquet')
    annual=pd.read_parquet(AUDIT/'annual.parquet')
    daily=pd.read_parquet(AUDIT/'daily_nav.parquet')
    plans=pd.read_parquet(AUDIT/'preopen_plans.parquet')
    tx=pd.read_parquet(AUDIT/'transactions.parquet')
    scores=pd.read_parquet(AUDIT/'scores.parquet')
    quotes=Quotes()
    # Audit all pre-auction cash buckets against previous close cash and
    # signal-close NAV, not against Monday closing prices or later fills.
    for (method,date),g in plans.groupby(['method','date'],sort=False):
        history=daily.loc[daily.method.eq(method)&daily.date.lt(date)]
        before_cash=float(history.cash.iloc[-1]) if len(history) else 1e6
        prior_holdings=set(history.holdings.iloc[-1].split(';'))-{''} if len(history) else set()
        selected=scores.loc[scores.method.eq(method)&scores.monday.eq(date)].sort_values('rank')
        expected=[s for s in selected.symbol if s not in prior_holdings][:10-len(prior_holdings)]
        assert g.symbol.tolist()==expected
        signal=selected.signal_date.iloc[0]
        signal_nav=daily.loc[daily.method.eq(method)&daily.date.eq(signal),'equity']
        target=float(signal_nav.iloc[0])/10 if len(signal_nav) else 1e5
        remaining=before_cash
        for row in g.itertuples():
            budget=min(target,remaining)
            remaining-=budget
            assert abs(row.budget-budget)<1e-6
            i=quotes.days.get_loc(pd.Timestamp(date))
            b=quotes.bar(row.symbol,i)
            p=quotes.bar(row.symbol,i-1)
            order,reason=plan_buy(b,budget,p['volume'] if p['active'] else 0,pd.Timestamp(date))
            if order:
                assert row.qty==order['qty'] and row.limit_price==order['limit_price']
                assert row.qty*row.limit_price+fee(row.qty*row.limit_price,'buy',date)<=budget+1e-6
            else:
                assert row.qty==0 and row.reason==reason
        assert remaining>=-1e-6
    for method in summary.method:
        d=daily.loc[daily.method.eq(method)]
        _,recalc=aggregate(d)
        old=summary.loc[summary.method.eq(method)].iloc[0]
        np.testing.assert_allclose([recalc[k] for k in ['cagr','cumulative_return','maximum_drawdown']],
                                  [old[k] for k in ['cagr','cumulative_return','maximum_drawdown']],atol=1e-12)
    dump(AUDIT/'full_preopen_plan_validation.json',dict(passed=True,all_budget_buckets_replayed=True,
        all_quantities_replayed_without_final_open_prices=True,all_top10_and_old_position_slots_checked=True,
        cash_reservation_checked=True,calendar_year_CAGR_origin_generalized_for_audit=True,
        generalization_does_not_change_any_development_metric=True))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[3,1]})
    names={'long120':'11因子＋120日动量','anchor11':'11因子基准','sse_timing_gross':'上证相同时点（毛）'}
    for method,color in [('long120','#b45d3c'),('anchor11','#477b9c'),('sse_timing_gross','#b39c3f')]:
        d=daily.loc[daily.method.eq(method)]
        curve=np.r_[1e6,d.equity.to_numpy()]
        dd=curve[1:]/np.maximum.accumulate(curve)[1:]-1
        axes[0].plot(pd.to_datetime(d.date),d.equity/1e6,label=names[method],color=color,lw=1.2)
        axes[1].plot(pd.to_datetime(d.date),dd*100,color=color,lw=1)
    axes[0].set_title('买卖规则V1开发回测：2021—2023逐年向前评分\n开盘前定量；扣交易费用、红利税前；日K条件成交代理，不是已认证集合竞价成交')
    axes[0].set_ylabel('账户净值（初始=1）')
    axes[1].set_ylabel('收盘回撤%')
    axes[0].legend(fontsize=9)
    for ax in axes:ax.grid(alpha=.2)
    fig.savefig(AUDIT/'account_nav.png',dpi=160)
    plt.close(fig)
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    lines=['周一选股买卖规则V1：开发账户回测',
        '固定规则：周一前一实际交易日收盘评分，原top10；周一开盘前按涨停减一档限价和费用确定整手数量并预留预算；周二收盘按跌停加一档限价尝试退出。失败预算不换股不分配，持仓受阻保留，下一开市周二重试。',
        '本次账户区间2021—2023，采用既有逐年向前评分：每年仅由此前成熟标签训练的历史模型产生分数。没有把2023年底最终模型倒用于早期，也没有新训练/调参。因子选择已经观察该开发区间，因此不是独立最终验证。',
        '本报告只含开发数据，未读取后验成绩。后验账户回测须冻结本引擎，再由原独立审计子代理单向执行。',
        '初始100万元，最多10只，新仓预算信号净值10%，包含费用；100股整数手，无融资，闲置现金不计息，零滑点是研究假设。',
        '结果扣佣金（双边万三最低5元）、相应日期过户费及卖出印花税；现金/送股红利仍为个人差别化红利税前口径。',
        '注意：日K开/收盘价并不证明集合竞价有成交深度或撤单及时。涨跌停按历史日期/ST/参考价条件重建，未获得逐日官方价格界限认证。表内是条件账户估算，不是已证实实盘可实现收益。',
        '', '累计/年化/收盘最大回撤']
    for r in summary.itertuples():
        lines.append(f'{names[r.method]} | 累计{r.cumulative_return:+.2%} | 复合年化{r.cagr:+.2%} | 全程最大回撤{r.maximum_drawdown:.2%} | 期末{r.end_equity:.2f}元 | 条件记账完整{r.conditional_account_complete}')
    lines+=['','逐年：收益、该年收盘最大回撤、年末资金']
    for r in annual.itertuples():
        lines.append(f'{names[r.method]} {r.year} | {r.annual_return:+.2%} | {r.maximum_drawdown:.2%} | {r.end_equity:.2f}元')
    lines+=['','执行/资金占用']
    for r in summary.loc[summary.method.ne('sse_timing_gross')].itertuples():
        lines.append(f'{names[r.method]} | 买入{int(r.buys)}次 | 失败买入{int(r.cancelled_buys)}次 | 延迟退出持仓{int(r.delayed_trades)}笔 | 最长已平仓持有{int(r.longest_closed_calendar_hold)}自然日 | 交易费用{r.fees:.2f}元 | 期末未平仓{int(r.open_trades)}笔 | 平均日收盘持仓比例{r.average_close_exposure:.2%} | 已平仓胜率{r.closed_trade_win_rate:.2%}')
    lines += ['', '核验与限制',
        f'全部预开盘预算/数量、成交数量和费用可核对。两账户从成交与公司行动原始记录独立重放现金、上市/未上市股份和应收款，与每日净值一致。已核验{len(collection["sources"])}个持有股票-年份原始查询；供应商记录成功并不等于完整经济台账认证。',
        '分红支付只有日期、没有入账时刻，保守视为支付日收盘可用，不拿当天分红去参与早盘买入。',
        '全部结果未对不可成交信号事后删股；送转按登记、除权、现金支付、红股上市分别记账。未核实的参考价变化/价格界限矛盾保留异常，不假装已核准。当前两账户未触发未解决异常。',
        '逐笔普通标签均值与账户收益不同：实际整手/预算、费用、空闲现金、退出受阻和股东权益会改变净值。',
        '上证为相同时点零费用指数点位毛参照，不是股票账户或可直接交易产品，资产和费用口径不同。',
        '当年最大回撤按该年初资金重置峰值；全程最大回撤跨年计算。均为日收盘净值回撤，不包含日内最大风险。',
        '历史退市覆盖及数据版本修订尚未完整核实；交易参数在账户结果前登记，本轮没有新增止损、止盈、仓位或因子搜索。',
        '', '文件：summary.parquet、annual.parquet、daily_nav.parquet、trades.parquet、transactions.parquet、preopen_plans.parquet、execution_log.parquet；account_nav.png为曲线。']
    (AUDIT/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    frozen=AUDIT/'frozen_engine_v1'
    assert not frozen.exists()
    frozen.mkdir()
    for name in ['execution.py','portfolio.py','account_validation.py','company_data.py']:
        shutil.copy2(Path(__file__).with_name(name),frozen/name)
    common=Path(__file__).with_name('common.py').read_text(encoding='utf-8')
    common=common.replace('BASE=Path(__file__).resolve().parent.parent',f'BASE=Path({str(BASE)!r})')
    common=common.replace("SPEC=json.loads((AUDIT/'spec.json').read_text(encoding='utf-8'))","SPEC=json.loads((Path(__file__).parent/'spec.json').read_text(encoding='utf-8'))")
    (frozen/'common.py').write_text(common,encoding='utf-8')
    shutil.copy2(AUDIT/'spec.json',frozen/'spec.json')
    shutil.copy2(BASE/'audits/holdout_restricted/monday_trading_rules_v1/RULES.json',frozen/'RULES.json')
    dump(frozen/'AUDIT_PROTOCOL.json',dict(
        audit_type='Additional account posthoc evaluation on previously used stock period, not fresh independent blind test.',
        quote_inputs='Original auditor same2025-2026raw stock/index/calendar snapshot and exact cutoff. No refreshed or extended market prices.',
        factor_models='Use both files from monday_factor_v5/frozen_exploratory_requested_v1; baseline=11factor and candidate=11factor+120day. Manifest sha81d0ea7fd52dee7722b9522e82de61c1cb2c7a9f19f5648993f8cf6910e17e25. No retraining.',
        runtime='Import frozen common/portfolio/execution/account_validation/company_data. Pass explicit quote object, weekly schedule, auditstart/end to simulate. Outputs all to new audit directory; never call development main scripts or guard installer in audit role.',
        corporate_evidence='Independent held stock-year provider evidence required before valid PnL; provider raw cache ONLY in audit output, never inputs_pre2025. Use initialize(store_path) in query worker, normalize(records,quotes=future_quotes,store=audit_cache). Iteratively inventory held-years without publishing PnL until supported.',
        historical_bands='Fixed date-specific ST5%before2026-07-06and10%fromthatdate; ordinary10%. Verify primary rule sources/effective date. Observed high/low contradictions and unknown references remain failures, not strategy edits.',
        validation='Run original synthetic checks or equivalent, independent_account for all actual days, full budget-reservation and planned-quantity replay, actual model/engine hashes before/after. Company action quantity/listing/payment independent. Missing row not assumed suspension.',
        metrics='Initial1millionCNY, per-year and full cumulative/CAGR/closeMDD, fees, idle/exposure, failed orders, delayed positions and terminal inventory. Personal dividend withholding beforetax. Conditional daily OHLC fills only, no auction depth/queue proof.',
        rule_freeze='No factor/parameter/capacity/stop or candidate tuning; any engineering repair must preserve original and logs, not conceal or optimize return.',
        return_firewall='Write complete report and PNGtables/curves in audit output. Parent receives only status and report/image paths, never numbers, ranking or advice; no output images forwarded into optimizer context.'))
    files=[p for p in frozen.iterdir() if p.is_file()]
    dump(frozen/'FREEZE_MANIFEST.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        after_development_account_validation_before_account_posterior=True,
        rules_sha256=SPEC['rules_sha256'],files=[dict(path=p.name,sha256=sha(p)) for p in sorted(files)]))
    dump(AUDIT/'ARTIFACTS.json',dict(only_pre2024_account_results=True,no_posterior_reads=True,
        files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted([p for p in AUDIT.iterdir() if p.is_file() and p.name!='ARTIFACTS.json']+list((BASE/'src_account_v1').glob('*.py')))]))
    print('REPORT:',AUDIT/'REPORT.txt',flush=True)
    print('FROZEN_ENGINE_SHA256:',sha(frozen/'FREEZE_MANIFEST.json'),flush=True)


if __name__=='__main__':
    from pathlib import Path
    main()
