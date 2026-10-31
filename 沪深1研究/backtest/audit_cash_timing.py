"""Single-variable settlement experiment with daily cash and fill evidence."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
import engine as e
from compare_cost_profiles import HOME, read, write, sha


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--start-quarter',default=None,help='For example 2020Q1; default January 2025')
    args=parser.parse_args()
    snapshot=args.snapshot.resolve()
    assert snapshot.is_relative_to(HOME/'results/holdout_restricted')
    target=read(snapshot/'summary.json')['end']
    start_scope=args.start_quarter or 'jan2025'
    out=HOME/'results/holdout_restricted'/('cash_timing_only_'+start_scope+'_to_'+target.replace('-',''))
    out.mkdir(parents=True,exist_ok=True)
    work=out/'runtime_inputs';work.mkdir(exist_ok=True)
    assert not list((HOME.parents[1]/'K线数据/更新备份与审计').rglob('*.lock'))
    assert sha(HOME/'supermind_hushen_1.py')==read(snapshot/'RUN_STARTED.json')['strategy_sha256']
    for f in ['inputs.json','rankings_original.json','calendar.parquet']:
        (work/f).write_bytes((snapshot/'runtime_inputs'/f).read_bytes())
    policy=read(HOME/'backtest/cash_cost_policy.json')
    write(out/'PROTOCOL_BEFORE_RUN.json',dict(start_scope=start_scope,end=target,initial_cash=100000,
          identical_costs=policy,only_account_difference='settle_sale_next_session=False versus True',
          source_sha256=sha(HOME/'supermind_hushen_1.py'),engine_sha256=sha(HOME/'backtest/engine.py'),
          ledger_sha256=sha(HOME/'backtest/ledger.py'),ranking_sha256=sha(work/'rankings_original.json')))
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=target)
    code=(HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    market=e.Market();market.actions.own=work/'additional_actions.json'
    previous=snapshot/'runtime_inputs/additional_actions.json'
    market.actions.extra=read(previous) if previous.exists() else {}
    market.actions.cache.update(market.actions.extra)
    original=e.Account
    mode={'next_session':False}

    class AuditedAccount(original):
        def __init__(self,*a,**kw):
            self.fill_cash_audit=[];self.day_audit=[];self.release_audit=[]
            super().__init__(*a,**kw)
            self.settle_sale_next_session=mode['next_session']
            assert self.no_transfer_fee and self.fixed_stamp_rate==.001
            assert self.m.SLIP_ONE_SIDE==.002 and self.commission_rate==.0003 and self.minimum_commission==5
        def corporate(self):
            due=[(d,v) for d,v in self.receivables if d<=self.date]
            cash_before=self.cash
            super().corporate()
            assert self.cash>=cash_before+sum(v for d,v in due)-1e-7
            self.release_audit.append(dict(date=str(self.date.date()),cash_before=cash_before,
                due_released=sum(v for d,v in due),cash_after=self.cash))
        def order(self,s,qty,price=None):
            cash_before=self.cash;pending_before=sum(v for d,v in self.receivables)
            count=len(self.trades)
            result=super().order(s,qty,price)
            if len(self.trades)>count:
                t=self.trades[-1];gross=round(abs(t['qty'])*t['price'],2)
                assert t['commission']==round(max(5,gross*.0003),2)
                assert t['stamp']==(round(gross*.001,2) if qty<0 else 0)
                assert t['transfer']==0
                net=gross-sum(t[k] for k in ['commission','transfer','stamp','dividend_tax'])
                pending_after=sum(v for d,v in self.receivables)
                if qty<0 and self.settle_sale_next_session:
                    assert abs(self.cash-cash_before)<1e-7
                    assert abs(pending_after-pending_before-net)<1e-7
                    assert self.receivables[-1][0]>self.date
                elif qty<0:assert abs(self.cash-cash_before-net)<1e-7
                else:
                    assert self.cash>=-1e-7 and gross+t['commission']<=cash_before+1e-7
                self.fill_cash_audit.append(dict(t,cash_before=cash_before,cash_after=self.cash,
                    pending_before=pending_before,pending_after=pending_after))
            return result
        def step(self,date,index,prev,ranks):
            rebalance=self.m.g.alpha_first or (index-1)%20==0
            super().step(date,index,prev,ranks)
            point=self.curve[-1]
            pending=sum(v for d,v in self.receivables)
            assert abs(point['equity']-self.cash-point['market_value']-pending)<1e-7
            self.day_audit.append(dict(date=str(date.date()),rebalance=rebalance,cash=self.cash,
                pending=pending,equity=point['equity'],market_value=point['market_value'],
                targets=dict(self.m.g.alpha_targets),holdings={s:p['qty'] for s,p in self.holdings.items()}))

    e.Account=AuditedAccount
    if args.start_quarter:
        period=pd.Period(args.start_quarter,freq='Q')
        starts=market.dates[(market.dates>=period.start_time)&(market.dates<=period.end_time)]
    else:starts=market.dates[market.dates.strftime('%Y-%m')=='2025-01']
    assert len(starts)>0
    results=[];paths={};daily=[];fills=[];releases=[]
    try:
        for name,next_session in [('same_day',False),('next_session',True)]:
            mode['next_session']=next_session
            for d in starts:
                start=str(d.date())
                r,a=e.simulate(market,start,target,scenario='unified_cash_cost',initial=100000,save=name+'_'+start)
                assert r['unresolved_actions']==r['reference_differences']==0
                r['cash_mode']=name;results.append(r)
                paths[name,start]=a.day_audit
                daily.extend(dict(x,cash_mode=name,start=start) for x in a.day_audit)
                fills.extend(dict(x,cash_mode=name,start=start) for x in a.fill_cash_audit)
                releases.extend(dict(x,cash_mode=name,start=start) for x in a.release_audit)
                pd.DataFrame(results).to_csv(out/'all_starts.csv',index=False,encoding='utf-8-sig')
            print('CASH MODE COMPLETE',name,len(starts),flush=True)
    finally:market.actions.close()
    frame=pd.DataFrame(results)
    pd.DataFrame(fills).to_parquet(out/'fill_cash_audit.parquet',index=False)
    pd.DataFrame(releases).to_parquet(out/'cash_releases.parquet',index=False)
    # JSON retains exact target and holdings dictionaries for replay diagnosis.
    write(out/'daily_account_audit.json',daily)
    rows=[]
    for name,z in frame.groupby('cash_mode',sort=False):
        row=dict(cash_mode=name,starts=len(z))
        for k in ['final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost','average_exposure']:
            row[k+'_mean']=float(z[k].mean())
        rows.append(row)
    write(out/'summary.json',rows)
    # Verify delayed mode reproduces the earlier uniform-cost experiment.
    prior_reproduced=None
    if not args.start_quarter:
        previous_runs=read(HOME/'results/holdout_restricted/month_202501_to_20261028_three_profiles/summary.json')
        expected=next(x for x in previous_runs if x['profile']=='统一现金与成本')
        delay=next(x for x in rows if x['cash_mode']=='next_session')
        for k in ['final_equity_mean','cagr_mean','max_drawdown_mean','sharpe_mean']:
            assert np.isclose(delay[k],expected[k],rtol=0,atol=1e-8),k
        prior_reproduced=True
    divergences=[]
    for d in starts:
        start=str(d.date());p=paths['same_day',start];q=paths['next_session',start]
        assert len(p)==len(q)
        for a,b in zip(p,q):
            if a['holdings']!=b['holdings']:
                divergences.append(dict(start=start,date=a['date'],same_day=a,next_session=b))
                break
    write(out/'FIRST_HOLDING_DIVERGENCES.json',divergences)
    first=divergences[0]
    selected=[x for x in fills if x['start']==first['start'] and x['date']>=pd.Timestamp(first['date']) and x['date']<=pd.Timestamp(first['date'])+pd.Timedelta(days=7)]
    pd.DataFrame(selected).to_csv(out/'first_divergence_week_fills.csv',index=False,encoding='utf-8-sig')
    # Holding-count comparison is a diagnostic, not a strategy alteration.
    write(out/'AUDIT_COMPLETE.json',dict(status='passed',paths=len(frame),starts=len(starts),
        filled_orders_checked=len(fills),cash_releases_checked=len(releases),daily_nav_identities_checked=len(daily),
        delayed_mode_reproduces_prior=prior_reproduced,first_holdings_divergence=first,
        possible_untraded_targets='Retained and retried through the unmodified original handle_bar loop',
        protocol_sha256=sha(out/'PROTOCOL_BEFORE_RUN.json')))
    lines=['# 沪深1：只改变卖出款可用时间','',f'{start_scope}全部{len(starts)}交易日起点，每个10万元，截止{target}。',
      '两组相同：0.2%滑点、佣金万三最低5元、卖出印花税0.1%、无单列过户费、原FIFO股息税、原选股/调仓/仓位/减股数/容量。唯一差异是卖出净款当天或下一交易日可用。','',
      '| 指标 | 当天可用 | 下一交易日可用 |','|---|---:|---:|']
    for label,k,fmt in [('平均期末资产','final_equity_mean','money'),('平均累计收益','total_return_mean','pct'),('平均年化','cagr_mean','pct'),('平均最大回撤','max_drawdown_mean','pct'),('平均Sharpe','sharpe_mean','num'),('平均成交笔数','trades_mean','num'),('平均总成本含股息税','total_cost_mean','money'),('平均仓位','average_exposure_mean','pct')]:
        lines.append('| '+label+' | '+' | '.join(f'{r[k]:.2%}' if fmt=='pct' else f'{r[k]:,.2f}' if fmt=='money' else f'{r[k]:.3f}' for r in rows)+' |')
    lines+=['',f"首个起点{first['start']}的首次持仓分化日为{first['date']}，详见FIRST_HOLDING_DIVERGENCES.json及first_divergence_week_fills.csv。",'',
      '逐笔验证：卖出净款计入待结算应收且不增加同日现金；次交易日开盘前释放；买入不得超可用现金；净值=现金+股票市值+待结算应收。',
      '各起点平均为算术平均。日线近似撮合；不作为独立盲测或未来收益保证。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(summary=rows,first_divergence=first),ensure_ascii=False),flush=True)
    print('COMPLETE',out,flush=True)


if __name__=='__main__':main()
