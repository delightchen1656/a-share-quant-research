"""All trading-day starts in one month, three fixed execution profiles."""
from pathlib import Path
import argparse
import pandas as pd
import engine as e
from compare_cost_profiles import HOME, read, write, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--month',required=True)
    args=parser.parse_args()
    snapshot=args.snapshot.resolve()
    assert snapshot.is_relative_to(HOME/'results/holdout_restricted')
    source_work=snapshot/'runtime_inputs'
    original=read(snapshot/'original_cost_summary.json')
    target=original['end']
    out=HOME/'results/holdout_restricted'/('month_'+args.month.replace('-','')+'_to_'+target.replace('-','')+'_three_profiles')
    out.mkdir(parents=True,exist_ok=True)
    work=out/'runtime_inputs';work.mkdir(exist_ok=True)
    assert not list((HOME.parents[1]/'K线数据/更新备份与审计').rglob('*.lock'))
    assert sha(HOME/'supermind_hushen_1.py')==read(snapshot/'RUN_STARTED.json')['strategy_sha256']
    # Isolated runtime outputs; original snapshot ranks/calendar remain unchanged.
    for name in ['inputs.json','rankings_original.json','calendar.parquet']:
        (work/name).write_bytes((source_work/name).read_bytes())
    write(out/'RUN_STARTED.json',dict(month=args.month,end=target,initial_cash=100000,
          source_snapshot=str(snapshot),input_sha256=sha(work/'inputs.json'),
          ranking_sha256=sha(work/'rankings_original.json'),policy=read(HOME/'backtest/cash_cost_policy.json'),
          entry_sha256=sha(HOME/'supermind_hushen_1.py'),engine_sha256=sha(HOME/'backtest/engine.py'),ledger_sha256=sha(HOME/'backtest/ledger.py')))
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=target)
    code=(HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    market=e.Market()
    market.actions.own=work/'additional_actions.json'
    market.actions.extra=read(source_work/'additional_actions.json') if (source_work/'additional_actions.json').exists() else {}
    market.actions.cache.update(market.actions.extra)
    starts=market.dates[market.dates.strftime('%Y-%m')==args.month]
    assert len(starts) and starts[-1]<=pd.Timestamp(target)
    profiles=[('原口径','strict_daily_limits',None),('仅滑点0.2%','strict_daily_limits',{'SLIP_ONE_SIDE':.002}),('统一现金与成本','unified_cash_cost',None)]
    results=[]
    try:
        for name,scenario,params in profiles:
            for d in starts:
                result,account=e.simulate(market,str(d.date()),target,scenario=scenario,initial=100000,params=params,
                                          save=name+'_'+str(d.date()))
                assert result['unresolved_actions']==result['reference_differences']==0
                assert abs(account.curve[-1]['equity']-result['final_equity'])<1e-7
                result['profile']=name
                results.append(result)
                pd.DataFrame(results).to_csv(out/'all_starts.csv',index=False,encoding='utf-8-sig')
            print('PROFILE COMPLETE',name,len(starts),flush=True)
    finally:market.actions.close()
    frame=pd.DataFrame(results)
    summaries=[]
    for name,_,_ in profiles:
        z=frame.loc[frame.profile.eq(name)]
        row=dict(profile=name,starts=len(z),best_start=z.loc[z.cagr.idxmax(),'actual_start'],worst_start=z.loc[z.cagr.idxmin(),'actual_start'])
        for k in ['final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost','average_exposure']:
            row[k+'_mean']=float(z[k].mean())
        for k in ['cagr','max_drawdown','sharpe']:
            row[k+'_min']=float(z[k].min());row[k+'_max']=float(z[k].max());row[k+'_std']=float(z[k].std(ddof=1))
        summaries.append(row)
    write(out/'summary.json',summaries)
    pd.DataFrame(summaries).to_csv(out/'summary.csv',index=False,encoding='utf-8-sig')
    lines=['# 沪深1月度全交易日起点三口径分布','',f'{args.month}共{len(starts)}个独立起点，每个初始10万元，统一至{target}。原四因子、5只目标、98%、20交易日全局相位不变。','',
           '| 指标 | '+' | '.join(x[0] for x in profiles)+' |','|---|---:|---:|---:|']
    for label,key,fmt in [('平均期末资产','final_equity_mean','money'),('平均累计收益','total_return_mean','pct'),('平均年化','cagr_mean','pct'),('最差起点年化','cagr_min','pct'),('最好起点年化','cagr_max','pct'),('平均最大回撤','max_drawdown_mean','pct'),('最严重回撤','max_drawdown_max','pct'),('平均Sharpe','sharpe_mean','number'),('平均成交笔数','trades_mean','number'),('平均总成本含股息税','total_cost_mean','money'),('平均仓位','average_exposure_mean','pct')]:
        vals=[r[key] for r in summaries]
        lines.append('| '+label+' | '+' | '.join(f'{v:.2%}' if fmt=='pct' else f'{v:,.2f}' if fmt=='money' else f'{v:.3f}' for v in vals)+' |')
    lines+=['','平均值为各独立起点指标的算术平均，不是合并账户收益；回撤为各账户各自路径的最大回撤。',
            '原口径：滑点0.1%，卖出款当天可用，原历史税费；仅滑点组仅改为0.2%；统一组滑点0.2%、卖出款下一交易日可用、卖出印花税固定0.1%、无单列过户费。三组佣金均万三最低5元；股息税沿原FIFO规则。',
            '日线近似撮合，滑点受原价格范围、限价与涨跌停约束；末日未强制平仓。该结果是后边界回放，不参与研发选参。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    assert len(frame)==len(starts)*3 and not frame[['final_equity','cagr','max_drawdown','sharpe']].isna().any().any()
    write(out/'RUN_COMPLETE.json',dict(status='complete',starts_per_profile=len(starts),paths=len(frame),summary_sha256=sha(out/'summary.json'),all_starts_sha256=sha(out/'all_starts.csv')))
    print(pd.DataFrame(summaries).to_string(index=False),flush=True)
    print('COMPLETE',out,flush=True)


if __name__=='__main__':main()
