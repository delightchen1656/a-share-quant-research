"""Attribute the existing58 continuous accounts to SSE stages without trading."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

PARENT=Path(__file__).resolve().parents[1]/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'
OUT=PARENT/'continuous_sse_stages'


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def metrics(values,baseline):
    returns=values/np.r_[baseline,values[:-1]]-1
    return dict(total_return=float(values[-1]/baseline-1),
        max_drawdown=float((1-values/np.maximum.accumulate(np.r_[baseline,values])[1:]).max()),
        sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)) if len(returns)>1 and returns.std(ddof=1)>0 else None)


def main(stage_source=None,output=None):
    global OUT
    if output is not None:OUT=Path(output)
    OUT.mkdir(exist_ok=True)
    stage_path=Path(stage_source) if stage_source is not None else PARENT/'sse_reversal10_pivots_first5/STAGE_SUMMARY.json'
    stages=read(stage_path)
    whole=read(PARENT/'SUMMARY.json');assert whole['start_count']==58
    indexes={}
    for key,code in [('sse','sh.000001'),('hs300','sh.000300')]:
        d=pd.DataFrame(read(PARENT/'benchmark_inputs'/(code+'.json'))['rows']);d.date=pd.to_datetime(d.date)
        indexes[key]=d.set_index('date').close.astype(float)
    all_rows=[];prefixes=[];reconciliation=[];input_hashes={}
    for path in sorted((PARENT/'runs').glob('*_nav.parquet')):
        start=path.name[:10];nav=pd.read_parquet(path).sort_values('date');nav.date=pd.to_datetime(nav.date);nav=nav.set_index('date')
        trade_path=path.with_name(start+'_trades.parquet');trades=pd.read_parquet(trade_path);trades.date=pd.to_datetime(trades.date)
        input_hashes[path.name]=sha(path);input_hashes[trade_path.name]=sha(trade_path)
        entry=pd.Timestamp(start);first_pivot=pd.Timestamp(stages[0]['period_start']);product=1.;index_product={k:1. for k in indexes}
        # Preserve entries before the first supplied pivot separately so the
        # full continuous account still reconciles exactly.
        if entry<first_pivot:
            opening=nav.loc[nav.index<=first_pivot];ret=float(opening.equity.iloc[-1]/100000-1);product*=1+ret
            pref=dict(start=start,period_start=start,period_end=str(first_pivot.date()),total_return=ret)
            for k,q in indexes.items():
                r=float(q.loc[first_pivot]/q.loc[entry]-1);index_product[k]*=1+r;pref[k+'_return']=r
            prefixes.append(pref)
        for stage in stages:
            left=pd.Timestamp(stage['period_start']);right=pd.Timestamp(stage['period_end'])
            if entry>=left:
                segment=nav.loc[(nav.index>=entry)&(nav.index<=right)];baseline=100000.;index_base_date=entry
            else:
                segment=nav.loc[(nav.index>left)&(nav.index<=right)];baseline=float(nav.loc[left,'equity']);index_base_date=left
            assert len(segment)>0
            row=dict(start=start,stage_id=stage['id'],state=stage['state'],unfinished=stage['unfinished'],
                boundary_start=stage['period_start'],boundary_end=stage['period_end'],
                actual_segment_start=str(segment.index[0].date()),baseline_equity=baseline,ending_equity=float(segment.equity.iloc[-1]))
            row.update(metrics(segment.equity.to_numpy(dtype=float),baseline));product*=1+row['total_return']
            for key,q in indexes.items():
                r=float(q.loc[right]/q.loc[index_base_date]-1);row[key+'_return']=r
                row['excess_vs_'+key+'_pp']=row['total_return']-r;index_product[key]*=1+r
            t=trades.loc[trades.date.isin(segment.index)]
            row['trades']=len(t);row['fees']=float(t[['commission','transfer','stamp','dividend_tax']].sum().sum())
            all_rows.append(row)
        full=float(nav.equity.iloc[-1]/100000)
        assert np.isclose(product,full,rtol=0,atol=1e-10),(start,product,full)
        for key,q in indexes.items():assert np.isclose(index_product[key],q.loc[nav.index[-1]]/q.loc[entry],rtol=0,atol=1e-10)
        reconciliation.append(dict(start=start,full_wealth_multiple=full,stage_compounded_multiple=product,identical=True))
    df=pd.DataFrame(all_rows);summary=[]
    for stage in stages:
        z=df.loc[df.stage_id.eq(stage['id'])];assert len(z)==58
        r={k:stage[k] for k in ['id','state','period_start','period_end','unfinished']};r['accounts']=len(z)
        for k in ['total_return','sse_return','hs300_return','excess_vs_sse_pp','excess_vs_hs300_pp','max_drawdown','sharpe','trades','fees']:
            r['mean_'+k]=float(z[k].mean())
        r['min_return']=float(z.total_return.min());r['max_return']=float(z.total_return.max())
        summary.append(r)
    audit=dict(source='Existing continuous2019-Q1 accounts; no simulation or trade generation.',
        accounts=58,stages=len(summary),slippage=.005,initial_cash=100000,end=whole['end'],
        source_summary_sha256=sha(PARENT/'SUMMARY.json'),stage_boundary_source_sha256=sha(stage_path),
        input_hashes=input_hashes,all_account_and_index_compounding_reconciled=True,
        first_stage='Accounts entering on/after the first supplied pivot begin from actual entry,100000 capital. Earlier entries use that pivot closing NAV as first stage baseline; leading fragments are preserved separately.',
        later_stages='Existing NAV at left pivot close to right pivot close; daily returns start the next session. No account reset, forced liquidation or extra rebalance.',
        benchmark='Same dates, price-index closes; first entry uses its closing index base, matching existing full-period benchmark convention.',
        future_label='Peak/trough stage boundaries use later10% reversal confirmations for ex-post attribution only; not an executable turning-point rule.')
    write(OUT/'PROVENANCE.json',audit);write(OUT/'ACCOUNT_STAGE_RESULTS.json',all_rows);write(OUT/'STAGE_SUMMARY.json',summary)
    write(OUT/'LEADING_FRAGMENTS.json',prefixes);write(OUT/'RECONCILIATION.json',reconciliation)
    group=[]
    for state in ['bull','bear']:
        z=[r for r in summary if r['state']==state and not r['unfinished']]
        group.append(dict(state=state,completed_stages=len(z),positive_stages=sum(r['mean_total_return']>0 for r in z),
            mean_stage_return=float(np.mean([r['mean_total_return'] for r in z])),mean_excess_vs_sse=float(np.mean([r['mean_excess_vs_sse_pp'] for r in z])),
            mean_stage_drawdown=float(np.mean([r['mean_max_drawdown'] for r in z]))))
    write(OUT/'COMPLETED_REGIME_SUMMARY.json',group)
    rows=[]
    for r in summary:
        label=('牛' if r['state']=='bull' else '熊')+('（进行中）' if r['unfinished'] else '')
        rows.append('<tr><td>'+label+'</td><td>'+r['period_start']+' 至 '+r['period_end']+'</td>'+''.join('<td>'+format(r[k],'.3f' if k=='mean_sharpe' else '+.2%' if 'excess' in k else '.2%')+'</td>' for k in ['mean_total_return','mean_sse_return','mean_excess_vs_sse_pp','mean_excess_vs_hs300_pp','mean_max_drawdown','mean_sharpe'])+'</tr>')
    page='<meta charset="utf-8"><title>沪深1连续账户按牛熊阶段归因</title><style>body{font:15px sans-serif;margin:28px}td,th{padding:8px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>2019Q1全部58个起点：连续账户按上证峰谷分段</h1><p>每账户初始10万元，连续运行至2026-10-29，单边0.5%理想化保证成交。只切分既有净值，不清仓、不开新账户、不重置本金、不额外调仓。全期平均年化仍为26.57%，期末资产平均616223.64元。</p><p>峰谷由上证收盘价反向10%确认，属于事后行情归因。后续各段收益=段末权益÷起始转折日收盘权益−1；相邻段不重复计算转折日收益。第一段按各账户实际存在区间计算。58个账户的收益、超额、回撤和Sharpe分别计算后取平均。超额为百分点差，指数首日收盘基准沿用原全期比较。段回撤以当段起始权益重新计算，Sharpe无风险利率0。短阶段Sharpe不宜与多年值直接比较。</p><table><tr><th>状态</th><th>阶段边界</th><th>策略收益</th><th>上证收益</th><th>对上证超额</th><th>对沪深300超额</th><th>最大回撤</th><th>Sharpe</th></tr>'+''.join(rows)+'</table><p>所有58账户分段收益逐一复合后，与原连续账户期末资产完全一致；不能直接复合各段平均收益。未结束熊段不计入已结束阶段汇总。</p>'
    (OUT/'report.html').write_text(page,encoding='utf-8')
    write(OUT/'COMPLETE.json',dict(summary_sha256=sha(OUT/'STAGE_SUMMARY.json'),reconciled_accounts=len(reconciliation)))
    for r in summary:print(r['state'],r['period_start'],r['period_end'],*[round(r[k]*100,2) for k in ['mean_total_return','mean_excess_vs_sse_pp','mean_excess_vs_hs300_pp','mean_max_drawdown']],round(r['mean_sharpe'],3))
    print('GROUP',json.dumps(group));print('COMPLETE',OUT,'reconciled',len(reconciliation))


if __name__=='__main__':main()
