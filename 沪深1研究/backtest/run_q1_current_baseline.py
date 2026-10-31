"""Every 2020-Q1 entry, frozen current execution baseline, audited latest data."""
from pathlib import Path
import hashlib
import html
import json
import sys
import traceback
import pandas as pd
import engine as e

HOME=Path(__file__).resolve().parents[1]
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
sys.path.insert(0,str(ROOT/'沪深实盘工作台/tracker'))
import market as local_market


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    p=Path(p);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8');tmp.replace(p)


def main():
    health=local_market.health(ROOT/'沪深实盘工作台/tracker/hushen1_data');end=health['market_date']
    policy=read(HOME/'backtest/execution_baseline.json');assert policy['scenario']=='open_003_guaranteed'
    registration=read(HOME/'research/migration.json')
    assert sha(HOME/'supermind_hushen_1.py')==registration['entry_sha256']
    assert sha(HOME/'backtest/execution_baseline.json')==registration['local_execution_baseline']['policy_sha256']
    snapshot=HOME/'results/holdout_restricted'/('range_20200101_to_'+end.replace('-','')+'_unified_cash_cost')
    source=snapshot/'runtime_inputs'
    assert read(snapshot/'RUN_STARTED.json')['end']==end
    out=HOME/'results/holdout_restricted'/('q1_2020_to_'+end.replace('-','')+'_open003_guaranteed')
    out.mkdir(exist_ok=True);work=out/'runtime_inputs';work.mkdir(exist_ok=True)
    for name in ['inputs.json','rankings_original.json','calendar.parquet']:
        target=work/name
        if target.exists():assert target.read_bytes()==(source/name).read_bytes()
        else:target.write_bytes((source/name).read_bytes())
    manifest=dict(end=end,initial_cash=100000,scenario=policy['scenario'],policy=policy,
        hashes={name:sha(HOME/name) for name in ['supermind_hushen_1.py','backtest/engine.py','backtest/ledger.py','backtest/execution_baseline.json']},
        input_sha256=sha(work/'inputs.json'),ranks_sha256=sha(work/'rankings_original.json'),audit_sha256=health['audit_sha256'],
        comparison='Each Q1 session starts independently empty. Keep original global20-session phase plus first-entry exception; no phase optimization.',
        interpretation='Arithmetic means across overlapping backtests; not independent samples or an unseen holdout.')
    protocol=out/'PROTOCOL.json'
    if protocol.exists():assert read(protocol)==manifest,'Checkpoint fingerprint mismatch'
    else:write(protocol,manifest)
    before=local_market.input_inventory()
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=end)
    code=(HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    print('LOAD_VERIFIED_MARKET',end,flush=True)
    market=e.Market();market.actions.own=work/'additional_actions.json'
    for extra in [source/'additional_actions.json',market.actions.own]:
        if extra.exists():market.actions.cache.update(read(extra))
    market.actions.extra=read(market.actions.own) if market.actions.own.exists() else {}
    starts=market.dates[(market.dates>='2020-01-01')&(market.dates<='2020-03-31')]
    write(out/'STARTS.json',[str(d.date()) for d in starts])
    runs=out/'runs';runs.mkdir(exist_ok=True);results=[];failures=[]
    try:
        for index,day in enumerate(starts,1):
            start=str(day.date());checkpoint=runs/(start+'.json')
            if checkpoint.exists():result=read(checkpoint)
            else:
                try:
                    result,account=e.simulate(market,start,end,scenario=policy['scenario'],initial=100000)
                    result['data_issues']=account.issues;result['reference_issues']=account.reference_diffs
                    pd.DataFrame(account.curve).to_parquet(runs/(start+'_nav.parquet'),index=False)
                    pd.DataFrame(account.trades).to_parquet(runs/(start+'_trades.parquet'),index=False)
                    write(checkpoint,result)
                except Exception as exc:
                    failure=dict(start=start,error=str(exc),trace=traceback.format_exc())
                    failures.append(failure);write(out/'FAILURES.json',failures)
                    print('FAILED',index,len(starts),start,str(exc),flush=True);continue
            results.append(result)
            write(out/'PROGRESS.json',dict(completed=len(results),failed=len(failures),total=len(starts),last_start=start))
            print('PROGRESS',index,len(starts),start,'CAGR',round(result['cagr'],6),'issues',result['unresolved_actions'],result['reference_differences'],flush=True)
    finally:market.actions.close()
    write(out/'all_starts.json',results)
    if failures:raise RuntimeError('Incomplete: '+str(len(failures))+' starts failed; no survivor-only average published')
    assert len(results)==len(starts)
    assert before==local_market.input_inventory() and not local_market._updater_running(),'Market changed during replay'
    keys=['final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost','commission','stamp','dividend_tax','average_exposure']
    frame=pd.DataFrame(results)
    summary={k:dict(mean=float(frame[k].mean()),median=float(frame[k].median()),min=float(frame[k].min()),max=float(frame[k].max()),std=float(frame[k].std(ddof=1))) for k in keys}
    quality=dict(unresolved_actions_total=int(frame.unresolved_actions.sum()),reference_differences_total=int(frame.reference_differences.sum()),rejected_orders_total=int(frame.rejected_orders.sum()))
    quality['fully_validated']=not any(quality.values())
    result=dict(start_count=len(starts),first_start=str(starts[0].date()),last_start=str(starts[-1].date()),end=end,initial_cash=100000,summary=summary,quality=quality)
    write(out/'SUMMARY.json',result)
    labels={'final_equity':'期末资产（元）','total_return':'累计收益','cagr':'年化收益','max_drawdown':'最大回撤','sharpe':'Sharpe','trades':'成交笔数','total_cost':'总成本（元）','commission':'佣金（元）','stamp':'印花税（元）','dividend_tax':'股息税（元）','average_exposure':'平均仓位'}
    percent={'total_return','cagr','max_drawdown','average_exposure'}
    rows=[]
    for k,values in summary.items():
        vals=[format(values[x],'.2%' if k in percent else ',.3f' if k=='sharpe' else ',.2f') for x in ['mean','median','min','max']]
        rows.append('<tr><td>'+labels[k]+'</td>'+''.join('<td>'+v+'</td>' for v in vals)+'</tr>')
    page='<meta charset="utf-8"><title>沪深1 Q1全起点均值</title><style>body{font:16px sans-serif;margin:32px}td,th{padding:9px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>沪深1：2020Q1全部起点至'+end+'</h1><p>'+str(len(starts))+'个起点，各自10万元。开盘单边0.3%理想化保证成交、当日卖出款可用、佣金万三最低5元、卖出印花税0.1%、无单列过户费。</p><p>均值为各账户指标的算术平均；回撤/Sharpe先逐账户计算，再取平均。起点高度重叠，不是独立样本。质量核验：'+html.escape(str(quality))+'</p><table><tr><th>指标</th><th>平均</th><th>中位数</th><th>最小</th><th>最大</th></tr>'+''.join(rows)+'</table>'
    (out/'report.html').write_text(page,encoding='utf-8')
    write(out/'COMPLETE.json',dict(summary_sha256=sha(out/'SUMMARY.json'),protocol_sha256=sha(protocol)))
    print('COMPLETE',out,flush=True)


if __name__=='__main__':main()
