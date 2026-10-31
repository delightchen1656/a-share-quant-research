"""One-way posterior: fixed 40% take-profit, maximum holding 20..90 sessions, no stop."""
from pathlib import Path
import datetime,hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
HORIZONS=list(range(20,91,10))
TP=.40
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def price_frame(q,r,dates):
    q=q.set_index('date').reindex(dates);r=r.set_index('date').reindex(dates)
    f=pd.DataFrame(index=dates)
    for k in ['open','high','low','close']:f[k]=pd.to_numeric(q[k],errors='coerce')
    f['valid']=r.tradestatus.astype(str).eq('1')&pd.to_numeric(r.volume,errors='coerce').gt(0)
    for k in ['open','high','low','close']:f['valid'] &= np.isfinite(f[k])&f[k].gt(0)
    return f,r

def eligibility(f,t,n):
    if t+n+1>=len(f):return 'not_mature'
    if not f.valid.iloc[t+1:t+n+2].all():return 'missing_or_suspended_quote'
    return 'eligible'

def selection_features(raw,t):
    # Signal formation only: cannot use D1 or anything later.
    r=raw.iloc[:t+1];b=r.iloc[t-15:t];volume=pd.to_numeric(b.volume,errors='coerce')
    up=pd.to_numeric(b.close,errors='coerce')>pd.to_numeric(b.open,errors='coerce')
    if len(b)!=15 or not volume.gt(0).all():raise ValueError('Invalid signal-time base')
    return dict(up_volume_share=float(volume[up].sum()/volume.sum()),
        signal_volume_ratio=float(pd.to_numeric(r.volume.iloc[t])/volume.mean()))

def simulate(f,t,n):
    status=eligibility(f,t,n)
    if status!='eligible':return dict(status=status)
    entry=float(f.open.iloc[t+1]);take=entry*(1+TP);d1_hit=bool(f.high.iloc[t+1]>=take-1e-10)
    # A-share T+1: D1 highs cannot be monetized on the buy day.
    for day in range(2,n+1):
        bar=f.iloc[t+day]
        if bar.open>=take-1e-10:
            return dict(status='closed',reason='take_profit_gap',entry=entry,exit=float(bar.open),return_pct=float(bar.open/entry-1),
                exit_day=day,exit_date=str(f.index[t+day].date()),d1_hit_not_sellable=d1_hit)
        if bar.high>=take-1e-10:
            return dict(status='closed',reason='take_profit_touch',entry=entry,exit=take,return_pct=TP,
                exit_day=day,exit_date=str(f.index[t+day].date()),d1_hit_not_sellable=d1_hit)
    price=float(f.open.iloc[t+n+1])
    return dict(status='closed',reason='forced_open',entry=entry,exit=price,return_pct=float(price/entry-1),
        exit_day=n+1,exit_date=str(f.index[t+n+1].date()),d1_hit_not_sellable=d1_hit)

def summarize(g):
    if not len(g):return dict(n=0,take_profit_n=0,forced_n=0,take_profit_rate=None,forced_mean=None,take_profit_mean=None,all_mean=None,win_rate=None)
    tp=g.reason.str.startswith('take_profit');forced=~tp
    def mean(v):return float(v.mean()) if len(v) else None
    return dict(n=len(g),take_profit_n=int(tp.sum()),forced_n=int(forced.sum()),take_profit_rate=float(tp.mean()),
        forced_mean=mean(g.loc[forced,'return_pct']),take_profit_mean=mean(g.loc[tp,'return_pct']),all_mean=mean(g.return_pct),
        forced_median=mean(pd.Series([g.loc[forced,'return_pct'].median()])) if forced.any() else None,
        forced_min=float(g.loc[forced,'return_pct'].min()) if forced.any() else None,win_rate=float(g.return_pct.gt(0).mean()),
        d1_only_hits=int(g.d1_hit_not_sellable.sum()))

