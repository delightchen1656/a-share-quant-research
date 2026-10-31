"""2019-Q1 starts, +0.2 percentage point execution stress, no retuning."""
from pathlib import Path
import json
import hashlib
import html
import subprocess
import sys
import traceback
import numpy as np
import pandas as pd
import engine as e

HOME=Path(__file__).resolve().parents[1];ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
DATA=ROOT/'K线数据/沪深'
OUT=HOME/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    p=Path(p);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8');tmp.replace(p)
def writers():
    script="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'daily_market_update\\.py|backfill_hushen_history\\.py|wait_for_hushen_backfill_then_catch_up\\.py' } | Select-Object -ExpandProperty ProcessId"
    return subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,text=True,check=True,creationflags=0x08000000).stdout.strip()
def inventory():return [(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in sorted((DATA/'raw').glob('*/*.parquet'))]


def prepare():
    assert not writers(),'A market writer is active'
    end='2026-10-29';audit_path=ROOT/'K线数据/更新备份与审计/20261029/audit.json';audit=read(audit_path)
    assert audit['status']=='ok' and audit['target']==end
    refresh=read(DATA/'metadata/refresh_20261029.json')
    assert all(refresh[k]==audit[k] for k in ['status','target','updated_at','datasets','validation'])
    assert audit['validation']['transactional_staging'] and audit['validation']['active_symbol_latest_date']==end
    commit=read(ROOT/'K线数据/更新备份与审计/20261029/commit_manifest.json');assert len(commit['files'])==audit['committed_files'] and commit['target']==end
    # The failed history downloader only staged files. Prove that it never
    # reached backup/commit, preserve all its files, and verify every official
    # raw file against the already-frozen daily signal/snapshot receipts.
    failed=ROOT/'K线数据/更新备份与审计/hushen_full_20100101_20261029'
    assert not (failed/'before_update').exists() and not (failed/'commit_manifest.json').exists()
    assert 'full-history raw/qfq dates differ' in (failed/'background.stderr.log').read_text(encoding='utf-8')
    for stage in (ROOT/'K线数据/更新备份与审计').glob('*/staging'):
        assert stage.parent==failed,'Unrecognized staged transaction'
    signal_path=ROOT/'沪深实盘工作台/tracker/hushen1_data/signals/2026-10-29.json'
    signal=read(signal_path);assert signal['asof']==end and signal['audit_sha256']==sha(audit_path)
    registration=read(HOME/'research/migration.json')
    assert sha(HOME/'supermind_hushen_1.py')==signal['entry_sha256']==registration['entry_sha256']
    assert sha(HOME/'backtest/execution_baseline.json')==registration['local_execution_baseline']['policy_sha256']
    old=HOME/'results/holdout_restricted/range_20200101_to_20261028_unified_cash_cost/runtime_inputs'
    old_expected={r['symbol']:r['sha256'] for r in read(old/'inputs.json')['files']}
    expected={r['symbol']:r['sha256'] for r in signal['input_hashes']}
    records=[]
    for p in sorted((DATA/'raw').glob('*/*.parquet')):
        actual=sha(p);assert actual==expected.get(p.stem,old_expected.get(p.stem)),('Committed raw fingerprint mismatch',p.stem)
        records.append(dict(symbol=p.stem,sha256=actual))
    work=OUT/'runtime_inputs';work.mkdir(exist_ok=True)
    ranks=read(old/'rankings_original.json')
    historical_path=HOME/'results/holdout_restricted/jan2016_all_starts_to_20261023/runtime_inputs/historical_rankings_to_20191231.json'
    historical=read(historical_path)
    historical_audit=read(historical_path.with_name('historical_ranking_audit.json'))
    assert historical_audit['verified_raw_receipts']==3414 and all(x['equal'] for x in historical_audit['overlap_parity'])
    assert historical_audit['formula']['weights']==[-.35,-.2,.25,-.2]
    ranks.update({k:v for k,v in historical.items() if '2018-12-01'<=k<='2019-12-31'})
    # Extend only with frozen daily rankings that match the current code and
    # successful daily commit audits, never with the uncommitted history files.
    for day in ['2026-10-28','2026-10-29']:
        p=signal_path.with_name(day+'.json');s=read(p)
        assert s['entry_sha256']==registration['entry_sha256']
        assert s['audit_sha256']==sha(ROOT/'K线数据/更新备份与审计'/day.replace('-','')/'audit.json')
        ranks[day]=s['ranks']
    calendar=pd.read_csv(DATA/'metadata/trade_calendar_20261029.csv',dtype=str)
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq('1'),'calendar_date']))
    dates=dates[(dates>='2018-01-01')&(dates<=end)];assert str(dates[-1].date())==end
    starts=dates[(dates>='2019-01-01')&(dates<='2019-03-31')]
    assert all(ranks.get(str(dates[dates.get_loc(d)-1].date())) for d in starts)
    write(work/'inputs.json',dict(files=records));write(work/'rankings_original.json',ranks)
    pd.DataFrame(dict(date=dates)).to_parquet(work/'calendar.parquet',index=False)
    effective=read(HOME/'backtest/execution_baseline.json')
    effective.update(policy_id='execution_stress_open005_v1',base_policy_id=effective['policy_id'],slippage_one_side=.005,
        fill_assumption='Buy raw open times1.005; sell raw open times0.995; round to CNY0.01; full eligible quantity.',production_baseline_changed=False)
    protocol=dict(year=2019,end=end,initial_cash=100000,starts=[str(d.date()) for d in starts],effective_policy=effective,
        engine_sha256=sha(HOME/'backtest/engine.py'),ledger_sha256=sha(HOME/'backtest/ledger.py'),source_sha256=registration['entry_sha256'],
        input_sha256=sha(work/'inputs.json'),ranking_sha256=sha(work/'rankings_original.json'),historical_ranking_sha256=sha(historical_path),
        historical_warmup='Reuse audited2013+ price history reconstruction for2019 rankings; same formula, no retraining or selection changes.',
        daily_audit_sha256=sha(audit_path),uncommitted_staging_excluded=str(failed),
        formal_data_validation='No active writers; failed precommit has neither backup nor manifest; all official raw files match committed signal or unchanged snapshot hashes.',
        calendar_phase='Original global20-session phase from2018, plus independent first entry; no phase optimization')
    pp=OUT/'PROTOCOL.json'
    if pp.exists():assert read(pp)==protocol,'Checkpoint fingerprint mismatch'
    else:write(pp,protocol)
    return end,starts,work,old,protocol


