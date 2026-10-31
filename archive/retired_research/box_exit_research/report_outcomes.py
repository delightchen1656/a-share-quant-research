"""Conditional wins, stop losses and close-path drawdowns; retrospective sensitivity only."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from run_exit_study import INPUT,OUT,sha,dump,prepare_frame,finite

def main():
    audit=json.loads((OUT/'AUDIT.json').read_text(encoding='utf-8'));assert sha(OUT/'event_exits.parquet')==audit['results_sha256']
    data=pd.read_parquet(OUT/'event_exits.parquet');manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'))
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_json(INPUT/'calendar.json').date));lookup={(r['code'],r['mode']):r for r in manifest['files']}
    source_hash=sha(OUT/'event_exits.parquet');drawdowns={}
    for code,g in data.groupby('code'):
        frames={}
        for mode in ['raw','qfq']:
            rec=lookup[(code,mode)];assert sha(rec['path'])==rec['sha256'];frames[mode]=pd.read_parquet(rec['path'])
        f=prepare_frame(frames['raw'],frames['qfq'],dates)
        for r in g.itertuples():
            if r.status!='estimated_exit':continue
            t=dates.get_loc(pd.Timestamp(r.signal_date));j=t+int(r.exit_day)
            before_exit=f.iloc[t+1:j];closes=before_exit.loc[before_exit.active,'close'].to_numpy(float)
            values=np.r_[r.entry,closes,r.exit_price]
            dd=float(np.min(values/np.maximum.accumulate(values)-1))
            drawdowns[(r.event_id,r.rule)]=dd
    data['holding_close_drawdown']=[drawdowns.get((r.event_id,r.rule),np.nan) for r in data.itertuples()]
    rows=[];tables=[]
    for mode in ['all','exclude_peak_ge100']:
        d=data if mode=='all' else data[data.benchmark_gain60.lt(1)]
        for rule,g in d.groupby('rule'):
            g=g[g.status.eq('estimated_exit')]
            win=g[g.exit_return.gt(1e-10)];loss=g[g.exit_return.lt(-1e-10)]
            stops=loss[loss.exit_reason.isin(['stop_touch','gap_stop','stop_pending_limit'])]
            row=dict(mode=mode,rule=rule,signals=len(g),removed_extremes=int(data[data.rule.eq(rule)].benchmark_gain60.ge(1).sum()) if mode!='all' else 0,
                wins=len(win),mean_win=finite(win.exit_return.mean()),losses=len(loss),mean_loss=finite(loss.exit_return.mean()),
                stoplosses=len(stops),mean_stoploss=finite(stops.exit_return.mean()),
                mean_stoploss_holding_drawdown=finite(stops.holding_close_drawdown.mean()),
                worst_stoploss=finite(stops.exit_return.min()),mean_all=finite(g.exit_return.mean()),
                mean_holding_drawdown=finite(g.holding_close_drawdown.mean()))
            assert row['wins']+row['losses']+int(g.exit_return.abs().le(1e-10).sum())==len(g)
            assert row['mean_stoploss_holding_drawdown']<=row['mean_stoploss']+1e-10
            peak10=g[g.benchmark_gain60.ge(.10)]
            row['capture70_n']=int((peak10.exit_return>=.7*peak10.benchmark_gain60-1e-10).sum())
            row['peak10_n']=len(peak10)
            row['median_capture_peak10']=finite((peak10.exit_return/peak10.benchmark_gain60).median())
            rows.append(row)
        tables.append(mode)
    target=OUT/'conditional_outcomes_v1';target.mkdir(exist_ok=True)
    data.to_parquet(target/'event_outcomes.parquet',index=False);dump(target/'summary.json',rows)
    specs=dict(entry='Ideal signal close; exit from D1; no fees; no account/share ledger',
        data_end='2024-12-31',source_signals=135,full_horizon_after_cohort_purge=121,
        extreme_sensitivity='Retrospectively omit future maximum gain>=100% from descriptive averages only; not a live trade rule',
        stoploss='Exit return <0 AND exit reason is known standing stop touch, gap stop, or previously blocked stop',
        holding_drawdown='Min(value/cumulative peak -1) over entry, daily ACTIVE closes strictly before exit day, and estimated exit price. Excludes exit-day close after sale.',
        no_intraday_drawdown_claim=True,no_blind_test_claim=True,source_results_sha256=source_hash)
    dump(target/'SPEC.json',specs)
    labels={'fixed5':'5%止损','fixed8':'8%止损','box_cap8':'箱底止损（风险上限8%）',
        'none':'只设止损，D60退出','profit70':'浮盈达10%后保留已见浮盈70%',
        'atr25':'浮盈达10%后2.5ATR跟踪','ma5':'浮盈达10%后跌破MA5次日退出','ma10':'浮盈达10%后跌破MA10次日退出'}
    pct=lambda x:'—' if x is None else f'{x:+.2%}'
    lines=['盈利与止损条件统计（★当前合并龙头＋保留标签）',
        '只使用2019—2024行情；135次信号，剔除14次跨分组年末边界，121次共同可观察信号。',
        '信号收盘价理想买入，不计费；日线估算成交，不是实盘可执行承诺。',
        '平均亏损为退出价相对买价；持仓回撤为持仓收盘序列（加退出价）相对此前高点的最大跌幅。','']
    for mode in tables:
        lines.append('全部样本' if mode=='all' else '剔除未来最大涨幅≥100%的3次极端样本（仅描述统计）')
        lines.append('初始止损 | 退出方式 | 盈利笔数 | 盈利平均收益 | 止损亏损笔数 | 止损平均亏损 | 止损单平均持仓回撤 | 全部信号均值')
        for stop in ['fixed5','fixed8','box_cap8']:
            for method in ['none','profit70','atr25','ma5','ma10']:
                r=next(r for r in rows if r['mode']==mode and r['rule']==stop+'__'+method)
                lines.append(f"{labels[stop]} | {labels[method]} | {r['wins']} | {pct(r['mean_win'])} | {r['stoplosses']} | {pct(r['mean_stoploss'])} | {pct(r['mean_stoploss_holding_drawdown'])} | {pct(r['mean_all'])}")
        lines.append('')
    (target/'盈利与止损统计.txt').write_text('\n'.join(lines),encoding='utf-8')
    assert sha(OUT/'event_exits.parquet')==source_hash
    dump(target/'AUDIT.json',dict(status='ok',source_unchanged=True,conditional_count_reconciled=True,drawdown_before_exit_only=True,
        summary_sha256=sha(target/'summary.json'),results_sha256=sha(target/'event_outcomes.parquet')))
    print('\n'.join(lines),flush=True)
    print(json.dumps([r for r in rows if r['mode']=='exclude_peak_ge100' and r['rule'].endswith('__profit70')],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
