"""One fixed retrospective price-path observation, never strategy parameter selection."""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import datetime, hashlib, json, sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'leader_pattern_research/kline_viewer'))
from app import Store
from run_exit_study import prepare_frame

SL=.12
TP=.20

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def locked_down(row):
    rate=Decimal('.95') if str(row.isST)=='1' else Decimal('.90')
    lower=float((Decimal(str(row.preclose))*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    return abs(row.raw_high-row.raw_low)<.005 and abs(row.raw_close-lower)<.005

def simulate(f,t):
    if t+61>=len(f):return dict(status='incomplete_D61')
    if f.unknown.iloc[t+1:t+62].any():return dict(status='unknown_quote')
    first=f.iloc[t+1]
    if not first.active:return dict(status='D1_unavailable')
    entry=float(first.open);stop=entry*(1-SL);take=entry*(1+TP)
    pending=None;blocked=0;dual=0;buy_stop=False;buy_take=False
    entry_upper=abs(first.raw_high-first.raw_low)<.005 and first.raw_close>first.preclose+.005
    def finish(j,price,reason):
        return dict(status='closed',entry_date=str(f.index[t+1].date()),entry_price=entry,
            exit_date=str(f.index[j].date()),exit_price=float(price),exit_day=j-t,reason=reason,
            return_pct=float(price/entry-1),dual_touch=dual,blocked_days=blocked,
            buy_day_stop=buy_stop,buy_day_take=buy_take,entry_one_price_up=bool(entry_upper),
            worse_than_stop=bool(price<stop-1e-9),planned_end=str(f.index[t+61].date()))
    for j in range(t+1,len(f)):
        day=f.iloc[j];d=j-t
        if day.unknown:return dict(status='unknown_during_deferred_exit')
        if d==1:
            buy_stop=bool(day.low<=stop+1e-10);buy_take=bool(day.high>=take-1e-10)
            if buy_stop:pending='D1止损_T1次日退出'
            continue
        if not day.active:
            if d>=61:pending=pending or 'D60到期'
            continue
        if d>=61:pending=pending or 'D60到期'
        if pending:
            if locked_down(day):blocked+=1;continue
            return finish(j,float(day.open),pending)
        if day.open<=stop+1e-10:
            if locked_down(day):pending='跌停阻塞止损';blocked+=1;continue
            return finish(j,float(day.open),'跳空止损')
        if day.open>=take-1e-10:return finish(j,float(day.open),'跳空止盈')
        hit_sl=day.low<=stop+1e-10;hit_tp=day.high>=take-1e-10
        if hit_sl and hit_tp:dual+=1
        if hit_sl:
            if locked_down(day):pending='跌停阻塞止损';blocked+=1;continue
            return finish(j,stop,'同日双触先止损' if hit_tp else '止损')
        if hit_tp:return finish(j,take,'止盈')
    return dict(status='unresolved',blocked_days=blocked)

def summary(rows):
    g=pd.DataFrame(rows);closed=g[g.status.eq('closed')]
    if closed.empty:return dict(signals=len(g),closed=0,excluded=g.status.value_counts().to_dict())
    r=closed.return_pct
    def mean(x):return float(x.mean()) if len(x) else None
    return dict(signals=len(g),closed=len(closed),mean=mean(r),median=float(r.median()),win_rate=float(r.gt(1e-10).mean()),
        wins=int(r.gt(1e-10).sum()),losses=int(r.lt(-1e-10).sum()),flat=int(r.abs().le(1e-10).sum()),
        mean_win=mean(r[r.gt(1e-10)]),mean_loss=mean(r[r.lt(-1e-10)]),best=float(r.max()),worst=float(r.min()),
        mean_exit_day=float(closed.exit_day.mean()),exit_reasons=closed.reason.value_counts().to_dict(),
        dual_touch=int(closed.dual_touch.sum()),buy_day_stop=int(closed.buy_day_stop.sum()),buy_day_take=int(closed.buy_day_take.sum()),
        blocked_paths=int(closed.blocked_days.gt(0).sum()),entry_one_price_up=int(closed.entry_one_price_up.sum()),
        worse_than_stop=int(closed.worse_than_stop.sum()),excluded=g[~g.status.eq('closed')].status.value_counts().to_dict())

def main():
    store=Store()
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=ROOT/'box_exit_research/holdout_restricted'/('fixed_sl12_tp20_'+stamp);out.mkdir(parents=True,exist_ok=False)
    spec=dict(kind='one fixed retrospective adjusted-price observation; NOT new blind test or account backtest',
        stop=SL,take=TP,entry='signal D1 OPEN',exit='standing thresholds from D2; D1 stop latched to D2 OPEN; expiry D61 OPEN',
        same_day_dual_touch='opening gap priority, else stop first',gap='stop at adverse OPEN; profit at favorable OPEN',
        limit_down='no fill on one-price lower-limit bars; pending exit at next observable unlocked OPEN',
        universe='current merged SH/SZ mainboard leaders; report KEEP and ALL separately',
        fees=False,actual_share_and_dividend_ledger=False,extreme_return_pruning=False,
        generation=store.generation,cutoff=str(store.cutoff.date()),events_sha256=store.bundle['events_sha256'],
        manifest_sha256=store.bundle['manifest_sha256'],code_sha256=sha(__file__),
        no_optimization=True,future_results_not_for_optimization=True)
    dump(out/'SPEC.json',spec)
    signals=[r for r in store.signals(include_gaps=True)['signals'] if r['is_leader']]
    rows=[]
    for code in sorted({r['code'] for r in signals}):
        frames={}
        for mode in ['raw','qfq']:
            path=store.paths[(code,mode)];assert sha(path)==store.hashes[(code,mode)]
            frames[mode]=pd.read_parquet(path)
        f=prepare_frame(frames['raw'],frames['qfq'],store.dates)
        for s in [s for s in signals if s['code']==code]:
            t=store.dates.get_loc(pd.Timestamp(s['date']))
            keep=s['gap_down_count']==0 and s['gap_unfilled_count']==0
            result=simulate(f,t)
            rows.append(dict(event_id=s['id'],code=code,name=s['name'],signal_date=s['date'],year=int(s['year']),keep=bool(keep),**result))
    pd.DataFrame(rows).to_parquet(out/'signals.parquet',index=False)
    report={}
    for label,selection in [('leaders_keep',[r for r in rows if r['keep']]),('leaders_all',rows)]:
        report[label]=dict(overall=summary(selection),by_year={str(y):summary([r for r in selection if r['year']==y]) for y in sorted({r['year'] for r in selection})})
        pre=[r for r in selection if r['year']<=2024 and r.get('planned_end','9999')<='2024-12-31' and r.get('exit_date','9999')<='2024-12-31']
        report[label]['fully_pre2025']=summary(pre) if pre else {}
    dump(out/'SUMMARY.json',report)
    def pct(x):return '—' if x is None else f'{x*100:+.2f}%'
    lines=['固定-12%止损、+20%止盈：★当前合并龙头箱体信号',f'行情截至 {spec["cutoff"]}；不删极端收益；不是账户回测或新盲测。',
        'D1开盘买；T+1限制；D2起触价退出；D60仍未退出则D61开盘卖。开盘跳空优先，同日日内双触按先止损。',
        '前复权价格收益，未扣费，不含实际股数与分红现金账。当前龙头名单回看历史存在范围选择偏差。','']
    for key,name in [('leaders_keep','龙头＋保留标签'),('leaders_all','全部龙头箱体')]:
        r=report[key]['overall'];lines+=[name,f'原始信号 {r["signals"]}；完成 {r["closed"]}；排除 {r["excluded"]}',
            f'信号平均收益 {pct(r["mean"])}；中位数 {pct(r["median"])}；胜率 {pct(r["win_rate"])}',
            f'盈利均值 {pct(r["mean_win"])}；亏损均值 {pct(r["mean_loss"])}；最差 {pct(r["worst"])}；最好 {pct(r["best"])}',
            f'退出原因 {r["exit_reasons"]}；同日双触 {r["dual_touch"]}；跌停阻塞 {r["blocked_paths"]}；差于-12% {r["worse_than_stop"]}',
            '年份 | 完成信号 | 平均收益 | 胜率']
        for y,v in report[key]['by_year'].items():lines.append(f'{y} | {v["closed"]} | {pct(v.get("mean"))} | {pct(v.get("win_rate"))}')
        lines+=['']
    (out/'收益统计.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(output=str(out),cutoff=spec['cutoff'],report=report),ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