def main():
    OUT.mkdir(exist_ok=True);before=inventory();end,starts,work,old,protocol=prepare()
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=end)
    code=(HOME/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    print('LOAD_HASH_VERIFIED_MARKET',end,'starts',len(starts),flush=True)
    m=e.Market();m.actions.own=work/'additional_actions.json'
    for p in [old/'additional_actions.json',m.actions.own]:
        if p.exists():m.actions.cache.update(read(p))
    m.actions.extra=read(m.actions.own) if m.actions.own.exists() else {}
    results=[];failed=[];runs=OUT/'runs';runs.mkdir(exist_ok=True)
    try:
        for i,d in enumerate(starts,1):
            start=str(d.date());path=runs/(start+'.json')
            if path.exists():result=read(path)
            else:
                try:
                    result,a=e.simulate(m,start,end,scenario='open_003_guaranteed',initial=100000,params={'SLIP_ONE_SIDE':.005})
                    assert a.m.SLIP_ONE_SIDE==.005 and not a.settle_sale_next_session
                    result['execution_policy']=protocol['effective_policy']
                    result['issues']=a.issues;result['reference']=a.reference_diffs
                    pd.DataFrame(a.curve).to_parquet(runs/(start+'_nav.parquet'),index=False)
                    pd.DataFrame(a.trades).to_parquet(runs/(start+'_trades.parquet'),index=False)
                    write(path,result)
                except Exception as exc:
                    failed.append(dict(start=start,error=str(exc),trace=traceback.format_exc()));write(OUT/'FAILURES.json',failed)
                    print('FAILED',i,len(starts),start,str(exc),flush=True);continue
            results.append(result)
            write(OUT/'PROGRESS.json',dict(completed=len(results),failed=len(failed),total=len(starts),last_start=start))
            print('PROGRESS',i,len(starts),start,'CAGR',round(result['cagr'],6),'issues',result['unresolved_actions'],result['reference_differences'],flush=True)
    finally:m.actions.close()
    write(OUT/'all_starts.json',results)
    assert not failed,'Incomplete set; no survivor-only average published'
    assert len(results)==len(starts) and before==inventory() and not writers()
    frame=pd.DataFrame(results);keys=['final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost','commission','stamp','dividend_tax','average_exposure']
    summary={k:{stat:float(getattr(frame[k],stat)()) for stat in ['mean','median','min','max','std']} for k in keys}
    quality=dict(unresolved_actions_total=int(frame.unresolved_actions.sum()),reference_differences_total=int(frame.reference_differences.sum()),rejected_orders_total=int(frame.rejected_orders.sum()))
    quality['fully_validated']=not any(quality.values())
    answer=dict(start_count=len(starts),first_start=str(starts[0].date()),last_start=str(starts[-1].date()),end=end,initial_cash=100000,slippage_one_side=.005,summary=summary,quality=quality)
    write(OUT/'SUMMARY.json',answer)
    labels={'final_equity':'期末资产（元）','total_return':'累计收益','cagr':'年化收益','max_drawdown':'最大回撤','sharpe':'Sharpe','trades':'成交笔数','total_cost':'总成本（元）','commission':'佣金（元）','stamp':'印花税（元）','dividend_tax':'股息税（元）','average_exposure':'平均仓位'}
    percents={'total_return','cagr','max_drawdown','average_exposure'};rows=[]
    for k,v in summary.items():
        cells=[format(v[s],'.2%' if k in percents else ',.3f' if k=='sharpe' else ',.2f') for s in ['mean','median','min','max']]
        rows.append('<tr><td>'+labels[k]+'</td>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>')
    page='<meta charset="utf-8"><title>沪深1 2019Q1全起点</title><style>body{font:16px sans-serif;margin:32px}td,th{padding:9px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>沪深1：2019Q1全部起点至'+end+'</h1><p>'+str(len(starts))+'个起点，各10万元。单边0.5%理想化保证成交；卖出款当日可用；佣金万三最低5元、卖出印花税0.1%、不单列过户费。原选股公式、5只、98%、20交易日相位保留。</p><p>各账户指标先分别计算，再取算术平均；起点重叠，不是独立样本或新盲测。2019使用既有已审计长历史预热排名。全历史补数暂存区失败且尚未提交，本次仅使用逐文件指纹核验通过的正式库。质量：'+html.escape(str(quality))+'</p><table><tr><th>指标</th><th>平均</th><th>中位数</th><th>最小</th><th>最大</th></tr>'+''.join(rows)+'</table>'
    (OUT/'report.html').write_text(page,encoding='utf-8');write(OUT/'COMPLETE.json',dict(summary_sha256=sha(OUT/'SUMMARY.json'),protocol_sha256=sha(OUT/'PROTOCOL.json')))
    print('COMPLETE',OUT,flush=True)


if __name__=='__main__':main()