def panel(results,events,pool,common=True,year=None):
    e=events.copy()
    if pool=='all':e=e[e.up_volume_share.ge(.6)]
    elif pool=='leaders':e=e[e.is_leader&e.up_volume_share.ge(.6)&e.signal_volume_ratio.ge(1.5)]
    else:raise ValueError(pool)
    if year is not None:e=e[e.year.eq(year)]
    if common:e=e[e.common_status.eq('eligible')]
    ids=set(e.event_id);r=results[results.event_id.isin(ids)&results.status.eq('closed')]
    return {str(n):summarize(r[r.horizon.eq(n)]) for n in HORIZONS}

def report(result,out):
    def pct(x):return '—' if x is None else f'{100*x:+.2f}%'
    lines=['单向后验：固定40%止盈，强制平仓时间20至90交易日、步长10',
        f'冻结行情截至 {result["cutoff"]}。按信号年份归组，信号范围2025—2026；跨年持仓继续至规则退出。',
        '信号D1开盘买入；D2至DN触及+40%自动止盈；开盘越过目标按开盘卖。D1受T+1限制不卖。',
        '未止盈则D(N+1)开盘强制卖出；到期日开盘先执行强平，强平单也可能盈利超过40%。不设止损。',
        '全量池沿用阳线量占比>=60%；龙头池使用阳线量占比>=60%且信号量>=横盘均量1.5倍；均不加保留标签过滤。',
        '为比较持有期，主表统一使用D1至D91完整有效的同一批信号。附表为每档截至日所有已成熟信号，分母可能不同。',
        '前复权价格路径、未扣税费、不模拟真实股数分红现金及涨跌停排队；不是账户收益。未合并重叠交易。',
        '全部参数在读取后验报价前固定，仅汇报结果，不从后验挑选参数或返回优化。此前已见过部分后验汇总，因此不是全新未见盲测。','']
    for mode,title in [('common_cohort','统一D91成熟样本'),('available_per_horizon','每档所有已成熟样本（仅补充）')]:
        lines+=[title]
        for pool,name in [('all','全量池'),('leaders','龙头池')]:
            for year in ['overall','2025','2026']:
                lines += [f'{name} / {year}','最长持有日 | 样本 | 止盈数量 | 止盈率 | 强平数量 | 强平平均收益 | 止盈平均收益 | 全部平均收益']
                for n,row in result[mode][pool][year].items():lines.append(f'{n} | {row["n"]} | {row["take_profit_n"]} | {pct(row["take_profit_rate"])} | {row["forced_n"]} | {pct(row["forced_mean"])} | {pct(row["take_profit_mean"])} | {pct(row["all_mean"])}')
                lines+=['']
    lines += ['信号与缺失审计',json.dumps(result['cohort_audit'],ensure_ascii=False,indent=2)]
    (out/'止盈数量与强平收益.txt').write_text('\n'.join(lines),encoding='utf-8')

