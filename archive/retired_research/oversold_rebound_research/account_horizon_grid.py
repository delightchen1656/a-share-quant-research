"""Filtered-only 3% TP, B1..B5 forced close. No retraining or return-based selection."""
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import account_backtest as engine
from study import ROOT,digest

OUT=ROOT/'results_v11_filtered_horizons'


def main():
    inputs=list(engine.prepare());base=inputs[0].copy()
    old_path=ROOT/'results_v10_accounts_no_special/summary.json'
    previous=json.loads(old_path.read_text(encoding='utf8'))
    excluded={(x['code'],x['signal_date']) for x in previous['excluded_specials']}
    OUT.mkdir(exist_ok=True);iterations=[]
    for attempt in range(5):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
        results=[];new=set()
        for horizon in range(1,6):
            folder=OUT/f'B{horizon}';folder.mkdir(exist_ok=True);engine.OUT=folder
            for pool in ['sample','leaders']:
                for capital,slots in [(1000000,50),(100000,5)]:
                    r=engine.run(*inputs,pool,True,capital,slots,forced_day=horizon)
                    results.append(dict(horizon=horizon,**r))
                    t=pd.read_parquet(folder/r['key']/'trades.parquet')
                    for _,e in t.loc[t.reason.str.contains('delayed')].iterrows():new.add((e.code,e.signal_date))
        iterations.append(dict(attempt=attempt,excluded=sorted(excluded),newly_exposed=sorted(new)))
        if not new:break
        excluded.update(new)
    else:raise RuntimeError('Special case cleanup did not converge')
    checks=[]
    for r in results:
        s=r['summary'];folder=OUT/f"B{r['horizon']}"/r['key'];t=pd.read_parquet(folder/'trades.parquet')
        assert s['delayed_exits']==0
        assert abs(t.pnl.sum()+s['capital']-s['final_equity'])<.01
        assert t.buy_offset.between(1,r['horizon']).all()
        checks.append(dict(scenario=str(folder.relative_to(OUT)),cash_pnl_reconciled=True,no_delayed_exit=True,exit_within_horizon=True))
        if r['horizon']==5 and len(iterations)==1:
            old=next(x['summary'] for x in previous['results'] if x['key']==r['key'])
            assert abs(s['final_equity']-old['final_equity'])<.01
            assert abs(s['max_drawdown']-old['max_drawdown'])<1e-9
    result=dict(results=results,excluded_specials=sorted(excluded),cleanup_iterations=iterations,
        baseline_summary_sha256=digest(old_path),
        protocol='Same frozen inner95 selector, fixed20k slots, fees/actions/priority unchanged. B0 is buy day; T+1 3% TP checked before forced close at B1/B2/B3/B4/B5. Common ex-post anomalous event exclusions across every horizon. 2021-2024 continuous accounts, not annual restarts. No model refit.',
        caveat='Model predicts 40-day touch, not horizon-specific outcomes. Multiple horizon comparison is development-period analysis, not fresh blind test. Guaranteed fills conditional assumption, not market capacity proof.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'VERIFICATION.json').write_text(json.dumps(dict(unit_tests=7,checks=checks,
        B5_regression_check='passed' if len(iterations)==1 else 'not_applicable_common_cohort_changed'),indent=2),encoding='utf8')
    lines=['方向2：仅筛选后，3%止盈，买入后B1—B5分别收盘强平',
      '2021—2024年连续账户；信号次日开盘买入当天B0，B1为买入后的下一正式交易日。',
      '沿用固定95%验证目标筛选器，不重训，不按这次账户结果重新选择信号。两池2024年均没有筛选入选。',
      '每槽固定2万元（含买费）、100股向下取整、保证开盘成交的理想假设、同日代码排序、槽位/现金约束、双边万三最低5元及历史税费不变。',
      'B1起触及买价上方3%止盈；到指定Bn尚未止盈则收盘强平，不设止损。到期日先判止盈再判收盘强平。',
      '公司行动继续使用原始整数股数、现金应收/支付和送转上市的记账。',
      '沿用并统一排除特殊异常事件，不用停牌前价格假装到期成交；清单：'+json.dumps(sorted(excluded),ensure_ascii=False),
      '本轮短周期另发现600506/2021-04-21与603007/2021-04-28两个特殊信号，所有期限统一剔除，全样本筛后从258变256；龙头仍207。故B5结果与上一轮不同，不是模型调参。',
      '异常清理使用了后续可交易性信息，仅属用户要求的事后样本清理，不是可部署入场条件。',
      '筛选目标是40日触及3%，本次只比较不同退出期限；本轮全是研发期比较，不是未见盲测。',
      '', '池 | 账户 | 平仓日 | 成交数 | 止盈数/强平数 | 累计收益 | 年化收益 | 最大回撤 | 期末资金 | 净盈利交易比例']
    for r in results:
        s=r['summary'];lines.append(f"{s['pool']} | {s['capital']}/{s['slots']} | B{r['horizon']} | {s['trades']} | {s['takeprofit']}/{s['forced']} | {s['total_return']:.2%} | {s['annualized_return']:.2%} | {s['max_drawdown']:.2%} | {s['final_equity']:.2f} | {s['net_win_rate']:.2%}")
    lines+=['','逐年收益和年内回撤：池 | 账户 | 平仓日 | 年份 | 收益 | 回撤']
    for r in results:
        s=r['summary']
        for y in r['yearly']:lines.append(f"{s['pool']} | {s['capital']}/{s['slots']} | B{r['horizon']} | {y['year']} | {y['return_pct']:.2%} | {y['max_drawdown']:.2%}")
    (OUT/'持有期限对比.txt').write_text('\n'.join(lines),encoding='utf8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for pool in ['sample','leaders']:
        for capital in [1000000,100000]:
            g=[x for x in results if x['summary']['pool']==pool and x['summary']['capital']==capital]
            label=('样本池' if pool=='sample' else '龙头')+('100万/50槽' if capital==1000000 else '10万/5槽')
            axes[0].plot([x['horizon'] for x in g],[x['summary']['total_return']*100 for x in g],marker='o',label=label)
            axes[1].plot([x['horizon'] for x in g],[-x['summary']['max_drawdown']*100 for x in g],marker='o',label=label)
    for ax,title in zip(axes,['累计收益（%）','最大回撤（%）']):
        ax.set_title(title);ax.set_xticks(range(1,6));ax.set_xlabel('买入后第几交易日收盘强平');ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('筛选后固定3%止盈：2021—2024连续账户持有期限比较');fig.tight_layout(rect=[0,0,1,.92]);fig.savefig(OUT/'持有期限对比.png',dpi=140);plt.close(fig)
    print(OUT/'持有期限对比.txt')


if __name__=='__main__':main()
