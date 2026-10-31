"""Calendar-year breakdown of the completed58-start run; no new trades."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parents[1]/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'


def main():
    overall=json.loads((OUT/'SUMMARY.json').read_text(encoding='utf-8'))
    rows=[]
    for path in sorted((OUT/'runs').glob('*_nav.parquet')):
        start=path.name[:10];nav=pd.read_parquet(path).sort_values('date');nav.date=pd.to_datetime(nav.date)
        trades=pd.read_parquet(path.with_name(start+'_trades.parquet'));trades.date=pd.to_datetime(trades.date)
        for year,g in nav.groupby(nav.date.dt.year):
            prior=nav.loc[nav.date<g.date.iloc[0]]
            baseline=float(prior.equity.iloc[-1]) if len(prior) else 100000.
            values=g.equity.to_numpy(dtype=float);daily=values/np.r_[baseline,values[:-1]]-1
            period_start=pd.Timestamp(start) if year==2019 else pd.Timestamp(year=year,month=1,day=1)
            period_end=g.date.iloc[-1];days=(period_end-period_start).days+1
            total=float(values[-1]/baseline-1)
            # Full calendar years are already annual returns. For incomplete
            # first/final years show a separate calendar-day annualization.
            annualized=total if year not in (2019,2026) else float((1+total)**(365.25/days)-1)
            drawdown=float((1-values/np.maximum.accumulate(np.r_[baseline,values])[1:]).max())
            annual_trades=trades.loc[trades.date.dt.year.eq(year)]
            fees=float(annual_trades[['commission','transfer','stamp','dividend_tax']].sum().sum())
            rows.append(dict(start=start,year=int(year),period_start=str(period_start.date()),period_end=str(period_end.date()),
                period_return=total,annualized_return=annualized,max_drawdown=drawdown,
                sharpe=float(daily.mean()/daily.std(ddof=1)*np.sqrt(252)) if daily.std(ddof=1)>0 else None,
                trades=len(annual_trades),fees=fees,year_start_equity=baseline,year_end_equity=float(values[-1])))
        compounded=float(np.prod([1+r['period_return'] for r in rows if r['start']==start]))
        assert np.isclose(compounded,nav.equity.iloc[-1]/100000,rtol=0,atol=1e-10)
    frame=pd.DataFrame(rows);summary=[]
    for year,g in frame.groupby('year'):
        assert len(g)==overall['start_count']==58
        summary.append(dict(year=int(year),starts=len(g),mean_period_return=float(g.period_return.mean()),
            min_period_return=float(g.period_return.min()),max_period_return=float(g.period_return.max()),
            mean_annualized_return=float(g.annualized_return.mean()),mean_max_drawdown=float(g.max_drawdown.mean()),
            mean_sharpe=float(g.sharpe.mean()),mean_trades=float(g.trades.mean()),mean_fees=float(g.fees.mean())))
    (OUT/'annual_by_start.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'annual_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=[]
    for r in summary:
        lines.append('<tr><td>'+str(r['year'])+'</td>'+''.join('<td>'+format(r[k],'.2%' if k!='mean_sharpe' else '.3f')+'</td>' for k in ['mean_period_return','mean_annualized_return','min_period_return','max_period_return','mean_max_drawdown','mean_sharpe'])+'</tr>')
    page='<meta charset="utf-8"><title>沪深1逐年回测</title><style>body{font:16px sans-serif;margin:32px}td,th{padding:9px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>2019Q1全部58个起点：逐年统计</h1><p>每个账户初始10万元；单边滑点0.5%，理想化保证成交。2019为各自入场至年末，2026截至10月29日；其余完整自然年。各账户逐年计算后取均值。年内回撤从上年末权益（首年为初始资金）重新计算；Sharpe无风险利率为0。年度收益逐账户复合后已与全期收益核对，不能将各年的平均收益直接相乘重建平均全期收益。</p><table><tr><th>年份</th><th>平均区间收益</th><th>平均年化</th><th>最低区间收益</th><th>最高区间收益</th><th>平均年内最大回撤</th><th>平均Sharpe</th></tr>'+''.join(lines)+'</table>'
    (OUT/'annual_report.html').write_text(page,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
