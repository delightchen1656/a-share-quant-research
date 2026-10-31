"""Annualize continuous-account stages and compound/time-weight regime groups."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parents[1]/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed/continuous_sse_stages'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    rows=read(OUT/'ACCOUNT_STAGE_RESULTS.json');stages=read(OUT/'STAGE_SUMMARY.json')
    for r in rows:
        entry=pd.Timestamp(r['start']);left=pd.Timestamp(r['boundary_start']);end=pd.Timestamp(r['boundary_end'])
        # Continuous mark-to-mark intervals exclude the left-close day.
        # First entry is open-to-close inclusive, consistent with full CAGR.
        days=(end-entry).days+1 if entry>=left else (end-left).days
        assert days>0;r['calendar_days']=days
        r['annualized_return']=float(np.expm1(np.log1p(r['total_return'])*365.25/days))
        for key in ['sse','hs300']:
            ann=float(np.expm1(np.log1p(r[key+'_return'])*365.25/days))
            r[key+'_annualized_return']=ann;r['annualized_excess_vs_'+key+'_pp']=r['annualized_return']-ann
    df=pd.DataFrame(rows);summary=[]
    for stage in stages:
        z=df.loc[df.stage_id.eq(stage['id'])];assert len(z)==58
        r=dict(stage,calendar_span_days=(pd.Timestamp(stage['period_end'])-pd.Timestamp(stage['period_start'])).days)
        for key in ['annualized_return','sse_annualized_return','hs300_annualized_return','annualized_excess_vs_sse_pp','annualized_excess_vs_hs300_pp']:
            r['mean_'+key]=float(z[key].mean())
        summary.append(r)
    groups=[];details=[]
    for completed_only in [False,True]:
        for (state,start),z in df.groupby(['state','start']):
            if completed_only:z=z.loc[~z.unfinished]
            days=int(z.calendar_days.sum());assert days>0
            item=dict(state=state,start=start,completed_only=completed_only,calendar_days=days,segments=len(z))
            for key,retcol in [('strategy','total_return'),('sse','sse_return'),('hs300','hs300_return')]:
                log_total=float(np.log1p(z[retcol]).sum())
                item[key+'_wealth_multiple']=float(np.exp(log_total))
                item[key+'_annualized_return']=float(np.expm1(log_total*365.25/days))
                assert np.isclose(np.exp(log_total),np.prod(1+z[retcol]),rtol=1e-12)
            item['excess_vs_sse_pp']=item['strategy_annualized_return']-item['sse_annualized_return']
            item['excess_vs_hs300_pp']=item['strategy_annualized_return']-item['hs300_annualized_return']
            details.append(item)
        selected=pd.DataFrame([r for r in details if r['completed_only']==completed_only])
        for state,z in selected.groupby('state'):
            item=dict(state=state,completed_only=completed_only,accounts=len(z),segments=int(z.segments.iloc[0]),
                mean_calendar_days=float(z.calendar_days.mean()))
            for key in ['strategy_annualized_return','sse_annualized_return','hs300_annualized_return','excess_vs_sse_pp','excess_vs_hs300_pp']:
                item['mean_'+key]=float(z[key].mean())
            groups.append(item)
    protocol=dict(stage_annualization='(1+stage_return) ** (365.25 / actual_calendar_days) -1, calculated per account then averaged across58 accounts.',
        regime_annualization='For each continuous account, compound all same-state segment returns; annualize by SUM of their actual calendar durations. Then average the58 account annualized rates. Never arithmetic-average stage returns or stage annualized returns.',
        risk='Segment drawdown and Sharpe unchanged by annualization. Regime-group returns are ex-post attribution, not a deployable switching strategy.',
        short_periods='Annualized short-stage rates are mathematical extrapolations, not achieved annual profits.',
        leading_fragment='Leading fragments before the first supplied pivot are preserved in the original reconciliation and excluded from the labeled-stage group statistics.')
    write(OUT/'ANNUALIZED_ACCOUNT_STAGES.json',rows);write(OUT/'ANNUALIZED_STAGE_SUMMARY.json',summary)
    write(OUT/'TIME_WEIGHTED_REGIME_ACCOUNTS.json',details);write(OUT/'TIME_WEIGHTED_REGIME_SUMMARY.json',groups);write(OUT/'ANNUALIZATION_PROTOCOL.json',protocol)
    lines=[]
    for r in summary:
        label=('牛' if r['state']=='bull' else '熊')+('（进行中）' if r['unfinished'] else '')
        lines.append('<tr><td>'+label+'</td><td>'+r['period_start']+' 至 '+r['period_end']+'</td>'+''.join('<td>'+format(r[k],'.3f' if k=='mean_sharpe' else '+.2%' if 'excess' in k else '.2%')+'</td>' for k in ['mean_total_return','mean_annualized_return','mean_annualized_excess_vs_sse_pp','mean_annualized_excess_vs_hs300_pp','mean_max_drawdown','mean_sharpe'])+'</tr>')
    group_rows=[]
    for r in groups:
        if r['completed_only']:continue
        group_rows.append('<tr><td>'+r['state']+'</td><td>'+str(r['segments'])+'</td>'+''.join('<td>'+format(r[k],'+.2%' if 'excess' in k else '.2%')+'</td>' for k in ['mean_strategy_annualized_return','mean_sse_annualized_return','mean_hs300_annualized_return','mean_excess_vs_sse_pp','mean_excess_vs_hs300_pp'])+'</tr>')
    page='<meta charset="utf-8"><title>沪深1连续账户阶段年化</title><style>body{font:15px sans-serif;margin:28px}td,th{padding:8px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>连续账户：按阶段实际天数年化</h1><p>2019Q1全部58个起点，各10万元，单边0.5%理想化成交，持续至2026-10-29。不是各阶段新开账户。阶段年化=(1+阶段收益)^(365.25/实际自然日数)-1；初始阶段按各自实际入场时间，后续按相邻转折日收盘净值。年化超额为策略年化减指数同期年化，单位百分点。</p><p>牛熊汇总不平均阶段收益或阶段年化：先逐账户复合所有同类阶段收益，以同类阶段累计天数年化，最后对58个账户取均值。包括最后未结束熊段。峰谷是反向10%确认后的事后标签，仅作行情归因。</p><table><tr><th>状态</th><th>阶段数</th><th>策略年化</th><th>上证年化</th><th>沪深300年化</th><th>上证超额</th><th>沪深300超额</th></tr>'+''.join(group_rows)+'</table><h2>各阶段</h2><table><tr><th>状态</th><th>区间</th><th>实际区间收益</th><th>阶段年化折算</th><th>年化上证超额</th><th>年化沪深300超额</th><th>段内回撤</th><th>Sharpe</th></tr>'+''.join(lines)+'</table><p>很短阶段的年化会非常大或非常小，它只是折算，不是实际赚到了对应全年收益。回撤与Sharpe不因这次年化展示而改变。第一段58个入场日期不同，均使用各自实际持续时间。</p>'
    (OUT/'annualized_report.html').write_text(page,encoding='utf-8')
    print('GROUPS',json.dumps(groups))
    for r in summary:print(r['state'],r['period_start'],r['period_end'],*[round(r[k]*100,2) for k in ['mean_total_return','mean_annualized_return','mean_annualized_excess_vs_sse_pp','mean_annualized_excess_vs_hs300_pp']])


if __name__=='__main__':main()
