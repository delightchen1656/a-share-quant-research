"""Descriptive uncertainty and attribution; not a multiple-search correction."""
import json, math
import numpy as np
import pandas as pd
import research as r

def main():
    folder=r.HERE/'runs';q=pd.read_parquet(folder/'start_2020-01-01_equity.parquet')
    t=pd.read_parquet(folder/'start_2020-01-01_trades.parquet')
    nav=q.equity.to_numpy();returns=nav/np.r_[100000.,nav[:-1]]-1
    rng=np.random.default_rng(r.Q['stats']['bootstrap_seed']);block=20;n=len(returns);boot=[]
    for _ in range(1000):
        ix=((rng.integers(0,n,size=math.ceil(n/block))[:,None]+np.arange(block)[None,:])%n).ravel()[:n]
        x=returns[ix];boot.append(x.mean()/x.std(ddof=1)*np.sqrt(252))
    peak=np.maximum.accumulate(np.r_[100000.,nav])[1:];dd=1-nav/peak
    underwater=dd>1e-12;longest=current=0
    for value in underwater:
        current=current+1 if value else 0;longest=max(longest,current)
    contribution=json.loads((folder/'start_2020-01-01_contribution.json').read_text(encoding='utf-8'))
    positive=sum(max(0,v) for v in contribution.values());top=list(contribution.items())[:10]
    years=[];previous=100000.
    for year,rows in q.groupby(q.date.dt.year):
        years.append(dict(year=int(year),net_return=float(rows.equity.iloc[-1]/previous-1)))
        previous=float(rows.equity.iloc[-1])
    benchmark=pd.read_parquet(r.BASE/'start_date_study/benchmark.parquet').set_index('date').close
    benchmark=pd.to_numeric(benchmark)
    br=benchmark.pct_change().reindex(q.date).to_numpy()
    coefficient=np.linalg.lstsq(np.column_stack([np.ones(n),br]),returns,rcond=None)[0]
    benchmark_return=float(benchmark.loc[q.date.iloc[-1]]/benchmark.loc[q.date.iloc[0]]-1)
    corr={}
    for s in ['development','selection','confirmation','evaluation']:
        curves={}
        for control in r.CONTROLS:
            file=folder/(s+'_'+control+'_equity.parquet')
            if file.exists():
                c=pd.read_parquet(file).set_index('date').equity
                curves[control]=c/np.r_[100000.,c.to_numpy()[:-1]]-1
        corr[s]=pd.DataFrame(curves).corr().to_dict()
    result=dict(sharpe_20session_block_bootstrap_95pct=np.quantile(boot,[.025,.975]).tolist(),
        bootstrap_note='Conditional descriptive interval for a frozen observed return stream; not independent evidence, not a correction for prior searches, nonstationarity or implementation error.',
        worst_daily_return=float(returns.min()),best_daily_return=float(returns.max()),worst_5pct_mean=float(np.sort(returns)[:max(1,int(n*.05))].mean()),
        max_underwater_sessions=longest,max_drawdown_date=str(q.date.iloc[int(dd.argmax())].date()),
        profit_concentration=dict(top10=top,top1_share_of_net_profit=top[0][1]/(nav[-1]-100000),
                                 top10_share_of_positive_contributions=sum(v for k,v in top)/positive,
                                 identities_note='Per-symbol net cashflows incl dividend credits + final marked value; exactly reconciled to account net profit.'),
        benchmark=dict(name='000905.SH',close_to_close_total_return=benchmark_return,beta=float(coefficient[1]),annualized_regression_intercept=float(coefficient[0]*252),
                       note='Descriptive close-return comparison, not a traded ETF account and not proof of factor-neutral alpha.'),
        annual_returns=years,average_holdings=float(q.holdings.mean()),max_holdings=int(q.holdings.max()),
        average_exposure=float(q.exposure.mean()),max_exposure=float(q.exposure.max()),
        gross_traded_value=float((t.qty.abs()*t.price).sum()),strategy_return_correlations=corr,
        industry_limitation='Only current_industry_map.csv available. Historical sector-neutral attribution is NOT claimed; using current sectors would introduce retrospective classification.',
        search_bias_limitation='Prior historical strategy searches exist; their complete effective trial count is unavailable. No deflated-Sharpe/PBO success is claimed. New diagnostic trials are fully counted.')
    r.dump('statistical_diagnostics.json',result)
    old=pd.read_parquet(folder/'stress_original_daily_reference_trades.parquet')
    oldq=pd.read_parquet(folder/'stress_original_daily_reference_equity.parquet')
    prior=pd.read_parquet(r.BASE/'test2_weekly/original_202001/daily_equity.parquet')
    common=min(len(old),len(t));first=next((i for i in range(common) if any(old.iloc[i][k]!=t.iloc[i][k] for k in ['date','symbol','qty','price'])),None)
    r.dump('old_new_reconciliation.json',dict(old_reference_nav_exactly_reproduced=bool(np.array_equal(oldq.equity.to_numpy(),prior.equity.to_numpy())),
        first_fill_difference=None if first is None else dict(index=first,old=old.iloc[first].to_dict(),new=t.iloc[first].to_dict()),
        old_final=float(oldq.equity.iloc[-1]),new_final=float(nav[-1]),
        explanation='Same independently rebuilt signals; differences arise from tick rounding, exact opening-limit matching and cash rounding reserve, with path-dependent subsequent lot/target changes. No weights were fitted.'))
    print(json.dumps({k:v for k,v in result.items() if k in ['sharpe_20session_block_bootstrap_95pct','max_underwater_sessions','max_drawdown_date','annual_returns']},indent=2))

if __name__=='__main__':main()
