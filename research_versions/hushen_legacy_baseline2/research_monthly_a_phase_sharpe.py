"""Fixed cash sleeves with staggered monthly dates; no fee-free NAV blending."""
import json,itertools
import numpy as np
import pandas as pd
import monthly_A_structure_research as s
from supermind_performance import measure
from robust_policy_search import summarize
e=s.e;HERE=s.HERE;OUT=HERE/'monthly_A_phase_sharpe_20260925'
BASE=dict(id='BASE',count=6,offsets=[0],strict=False)
CONFIGS=[BASE]+[dict(id='P%d'%(i+1),count=n,offsets=offsets,strict=True) for i,(n,offsets) in enumerate(itertools.product((2,3,4),([0,10],[0,5,10])))]
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class Study:
    def __init__(self):
        s.CONFIGS=[dict(id='BASE')];old=s.Study();self.cal=old.cal;self.dev=old.dev;self.audit=old.audit;self.initial=old.initial
        self.months={}
        for d in self.cal:
            if d.year>=2020:self.months.setdefault((d.year,d.month),[]).append(d)
        needed=set(self.dev+self.audit)
        for days in self.months.values():needed.update(days[min(i,len(days)-1)] for i in (0,5,10))
        self.bridge=[days[0] for (y,m),days in self.months.items() if y in (2022,2023) and m in (1,4,7,10)]
        f=pd.read_parquet(HERE/'cadence_multiround_100k/exact_date_factors.parquet');self.ranks={};symbols=set()
        idx=pd.read_parquet(e.DATA/'indices/000905.SH.parquet').sort_values('date');idx['date']=pd.to_datetime(idx.date)
        for d,q in f[f.execute_date.isin(needed)].groupby('execute_date'):
            assert q.signal_date.max()<d
            h=idx[idx.date<=q.signal_date.iloc[0]];strong=h.close.iloc[-1]>h.close.tail(120).mean();q=q.sort_values('symbol').copy()
            if strong:q['score']=.25*e.rank01(q.amount20.to_numpy(),True)+.20*e.rank01(q.near_high.to_numpy())+.55*e.rank01(q.dividend.to_numpy())
            else:q=s.g.score(q[q.float_cap_proxy_group==1],'quality')
            ranked=q.sort_values(['score','symbol'],ascending=[False,True]).head(24);self.ranks[d]=ranked[['symbol','downside']];symbols.update(ranked.symbol)
        self.panel=e.load_daily_panel(symbols);e.PREPARED={pd.Timestamp(d):q.set_index('symbol') for d,q in self.panel.groupby('date')}

    def run(self,cfg,start,stress=False,full=False):
        end=pd.Timestamp('2026-09-11') if full else start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        n=len(cfg['offsets']);capital=[round(100000/n,2)]*(n-1);capital.append(100000-sum(capital))
        curves=[];fees=0.;orders=0;unresolved=0
        for j,offset in enumerate(cfg['offsets']):
            e.START=start;e.END=end;e.INITIAL_CASH=capital[j];e.ROUND_FEES=True;e.ACTION_MODE='ledger';e.STRICT_TARGET=cfg['strict']
            e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[]
            e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[v*(2 if stress else 1) for v in self.initial]
            dates={start}
            for days in self.months.values():
                d=days[min(offset,len(days)-1)]
                if start<d<=end:dates.add(d)
            ranks={d:self.ranks[d].assign(downside=self.ranks[d].downside.pow(.5)) for d in sorted(dates)}
            curve,trades=e.simulate(ranks,.05,cfg['count'],4*cfg['count'],.8,1.5,self.panel,min_adjustment=3000/n)
            assert curve.cash.min()>=-.01
            assert (trades[trades.side=='BUY'].quantity%100==0).all()
            assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
            if cfg['strict']:assert all(len(t['selected'])<=cfg['count'] for t in e.SELECTION_TRACE)
            curves.append(curve.set_index('date').equity);fees+=float((trades.commission+trades.stamp_tax).sum());orders+=len(trades);unresolved+=len(e.UNRESOLVED_ACTIONS)
        combined=pd.concat(curves,axis=1);assert not combined.isna().any().any()
        curve=combined.sum(axis=1).rename('equity').reset_index();z=measure(curve,risk_free_annual=.02)
        return dict(**z,start=str(start.date()),end=str(curve.date.iloc[-1].date()),fees=fees,orders=orders,unresolved_actions=unresolved),curve

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists()
    save('protocol.json',dict(configs=CONFIGS,rf=.02,selection='Dev top2 Sharpe with annual>=BASE-2pp,P10>=BASE-1pp,worstDD>=BASE-2pp;freeze before validations.',
        goal='Full Sharpe>=1,audit median>=1,bridge median>=1;full annual>=BASE-2pp,fullDD>=BASE-2pp;audit annual>=BASE-2pp,DD>=BASE-2pp;stressSharpe>=BASE-.02,stressannual>=BASE-2pp.',
        implementation='100k divided into2/3 non-transferring cash sleeves;each pays actual min5 commission/lot100;target80%;minadjust3000/number sleeves;all enter at start then trade month session offsets. No leverage, no fee-free blending;duplicates not netted. Actual broker pooling remains unverified.',
        caveats='Already-seen overlapping history;daily fill proxy;early history incomplete;not platform parity. This independent6-combination branch is explicit additional multiple testing.'))
    study=Study();rows=[];dev={}
    def group(cfg,split,dates,stress=False):
        batch=[]
        for start in dates:
            z,_=study.run(cfg,start,stress=stress);z.update(id=cfg['id'],split=split);batch.append(z);rows.append(z)
        out=summarize(batch);save('windows.json',rows);print(split,cfg['id'],json.dumps(out),flush=True);return out
    for c in CONFIGS:dev[c['id']]=group(c,'dev',study.dev);save('development.json',dev)
    b=dev['BASE'];pool=[c for c in CONFIGS[1:] if dev[c['id']]['median']>=b['median']-.02 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2];save('frozen_winners.json',winners)
    validation={};full={}
    for c in [BASE]+winners:
        cid=c['id'];validation[cid]={}
        for split,dates,stress in [('bridge',study.bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:validation[cid][split]=group(c,split,dates,stress)
        full[cid],curve=study.run(c,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];v=validation[cid];b=validation['BASE'];f=full[cid];fb=full['BASE']
        checks=dict(full_sharpe=f['sharpe']>=1,audit_sharpe=v['audit']['sharpe']>=1,bridge_sharpe=v['bridge']['sharpe']>=1,
            full_risk_return=f['annualized']>=fb['annualized']-.02 and f['drawdown']>=fb['drawdown']-.02,
            audit_risk_return=v['audit']['median']>=b['audit']['median']-.02 and v['audit']['drawdown']>=b['audit']['drawdown']-.02,
            stress=v['stress']['sharpe']>=b['stress']['sharpe']-.02 and v['stress']['median']>=b['stress']['median']-.02)
        goals[cid]=dict(checks=checks,passed=all(checks.values()))
    result=dict(configs=CONFIGS,development=dev,winners=winners,validation=validation,full=full,goals=goals,windows=len(rows),rf=.02,platform_parity=False);save('summary.json',result)
    lines=['# 分批月度调仓Sharpe研究','','实际分配10万元，各子账户单独计手续费和整手限制；不是将满额回测净值无成本平均。','',
        '|编号|每份目标股票数|月内交易日偏移|年化中位数|最差回撤|Sharpe中位数|','|---|---:|---|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%d|%s|%.2f%%|%.2f%%|%.3f|'%(c['id'],c['count'],str(c['offsets']),100*z['median'],-100*z['drawdown'],z['sharpe']))
    lines+=['','|编号|阶段|年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|']
    for cid,parts in validation.items():
        for split,z in parts.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|'%(cid,split,100*z['median'],-100*z['drawdown'],z['sharpe']))
    lines+=['','全期结果：'+json.dumps(full,ensure_ascii=False),'突破目标检查：'+json.dumps(goals,ensure_ascii=False),
        '平台公式，Rf暂按2%；全期2020-01-02至2026-09-11。历史反复使用且窗口重叠，不是独立样本外。未修改正式策略。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(dict(windows=len(rows),full=full,goals=goals)),flush=True)

if __name__=='__main__':main()
