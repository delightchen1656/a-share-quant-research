"""Sharpe-first48-way research with fixed approximate platform metrics/RF."""
import json,itertools,hashlib
import numpy as np
import pandas as pd
import monthly_A_structure_research as s
from supermind_performance import measure
from robust_policy_search import summarize

e=s.e;HERE=s.HERE;OUT=HERE/'monthly_A_sharpe_20260925'
BASE=dict(id='BASE',style='base',count=6,power=.5,strong=.8,weak=.8,strict=False)
CONFIGS=[BASE]+[dict(id='H%02d'%(i+1),style=style,count=count,power=power,strong=a,weak=b,strict=True)
    for i,(style,count,power,(a,b)) in enumerate(itertools.product(('base','quality','balanced'),(6,10),(.5,1.),((.5,.8),(.65,.8),(.8,.8),(.8,.5))))]

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class Study:
    def __init__(self):
        s.CONFIGS=[BASE];template=s.Study()
        self.cal=template.cal;self.dev=template.dev;self.audit=template.audit;self.initial=template.initial
        dates=set(template.ranks['BASE'])
        self.bridge=[d for d in sorted(dates) if d.year in (2022,2023) and d.month in (1,4,7,10) and d==min(x for x in dates if (x.year,x.month)==(d.year,d.month))]
        assert len(self.bridge)==8
        f=pd.read_parquet(HERE/'cadence_multiround_100k/exact_date_factors.parquet')
        idx=pd.read_parquet(e.DATA/'indices/000905.SH.parquet').sort_values('date');idx['date']=pd.to_datetime(idx.date)
        self.ranks={x:{} for x in ('base','quality','balanced')};self.strong={};symbols=set()
        for d,q in f[f.execute_date.isin(dates)].groupby('execute_date'):
            assert q.signal_date.max()<d
            hist=idx[idx.date<=q.signal_date.iloc[0]];strong=hist.close.iloc[-1]>hist.close.tail(120).mean();self.strong[d]=bool(strong)
            for style in self.ranks:
                x=q.sort_values('symbol').copy()
                if not strong or style=='quality':x=x[x.float_cap_proxy_group==1].copy()
                hi=lambda col:x[col].rank(pct=True)
                if not strong or style=='quality':x['score']=.55*hi('dividend')+.30*(1-hi('downside'))+.15*(1-hi('turn20'))
                elif style=='balanced':x['score']=.40*hi('dividend')+.30*(1-hi('downside'))+.15*hi('near_high')+.15*(1-hi('turn20'))
                else:x['score']=.25*e.rank01(x.amount20.to_numpy(),True)+.20*e.rank01(x.near_high.to_numpy())+.55*e.rank01(x.dividend.to_numpy())
                ranked=x.dropna(subset=['score']).sort_values(['score','symbol'],ascending=[False,True]).head(24)
                assert len(ranked)>=10
                self.ranks[style][d]=ranked[['symbol','downside']].copy();symbols.update(ranked.symbol)
        self.panel=e.load_daily_panel(symbols);e.PREPARED={pd.Timestamp(d):q.set_index('symbol') for d,q in self.panel.groupby('date')}

    def run(self,cfg,start,stress=False,full=False):
        end=pd.Timestamp('2026-09-11') if full else start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True;e.STRICT_TARGET=cfg['strict']
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.initial]
        dates={start}
        for due in pd.date_range(start.replace(day=1),end,freq='MS'):
            d=self.cal[self.cal.searchsorted(due)]
            if start<d<=end:dates.add(d)
        ranks={};exposures={}
        for d in sorted(dates):
            q=self.ranks[cfg['style']][d].copy();q['downside']=q.downside.pow(cfg['power']);ranks[d]=q
            exposures[d]=cfg['strong'] if self.strong[d] else cfg['weak']
        curve,trades=e.simulate(ranks,.05,cfg['count'],24,exposures,1.5,self.panel,min_adjustment=3000)
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        if cfg['strict']:assert all(len(t['selected'])<=cfg['count'] for t in e.SELECTION_TRACE)
        z=measure(curve,risk_free_annual=.02)
        return dict(**z,start=str(start.date()),end=str(curve.date.iloc[-1].date()),fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS)),curve

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists();assert len(CONFIGS)==49
    save('protocol.json',dict(configs=CONFIGS,rf=.02,objective='Sharpe-first. Freeze top2 DEV Sharpe with median annual>=BASE-2pp,P10>=BASE-1pp,worstDD>=BASE-2pp; do not require DEV1.0 to test near misses. No audit reselection.',
        goal='Full-period Sharpe>=1 AND audit-median Sharpe>=1 AND bridge-median Sharpe>=1; full annual>=BASE-2pp and fullDD>=BASE-2pp; audit annual>=BASE-2pp,P10>=BASE-1pp,DD>=BASE-2pp; stressSharpe>=BASE-.02 and annual>=BASE-2pp; opposite-power dev neighbor Sharpe>=BASE-.02 and annual>=BASE-2pp.',
        metrics='250day geometric annual/population volatility;Rf=2%fixed, not vendor-exact. No RF/metric manipulation to cross1.',
        data='Same already-seen overlapping24dev+8bridge+24audit windows,24months each. Approx daily fills/actions, early history gaps;no platform parity. Strong/weak allocation only on monthly rebalance. Original platform script untouched.'))
    paths=[HERE/'monthly_A_sharpe_search.py',HERE/'monthly_A_structure_engine.py',HERE/'supermind_performance.py',HERE/'cadence_multiround_100k/exact_date_factors.parquet',s.ALIGN/'action_ledger/manifest.json']
    save('inputs.json',[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
    study=Study();rows=[];dev={}
    def group(cfg,split,starts,stress=False):
        batch=[]
        for start in starts:
            z,_=study.run(cfg,start,stress=stress);z.update(id=cfg['id'],split=split);rows.append(z);batch.append(z)
        result=summarize(batch);save('windows.json',rows);print(split,cfg['id'],json.dumps(result),flush=True);return result
    for cfg in CONFIGS:
        dev[cfg['id']]=group(cfg,'dev',study.dev);save('development.json',dev)
    b=dev['BASE'];pool=[c for c in CONFIGS[1:] if dev[c['id']]['median']>=b['median']-.02 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2];save('frozen_winners.json',winners)
    validation={};full={}
    for cfg in [BASE]+winners:
        cid=cfg['id'];validation[cid]={}
        for split,dates,stress in [('bridge',study.bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:
            validation[cid][split]=group(cfg,split,dates,stress);save('validation.json',validation)
        full[cid],curve=study.run(cfg,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];v=validation[cid];b=validation['BASE'];f=full[cid];fb=full['BASE']
        neighbor=next(q for q in CONFIGS[1:] if all(q[k]==c[k] for k in ('style','count','strong','weak')) and q['power']!=c['power']);n=dev[neighbor['id']];d=dev['BASE']
        checks=dict(sharpe_full=f['sharpe']>=1,sharpe_audit=v['audit']['sharpe']>=1,sharpe_bridge=v['bridge']['sharpe']>=1,
            full_risk_return=f['annualized']>=fb['annualized']-.02 and f['drawdown']>=fb['drawdown']-.02,
            audit_risk_return=v['audit']['median']>=b['audit']['median']-.02 and v['audit']['p10']>=b['audit']['p10']-.01 and v['audit']['drawdown']>=b['audit']['drawdown']-.02,
            stress=v['stress']['sharpe']>=b['stress']['sharpe']-.02 and v['stress']['median']>=b['stress']['median']-.02,
            neighbor=n['sharpe']>=d['sharpe']-.02 and n['median']>=d['median']-.02)
        goals[cid]=dict(neighbor=neighbor['id'],checks=checks,passed=all(checks.values()))
    summary=dict(configs=CONFIGS,development=dev,winners=winners,validation=validation,full=full,goals=goals,windows=len(rows),platform_parity=False,rf=.02)
    save('summary.json',summary)
    lines=['# Sharpe突破1研究：48组','','平台公开统计公式，Rf暂按2%，不是平台端实测。基准和候选全部同口径。','',
        '|编号|选股风格|目标只数|风险指数|强市仓位|弱市仓位|开发年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%s|%d|%.1f|%.0f%%|%.0f%%|%.2f%%|%.2f%%|%.3f|'%(c['id'],c['style'],c['count'],c['power'],c['strong']*100,c['weak']*100,z['median']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','|编号|阶段|年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|']
    for cid,parts in validation.items():
        for split,z in parts.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|'%(cid,split,z['median']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','|编号|全期终值|年化|最大回撤|Sharpe|','|---|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(cid,z['final_equity'],z['annualized']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','突破1及约束检查：'+json.dumps(goals,ensure_ascii=False),'窗口数：'+str(len(rows)),
        '全期2020-01-02至2026-09-11，10万元；dev24个2020/21起点、bridge8个2022/23季度起点、audit24个2024起点，各24个月。stress为audit佣金/最低佣金/滑点翻倍，税不变。',
        'quality：所有市场状态均在中市值组按分红/下行风险/换手排序。balanced：强市采用分红40%、低下行风险30%、近高点15%、低换手15%，弱市原规则。base：原选股规则。',
        '已反复使用的历史及重叠窗口不是独立样本外。完整早期历史、分钟成交、部分公司行动日期仍有近似。正式平台策略不覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(dict(windows=len(rows),full=full,goals=goals)),flush=True)

if __name__=='__main__':main()
