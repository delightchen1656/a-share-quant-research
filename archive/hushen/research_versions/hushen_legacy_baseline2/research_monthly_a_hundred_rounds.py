"""Exactly 100 unique configurations, after auditable warmup/execution correction."""
import hashlib
import itertools
import json
import time
import sys
import numpy as np
import pandas as pd
import group_research as g
import monthly_A_aligned_engine as e
from start_date_robustness import measure
from robust_policy_search import summarize
from approximate_parity_gate import compare,LIMITS

HERE=g.HERE
ALIGN=HERE/'monthly_A_alignment_20260924'
OUT=HERE/'monthly_A_100_rounds'
EXISTING_HISTORY='--existing-history' in sys.argv
FACTORS=(HERE/'cadence_multiround_100k/exact_date_factors.parquet') if EXISTING_HISTORY else (ALIGN/'exact_date_factors.parquet')
if EXISTING_HISTORY:OUT=HERE/'monthly_A_100_rounds_existing_history'
MODEL_OUT=ALIGN/'existing_history_diagnostics' if EXISTING_HISTORY else ALIGN

def write(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def grid():
    rows=[]
    for family,count,exposure,power in itertools.product(('monthly','weekly_guard'),(5,6,7,8,9),(.70,.75,.80,.85,.90),(.50,.75)):
        rows.append(dict(id='R%03d'%(len(rows)+1),family=family,count=count,exposure=exposure,power=power,buffer=24,minimum=3000,threshold=.12))
    assert len(rows)==100
    return rows

BASE=dict(id='BASE',family='monthly',count=6,exposure=.8,power=.5,buffer=24,minimum=3000,threshold=.12)

class Research:
    def __init__(self):
        idx=pd.read_parquet(e.DATA/'indices/000905.SH.parquet')
        idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
        self.cal=pd.DatetimeIndex(idx.date.drop_duplicates());e.CALENDAR=self.cal
        self.ranks={};self.oldranks={};self.draw={};self.eligible={}
        for kind,path in [('warm',FACTORS),('old',HERE/'cadence_multiround_100k/exact_date_factors.parquet')]:
            f=pd.read_parquet(path)
            for d,x in f.groupby('execute_date'):
                x=x.sort_values('symbol').copy();assert x.signal_date.max()<d
                hist=idx[idx.date<=x.signal_date.iloc[0]]
                strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
                self.draw[d]=hist.close.iloc[-1]/hist.close.tail(60).max()-1
                x['score']=.25*e.rank01(x.amount20.to_numpy(),True)+.20*e.rank01(x.near_high.to_numpy())+.55*e.rank01(x.dividend.to_numpy())
                r=x if strong else g.score(x[x.float_cap_proxy_group==1],'quality')
                ranked=r.sort_values(['score','symbol'],ascending=[False,True])
                target=self.ranks if kind=='warm' else self.oldranks
                target[d]=ranked[['symbol','downside']].head(24).copy()
                if kind=='warm':self.eligible[d]=len(ranked)
            del f
        symbols=set().union(*(set(x.symbol) for rr in (self.ranks,self.oldranks) for x in rr.values()))
        panel=e.load_daily_panel(symbols)
        e.PREPARED={pd.Timestamp(d):x.set_index('symbol') for d,x in panel.groupby('date')}
        self.panel=panel
        self.initial=(e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION)
        e.INITIAL_CASH=100000.
        ledger=json.loads((ALIGN/'action_ledger/manifest.json').read_text(encoding='utf-8'))
        assert all('error' not in r for r in ledger['results'])
        e.ACTION_LEDGER={}
        for item in ledger['results']:
            for record in item['rows']:
                if not record.get('dividOperateDate'):continue
                d=pd.Timestamp(record['dividOperateDate'])
                num=lambda key:float(record.get(key) or 0)
                event=dict(cash=num('dividCashPsBeforeTax'),bonus=num('dividStocksPs')+num('dividReserveToStockPs'),
                    pay_date=pd.Timestamp(record.get('dividPayDate') or str(d.date())),
                    stock_date=pd.Timestamp(record.get('dividStockMarketDate') or str((d+pd.Timedelta(days=1)).date())))
                key=(d,item['symbol'])
                if key in e.ACTION_LEDGER:assert e.ACTION_LEDGER[key]==event,('Conflicting action records',key)
                e.ACTION_LEDGER[key]=event
        first=pd.DatetimeIndex(g.features().execute_date.unique()).sort_values()
        expand=lambda ss:[self.cal[self.cal.get_loc(d)+n] for d in ss for n in (0,5,10)]
        self.dev=expand([d for d in first if d.year in (2020,2021) and d.month in (1,4,7,10)])
        self.audit=expand([d for d in first if d.year==2024 and d.month<=8])

    def run(self,cfg,start,stress=False,old=False,round_fees=True,full=False,trace=False,legacy_actions=False):
        end=pd.Timestamp('2026-09-11') if full else start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        assert end<=pd.Timestamp('2026-09-11')
        e.START=start;e.END=end;e.ROUND_FEES=round_fees
        e.ACTION_MODE='legacy' if legacy_actions else 'ledger'
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[v*(2 if stress else 1) for v in self.initial]
        source=self.oldranks if old else self.ranks
        monthly={start}
        for due in pd.date_range(start.replace(day=1),end,freq='MS'):
            d=self.cal[self.cal.searchsorted(due)]
            if start<d<=end:monthly.add(d)
        rr={}
        for d in sorted(monthly):
            r=source[d].copy();r['downside']=r.downside.pow(cfg['power']);rr[d]=r
        def cap(d):
            if cfg['family']=='monthly':return cfg['exposure']
            v=self.draw[d];t=cfg['threshold']
            return min(cfg['exposure'],.2 if v<-(t+.05) else (.4 if v<-t else cfg['exposure']))
        ee={d:cap(d) for d in rr};limits={}
        if cfg['family']=='weekly_guard':
            for due in pd.date_range(start,end,freq='W-MON'):
                d=self.cal[self.cal.searchsorted(due)]
                if d>end or d in monthly or cap(d)>=cfg['exposure']:continue
                prior=max(m for m in monthly if m<d)
                rr[d]=rr[prior];ee[d]=cfg['exposure'];limits[d]=cap(d)
        e.SELECTION_TRACE=[] if trace else None
        curve,trades=e.simulate(rr,.05,cfg['count'],cfg['buffer'],ee,1.5,self.panel,min_adjustment=cfg['minimum'],risk_only_limits=limits)
        assert (curve.cash>=-.01).all()
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        assert not ((trades.date.isin(limits))&(trades.side=='BUY')).any()
        stats=dict(**measure(curve),fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS),start=str(start.date()),end=str(curve.date.iloc[-1].date()))
        return stats,curve,trades,e.SELECTION_TRACE

    def alignment(self):
        MODEL_OUT.mkdir(exist_ok=True)
        platform=pd.read_json(ALIGN/'platform_nav.json');platform['date']=pd.to_datetime(platform.date)
        pt=pd.read_json(ALIGN/'platform_trades.json');pt['date']=pd.to_datetime(pt.date)
        signals=json.loads((ALIGN/'platform_signals.json').read_text(encoding='utf-8'))
        models=[]
        for label,old,rounded,legacy in [('old_reproduction',True,False,True),('warm_history',False,False,True),('warm_history_cent_fees',False,True,True),('warm_history_action_ledger',False,True,False)]:
            if EXISTING_HISTORY:label=label.replace('warm_history','existing_history')
            stats,c,t,trace=self.run(BASE,self.dev[0],old=old,round_fees=rounded,full=True,trace=True,legacy_actions=legacy)
            if old:
                expected=json.loads((HERE/'two_family_return_sharpe_100k/summary.json').read_text(encoding='utf-8'))
                ref=next(r for r in expected['full'] if r['name']=='monthly_power_0.5')
                for k in ('final_equity','annualized','drawdown','sharpe'):assert abs(stats[k]-ref[k])<1e-7,(k,stats[k],ref[k])
            parity,_=compare(c,platform)
            matched=t.merge(pt,on=['date','symbol','side'],suffixes=('_local','_platform'))
            selections=[];by={r['date']:r for r in trace}
            for signal in signals:
                if signal['date'] not in by:continue
                local=by[signal['date']]['selected']
                selections.append(dict(date=signal['date'],platform=signal['selected'],local=local,overlap=len(set(local)&set(signal['selected']))))
            model=dict(model=label,metrics=stats,parity=parity,matched_trades=len(matched),local_trades=len(t),platform_common_trades=int((pt.date<=c.date.max()).sum()),exact_quantity=int((matched.quantity_local==matched.quantity_platform).sum()),selection_mean_overlap=float(np.mean([r['overlap'] for r in selections])),first_selection=selections[0])
            models.append(model)
            write(MODEL_OUT/(label+'_curve.json'),json.loads(c.to_json(orient='records',date_format='iso')))
            write(MODEL_OUT/(label+'_trades.json'),json.loads(t.to_json(orient='records',date_format='iso')))
            write(MODEL_OUT/(label+'_selections.json'),selections)
            print('ALIGN',label,json.dumps(model,ensure_ascii=False),flush=True)
        write(MODEL_OUT/'alignment_results.json',dict(limits=LIMITS,models=models,minute_parity=False,history_repaired=not EXISTING_HISTORY,
            note='Existing history remains under-warmed in early years.' if EXISTING_HISTORY else 'Warmup repaired. Fees and independent company-action ledger corrected. Minute execution remains approximate.'))
        return models[-1]