def main():
    pointer=json.loads((HERE/'holdout_restricted/LATEST_IMPROVE40.json').read_text(encoding='utf-8'))
    candidate=Path(pointer['path'])/'FROZEN_LEADER_RULE_CANDIDATE.json'
    c=json.loads(candidate.read_text(encoding='utf-8'));assert [x['threshold'] for x in c['conditions']]==[.6,1.5]
    current=ROOT/'leader_pattern_research/market_wide/holdout_restricted/CURRENT.json';b=json.loads(current.read_text(encoding='utf-8'))
    assert b['status']=='ok' and b['scope']=='SH_SZ_MAIN_BOARD_ONLY'
    for key in ['events','manifest','universe']:assert sha(b[key])==b[key+'_sha256']
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('posterior_holding20_90_tp40_'+stamp);out.mkdir(parents=True,exist_ok=False)
    dump(out/'FROZEN_SPEC.json',dict(horizons=HORIZONS,take_profit=TP,stop_loss=None,entry='signal D1 adjusted OPEN',
        trigger_window='D2..DN; T+1 blocks D1',expiry='D(N+1) OPEN',pools=dict(all='base up-volume share>=.60',leaders='current leader AND share>=.60 AND signal/base volume>=1.5'),
        common_cohort='D1..D91 complete valid quotations; per-horizon availability also disclosed',
        candidate_sha256=sha(candidate),source_generation=b['generation'],source_events_sha256=b['events_sha256'],source_manifest_sha256=b['manifest_sha256'],
        code_sha256=sha(__file__),after2024_one_way_only=True,no_refit=True,no_parameter_selection_from_posterior=True,not_fresh_blind=True,
        prices_not_cash_share_ledger=True,fees=False,execution_queue_simulated=False))
    cols=['event_id','code','name','signal_date','year','is_leader']
    events=pd.read_parquet(b['events'],columns=cols);events=events[events.signal_date.ge('2025-01-01')&events.signal_date.le(b['cutoff'])]
    assert events.code.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(b['calendar']).date));dates=dates[dates<=b['cutoff']]
    manifest=json.loads(Path(b['manifest']).read_text(encoding='utf-8'));lookup={(r['code'],r['mode']):r for r in manifest['files']}
    rows=[];event_rows=[];quote_audit=[]
    for code,group in events.groupby('code'):
        frames={}
        for mode in ['qfq','raw']:
            rec=lookup[(code,mode)];path=Path(rec['path']);assert sha(path)==rec['snapshot_sha256']
            frames[mode]=pd.read_parquet(path);quote_audit.append(dict(code=code,mode=mode,sha256=rec['snapshot_sha256']))
        f,raw=price_frame(frames['qfq'],frames['raw'],dates)
        for event in group.to_dict('records'):
            t=dates.get_loc(pd.Timestamp(event['signal_date']));sf=selection_features(raw,t)
            event_rows.append(dict(**event,**sf,common_status=eligibility(f,t,90)))
            for n in HORIZONS:rows.append(dict(event_id=event['event_id'],year=int(event['year']),horizon=n,**simulate(f,t,n)))
    e=pd.DataFrame(event_rows);r=pd.DataFrame(rows)
    e.to_parquet(out/'events_and_cohort.parquet',index=False);r.to_parquet(out/'per_signal_results.parquet',index=False);dump(out/'QUOTE_HASH_AUDIT.json',quote_audit)
    result=dict(cutoff=b['cutoff'],cohort_audit={},common_cohort={},available_per_horizon={})
    for pool in ['all','leaders']:
        selected=e[e.up_volume_share.ge(.6)] if pool=='all' else e[e.is_leader&e.up_volume_share.ge(.6)&e.signal_volume_ratio.ge(1.5)]
        result['cohort_audit'][pool]=dict(signals=len(selected),common_status=selected.common_status.value_counts().to_dict(),
            by_year={str(y):g.common_status.value_counts().to_dict() for y,g in selected.groupby('year')})
        for mode,common in [('common_cohort',True),('available_per_horizon',False)]:
            result[mode][pool]={key:panel(r,e,pool,common,year) for key,year in [('overall',None),('2025',2025),('2026',2026)]}
    for pool in ['all','leaders']:
        p=result['common_cohort'][pool]['overall'];assert len({v['n'] for v in p.values()})==1
        assert all(v['take_profit_n']+v['forced_n']==v['n'] for v in p.values())
        assert all(p[str(a)]['take_profit_n']<=p[str(b)]['take_profit_n'] for a,b in zip(HORIZONS,HORIZONS[1:]))
    dump(out/'SUMMARY.json',result);report(result,out)
    dump(HERE/'holdout_restricted/LATEST_POSTERIOR_HOLDING_GRID.json',dict(path=str(out),code_sha256=sha(__file__)))
    print(json.dumps(dict(output=str(out),**result),ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
