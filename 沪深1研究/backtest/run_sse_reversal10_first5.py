"""SSE10% close-reversal states; five fresh first-week entries per state."""
from pathlib import Path
import json
import hashlib
import html
import sys
import traceback
import argparse
import numpy as np
import pandas as pd
import engine as e
from run_q1_2019_slip005 import writers,inventory

HOME=Path(__file__).resolve().parents[1];ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
PARENT=HOME/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'
OUT=PARENT/'sse_reversal10_first5'
REFERENCE=OUT


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    p=Path(p);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8');tmp.replace(p)


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--basis',choices=['confirmation','pivot'],default='confirmation');args=parser.parse_args()
    retrospective=args.basis=='pivot'
    if retrospective:OUT=PARENT/'sse_reversal10_pivots_first5'
    OUT.mkdir(exist_ok=True)
    assert not writers(),'Market writer active'
    previous=read(PARENT/'PROTOCOL.json');end=previous['end'];assert end=='2026-10-29'
    assert sha(ROOT/'K线数据/更新备份与审计/20261029/audit.json')==previous['daily_audit_sha256']
    for name,key in [('engine.py','engine_sha256'),('ledger.py','ledger_sha256')]:assert sha(HOME/'backtest'/name)==previous[key]
    assert sha(HOME/'supermind_hushen_1.py')==previous['source_sha256']
    # A completed independent replay already proved the failed backfill never
    # committed. Recheck its transaction boundary and every market file hash.
    failed=Path(previous['uncommitted_staging_excluded'])
    assert not (failed/'before_update').exists() and not (failed/'commit_manifest.json').exists()
    before=inventory();work=OUT/'runtime_inputs';work.mkdir(exist_ok=True)
    for name in ['inputs.json','calendar.parquet','rankings_original.json']:
        src=PARENT/'runtime_inputs'/name;dest=work/name
        if dest.exists():assert dest.read_bytes()==src.read_bytes()
        else:dest.write_bytes(src.read_bytes())
    dates=pd.DatetimeIndex(pd.read_parquet(work/'calendar.parquet').date)
    sse=pd.DataFrame(read(REFERENCE/'sse_2016_to_20261029.json')['rows']);sse.date=pd.to_datetime(sse.date)
    sse=sse.set_index('date').sort_index();sse[['open','close']]=sse[['open','close']].astype(float)
    hs=pd.DataFrame(read(PARENT/'benchmark_inputs/sh.000300.json')['rows']);hs.date=pd.to_datetime(hs.date)
    hs=hs.set_index('date').sort_index();hs[['open','close']]=hs[['open','close']].astype(float)
    # Confirmed at the close. The next session is the first tradable entry.
    events=read(REFERENCE/'REVERSALS.json');stages=[]
    for index,event in enumerate(events):
        if event['confirmed']<'2019-01-01':continue
        confirmation=pd.Timestamp(event['pivot'] if retrospective else event['confirmed'])
        next_confirmation=pd.Timestamp(events[index+1]['pivot' if retrospective else 'confirmed']) if index+1<len(events) else pd.Timestamp(end)
        sessions=dates[((dates>=confirmation) if retrospective else (dates>confirmation))&(dates<=next_confirmation)]
        if not len(sessions):continue
        stages.append(dict(id=len(stages)+1,state=event['mode'],confirmed=event['confirmed'],pivot=event['pivot'],
            period_start=str(sessions[0].date()),period_end=str(sessions[-1].date()),sessions=len(sessions),
            starts=[str(d.date()) for d in sessions[:5]],unfinished=index+1==len(events)))
    protocol=dict(threshold=.10,price='SSE daily closing price; no intraday highs/lows',
        stage_rule='Bull -> bear after10% drawdown from running closing high; bear -> bull after10% rise from running closing low.',
        entry_rule='First5 actual sessions AFTER confirmation; five independent100000 cash accounts per stage.',
        end_rule='Next reversal confirmation close; terminal market value, no forced liquidation fee. Final ongoing phase ends at latest audited close.',
        initial_2019_carryover='The bear state confirmed2018-02-09 persists until2019-02-13; excluded because its actual first week predates the2019 research window.',
        execution=previous['effective_policy'],calendar_phase='Original20-session global phase plus first-entry exception; no phase tuning',
        parent_protocol_sha256=sha(PARENT/'PROTOCOL.json'),sse_input_sha256=sha(REFERENCE/'sse_2016_to_20261029.json'),stages=stages)
    if retrospective:
        protocol.update(basis='Retrospective confirmed extrema; uses future10% confirmations only for labeling/evaluation, not a deployable turning-point strategy.',
            entry_rule='First5 actual sessions beginning with each ex-post pivot; five independent100000 cash accounts per stage.',
            end_rule='Next confirmed ex-post pivot close; latest ongoing segment ends at latest audited close. No forced final liquidation.')
    pp=OUT/'PROTOCOL.json'
    if pp.exists():assert read(pp)==protocol,'Checkpoint mismatch'
    else:write(pp,protocol)
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=end)
    code=(HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    print('LOAD_VERIFIED_MARKET','stages',len(stages),'accounts',sum(len(s['starts']) for s in stages),flush=True)
    m=e.Market();m.actions.own=work/'additional_actions.json'
    for p in [PARENT/'runtime_inputs/additional_actions.json',m.actions.own]:
        if p.exists():m.actions.cache.update(read(p))
    m.actions.extra=read(m.actions.own) if m.actions.own.exists() else {}
    runs=OUT/'runs';runs.mkdir(exist_ok=True);all_results=[];failures=[];daily=[]
    try:
        for stage in stages:
            for start in stage['starts']:
                prefix=str(stage['id']).zfill(2)+'_'+start;path=runs/(prefix+'.json')
                if path.exists():result=read(path);nav=pd.read_parquet(runs/(prefix+'_nav.parquet'))
                else:
                    try:
                        result,a=e.simulate(m,start,stage['period_end'],scenario='open_003_guaranteed',initial=100000,params={'SLIP_ONE_SIDE':.005})
                        assert a.m.SLIP_ONE_SIDE==.005
                        result['execution_policy']=previous['effective_policy'];result.update(stage_id=stage['id'],state=stage['state'])
                        nav=pd.DataFrame(a.curve);nav.to_parquet(runs/(prefix+'_nav.parquet'),index=False)
                        pd.DataFrame(a.trades).to_parquet(runs/(prefix+'_trades.parquet'),index=False)
                        write(path,result)
                    except Exception as ex:
                        failures.append(dict(stage=stage,start=start,error=str(ex),trace=traceback.format_exc()));write(OUT/'FAILURES.json',failures)
                        print('FAILED',prefix,str(ex),flush=True);continue
                nav.date=pd.to_datetime(nav.date);ret=nav.equity.to_numpy()/np.r_[100000,nav.equity.to_numpy()[:-1]]-1
                for day,value in zip(nav.date,ret):daily.append(dict(stage_id=stage['id'],state=stage['state'],start=start,date=str(day.date()),ret=float(value)))
                for key,index_data in [('sse',sse),('hs300',hs)]:
                    q=index_data.loc[pd.Timestamp(start):pd.Timestamp(stage['period_end'])]
                    assert pd.DatetimeIndex(nav.date).equals(q.index)
                    opening=float(q.open.iloc[0]);v=q.close.to_numpy(dtype=float)
                    result[key+'_return']=float(v[-1]/opening-1)
                    result['excess_vs_'+key+'_pp']=result['total_return']-result[key+'_return']
                all_results.append(result)
            write(OUT/'PROGRESS.json',dict(stages_completed=stage['id'],total_stages=len(stages),accounts_completed=len(all_results),failed=len(failures)))
            print('STAGE',stage['id'],stage['state'],stage['period_start'],stage['period_end'],'accounts',len(stage['starts']),flush=True)
    finally:m.actions.close()
    assert not failures,'Failed accounts; no survivor-only stage averages'
    assert before==inventory() and not writers(),'Formal market changed during replay'
    frame=pd.DataFrame(all_results);summary=[]
    for stage in stages:
        group=frame.loc[frame.stage_id.eq(stage['id'])];assert len(group)==len(stage['starts'])
        item=dict(stage)
        for key in ['total_return','max_drawdown','sharpe','cagr','trades','total_cost','sse_return','hs300_return','excess_vs_sse_pp','excess_vs_hs300_pp']:
            item['mean_'+key]=float(group[key].mean())
        item['min_return']=float(group.total_return.min());item['max_return']=float(group.total_return.max())
        item['unresolved_actions']=int(group.unresolved_actions.sum());item['reference_differences']=int(group.reference_differences.sum())
        summary.append(item)
    df=pd.DataFrame(daily);groups=[]
    for state,z in df.groupby('state'):
        returns=z.ret.to_numpy();s=[r for r in summary if r['state']==state]
        groups.append(dict(state=state,stages=len(s),complete_stages=sum(not r['unfinished'] for r in s),
            mean_stage_return=float(np.mean([r['mean_total_return'] for r in s])),
            median_stage_return=float(np.median([r['mean_total_return'] for r in s])),
            mean_stage_excess_vs_sse=float(np.mean([r['mean_excess_vs_sse_pp'] for r in s])),
            mean_stage_max_drawdown=float(np.mean([r['mean_max_drawdown'] for r in s])),
            conditional_geometric_annualized=float(np.expm1(np.log1p(returns).mean()*252)),
            conditional_sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)),
            independent_market_sessions=len(z[['stage_id','date']].drop_duplicates())))
    write(OUT/'all_accounts.json',all_results);write(OUT/'STAGE_SUMMARY.json',summary);write(OUT/'REGIME_SUMMARY.json',groups)
    write(OUT/'QUALITY.json',dict(accounts=len(frame),stages=len(summary),unresolved_actions=int(frame.unresolved_actions.sum()),reference_differences=int(frame.reference_differences.sum()),rejected_orders=int(frame.rejected_orders.sum())))
    rows=[]
    for r in summary:
        label=('牛' if r['state']=='bull' else '熊')+('（进行中）' if r['unfinished'] else '')
        rows.append('<tr><td>'+label+'</td><td>'+r['confirmed']+'</td><td>'+r['period_start']+' 至 '+r['period_end']+'</td><td>'+', '.join(r['starts'])+'</td>'+''.join('<td>'+format(r[k],'.3f' if k=='mean_sharpe' else '+.2%' if 'excess' in k else '.2%')+'</td>' for k in ['mean_total_return','mean_sse_return','mean_excess_vs_sse_pp','mean_excess_vs_hs300_pp','mean_max_drawdown','mean_sharpe'])+'</tr>')
    basis_note=('按反向10%确认的峰谷作事后阶段归因：从极值日开始的前5个交易日各10万元空仓建仓，持有至下一极值日收盘。极值日只有之后反向10%才可确认，因此本表使用未来标签，不能作为可实时实现的转折点入场策略。' if retrospective else '收盘确认、次日起前5个交易日各10万元独立空仓建仓，持有至下一次反转确认日收盘。')
    page='<meta charset="utf-8"><title>沪深1上证10%反转阶段</title><style>body{font:15px sans-serif;margin:24px}td,th{padding:8px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>上证收盘价反向10%确认：沪深1阶段首周独立建仓</h1><p>'+basis_note+'按原20交易日全局相位继续调仓，段末估值不强制卖出。单边0.5%理想化保证成交。最后一段尚未结束，截止2026-10-29。</p><p>指数同期收益以各账户实际入场日开盘至段末收盘计算，价格指数不含费用和股息。超额为直接收益差（百分点）。回撤、Sharpe先逐账户计算再平均，Sharpe无风险利率0。第一周指前5个交易日，不是自然周。各段长度不同，平均段收益不能直接作为牛熊优劣依据；状态内年化为池化日收益的252日几何折算，不是一条连续执行净值。</p><table><tr><th>状态</th><th>确认日</th><th>评估区间</th><th>5个入场日</th><th>策略收益</th><th>上证收益</th><th>上证超额</th><th>沪深300超额</th><th>最大回撤</th><th>Sharpe</th></tr>'+''.join(rows)+'</table><pre>'+html.escape(json.dumps(groups,ensure_ascii=False,indent=2))+'</pre>'
    (OUT/'report.html').write_text(page,encoding='utf-8');write(OUT/'COMPLETE.json',dict(summary_sha256=sha(OUT/'STAGE_SUMMARY.json'),protocol_sha256=sha(pp)))
    print('COMPLETE',OUT,flush=True)


if __name__=='__main__':main()