def admissible(a,b):
    return a['median']>b['median']+.001 and a['sharpe']>b['sharpe']+.01 and a['p10']>=b['p10']-.01 and a['drawdown']>=b['drawdown']-.02

def main():
    OUT.mkdir(exist_ok=True)
    if '--alignment-only' in sys.argv:
        Research().alignment();return
    configs=grid()
    write(OUT/'protocol.json',dict(configs=configs,round_definition='Exactly100 unique combinations, each24 development windows; not100 copies of one backtest.',
        axes='2families x5counts(5..9) x5exposures(.70..90 step.05) x2powers(.5,.75); fixed buffer24/min3000/calendar-month1; weekly threshold12/17%.',
        development='2020/2021 Jan Apr Jul Oct +0/5/10 sessions, each24months',audit='2024 Jan-Aug +0/5/10 sessions, each24months',
        selection='Per family freeze max annual gain/2pp +Sharpe gain/.1, subject to annual>BASE+.1pp, Sharpe>BASE+.01,P10>=BASE-1pp,worstDD>=BASE-2pp. Common BASE is aligned monthlyA6/.8/.5. No audit reselection.',
        validation='Same gate on audit, double-cost audit annual/Sharpe>=BASE, P10>=BASE-1pp,DD>=BASE-2pp. Opposite power neighbor must keep dev annual>=BASE-1pp,P10>=BASE-1pp,Sharpe>=BASE-.05,DD>=BASE-2pp.',
        alignment_policy='Fix independently evidenced warmup/fee units and large-action ledger first. Preserve existing parity gate; if it fails, all100rounds are provisional local research, never platform-validated or automatic promotion.',
        history_repaired=not EXISTING_HISTORY,
        limitations='Previously seen overlapping windows,100way multiple testing, frozen universe, approximate corporate actions, no minute bars. Full period shown after selection only. Early-history under-warmup remains when existing-history flag used.'))
    fingerprint=hashlib.sha256()
    for path in (FACTORS,ALIGN/'action_ledger/manifest.json',HERE/'monthly_A_aligned_engine.py',HERE/'monthly_A_hundred_rounds.py'):
        with path.open('rb') as handle:
            for block in iter(lambda:handle.read(1024*1024),b''):fingerprint.update(block)
    stamp=fingerprint.hexdigest();checkpoint=OUT/'checkpoint_fingerprint.json'
    if checkpoint.exists():assert json.loads(checkpoint.read_text())['sha256']==stamp,'Checkpoint inputs changed: use a new output folder'
    else:write(checkpoint,dict(sha256=stamp))
    r=Research();alignment=r.alignment()
    rows=json.loads((OUT/'results.json').read_text(encoding='utf-8')) if (OUT/'results.json').exists() else []
    cached={(z['id'],z['split'],z['start']):z for z in rows}
    assert len(cached)==len(rows)
    development={}
    for cfg in configs:
        started=time.monotonic();group=[]
        for start in r.dev:
            key=(cfg['id'],'dev',str(start.date()))
            if key in cached:row=cached[key]
            else:
                stats,*_=r.run(cfg,start);row=dict(id=cfg['id'],split='dev',**stats);rows.append(row)
            group.append(row)
        development[cfg['id']]=summarize(group)
        write(OUT/'development.json',development);write(OUT/'results.json',rows)
        print('ROUND',cfg['id'],json.dumps(development[cfg['id']]),'seconds',round(time.monotonic()-started,1),flush=True)
    base=next(c for c in configs if c['family']=='monthly' and c['count']==6 and c['exposure']==.8 and c['power']==.5)
    baseline=development[base['id']]
    winners={}
    for family in ('monthly','weekly_guard'):
        eligible=[c for c in configs if c['family']==family and admissible(development[c['id']],baseline)]
        winners[family]=max(eligible,key=lambda c:(development[c['id']]['median']-baseline['median'])/.02+(development[c['id']]['sharpe']-baseline['sharpe'])/.10) if eligible else None
    write(OUT/'frozen_winners.json',dict(base=base,winners=winners))
    chosen={c['id']:c for c in [base]+[c for c in winners.values() if c is not None]}
    validation={};full={}
    for cfg in chosen.values():
        validation[cfg['id']]={}
        for split,stress in [('audit',False),('stress_audit',True)]:
            group=[]
            for start in r.audit:
                key=(cfg['id'],split,str(start.date()))
                if key in cached:row=cached[key]
                else:
                    stats,*_=r.run(cfg,start,stress=stress);row=dict(id=cfg['id'],split=split,**stats);rows.append(row)
                group.append(row)
            z=summarize(group);validation[cfg['id']][split]=z
            write(OUT/'results.json',rows);write(OUT/'validation.json',validation)
            print('VALIDATE',cfg['id'],split,json.dumps(z),flush=True)
        stats,c,t,_=r.run(cfg,r.dev[0],full=True)
        full[cfg['id']]=stats
        write(OUT/(cfg['id']+'_full_curve.json'),json.loads(c.to_json(orient='records',date_format='iso')))
    passed={};neighbors={}
    for family,cfg in winners.items():
        if cfg is None:passed[family]=False;continue
        neighbor=next(c for c in configs if all(c[k]==cfg[k] for k in ('family','count','exposure')) and c['power']!=cfg['power'])
        n=development[neighbor['id']];neighbors[family]=neighbor['id']
        stable=n['median']>=baseline['median']-.01 and n['p10']>=baseline['p10']-.01 and n['sharpe']>=baseline['sharpe']-.05 and n['drawdown']>=baseline['drawdown']-.02
        a=validation[cfg['id']];b=validation[base['id']];sa=a['stress_audit'];sb=b['stress_audit']
        passed[family]=bool(stable and admissible(a['audit'],b['audit']) and sa['median']>=sb['median'] and sa['sharpe']>=sb['sharpe'] and sa['p10']>=sb['p10']-.01 and sa['drawdown']>=sb['drawdown']-.02)
    summary=dict(rounds=len(configs),development_windows=2400,validation_windows=len(rows)-2400,full_runs=len(full),alignment_runs=4,base=base,winners=winners,neighbors=neighbors,local_validation_passed=passed,platform_parity=alignment['parity']['passed'],minute_parity=False,history_repaired=not EXISTING_HISTORY,development=development,validation=validation,full=full)
    write(OUT/'summary.json',summary)
    lines=['# 月初A口径修正后100轮研究','','每轮一个独立参数组合，24个开发起点。100轮共2400个开发窗口；后段仅验证冻结候选。','',
        '| 轮次 | 路线 | 持股数 | 仓位 | 风险权重指数 | 年化中位数 | P10 | 最差回撤 | Sharpe |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for cfg in configs:
        z=development[cfg['id']];lines.append('|%s|%s|%d|%.0f%%|%.2f|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(cfg['id'],'月初' if cfg['family']=='monthly' else '周防',cfg['count'],cfg['exposure']*100,cfg['power'],z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','| 版本 | 验证 | 年化中位数 | P10 | 最差回撤 | Sharpe |','|---|---|---:|---:|---:|---:|']
    for name,tests in validation.items():
        for test,z in tests.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(name,test,z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','| 版本 | 全历史终值 | 年化 | 最大回撤 | Sharpe |','|---|---:|---:|---:|---:|']
    for name,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(name,z['final_equity'],z['annualized']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','候选：'+json.dumps(winners,ensure_ascii=False),'本地验证通过：'+json.dumps(passed),'近似平台对齐门槛：'+str(alignment['parity']['passed']),
        '早期历史补齐：'+str(not EXISTING_HISTORY)+'；未补齐时，2020等早期窗口存在因子预热不足，仅为有明确数据限制的本地研究。',
        '实际分钟撮合仍未复现。所有历史反复研究且窗口重叠，100组比较会增加过拟合风险，不能视为独立样本外。未覆盖正式策略或原始行情。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps({k:summary[k] for k in ('rounds','development_windows','validation_windows','local_validation_passed','platform_parity')}),flush=True)

if __name__=='__main__':main()
