"""Stay-invested low-correlation selection. No market timing or NAV cash pause."""
import json,itertools,hashlib
import numpy as np
import pandas as pd
import monthly_A_structure_research as s
import monthly_A_invested_engine as e
from supermind_performance import measure
from robust_policy_search import summarize
HERE=s.HERE;OUT=HERE/'monthly_A_invested_20260925'
BASE=dict(id='BASE',strict=False,exposure=.8,power=.5)
CONTROL=dict(id='C90',strict=True,exposure=.9,power=.5)
CONFIGS=[BASE,CONTROL]+[dict(id='I%02d'%(i+1),strict=True,exposure=.9,power=power,lookback=lookback,penalty=penalty,retention=retention)
    for i,(lookback,penalty,retention,power) in enumerate(itertools.product((60,120),(.25,.5,1.),(.10,.25),(.0,.5)))]

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def longest(mask):
    best=run=0
    for value in mask:
        run=run+1 if value else 0;best=max(best,run)
    return best

def select_diversified(ranked,held,count,correlation,penalty,retention):
    symbols=list(ranked.symbol);n=len(symbols);alpha={v:1-i/max(1,n-1) for i,v in enumerate(symbols)}
    selected=[]
    while len(selected)<min(count,n):
        def score(symbol):
            crowd=np.mean([max(0.,float(correlation.loc[symbol,t])) for t in selected]) if selected else 0.
            return alpha[symbol]+retention*(symbol in held)-penalty*crowd
        choices=[v for v in symbols if v not in selected]
        selected.append(max(choices,key=lambda v:(score(v),-symbols.index(v))))
    return selected

def exposure_stats(curve):
    ratio=(curve.stock_value/curve.equity).clip(0,1)
    return dict(mean_exposure=float(ratio.mean()),p10_exposure=float(ratio.quantile(.1)),low_exposure_days=int((ratio<.5).sum()),
        low_exposure_fraction=float((ratio<.5).mean()),flat_days=int((ratio<.1).sum()),max_flat_streak=longest(ratio<.1))

def summarize_group(rows):
    return dict(**summarize(rows),mean_exposure=float(np.mean([z['mean_exposure'] for z in rows])),
        worst_mean_exposure=min(z['mean_exposure'] for z in rows),worst_low_fraction=max(z['low_exposure_fraction'] for z in rows),
        max_flat_streak=max(z['max_flat_streak'] for z in rows),flat_days_total=sum(z['flat_days'] for z in rows))

def invested(z):return z['worst_mean_exposure']>=.75 and z['worst_low_fraction']<=.05 and z['max_flat_streak']<=2

class Study:
    def __init__(self):
        s.e=e;s.CONFIGS=CONFIGS;s.measure=lambda c:measure(c,risk_free_annual=.02)
        self.base=s.Study();self.dev=self.base.dev;self.audit=self.base.audit
        dates=sorted(self.base.ranks['BASE']);self.bridge=[d for d in dates if d.year in (2022,2023) and d.month in (1,4,7,10) and d==min(x for x in dates if (x.year,x.month)==(d.year,d.month))]
        for cfg in CONFIGS:
            for d in self.base.exposures[cfg['id']]:self.base.exposures[cfg['id']][d]=cfg['exposure']
        symbols=sorted(set().union(*(set(q.symbol) for q in self.base.ranks['BASE'].values())))
        closes={}
        for sym in symbols:
            q=pd.read_parquet(e.qfq_path(sym),columns=['date','close']);q['date']=pd.to_datetime(q.date)
            assert not q.date.duplicated().any();closes[sym]=q.set_index('date').close.astype(float)
        prices=pd.DataFrame(closes).sort_index().ffill(limit=5);returns=prices.pct_change(fill_method=None)
        self.correlations={}
        for d in dates:
            names=list(self.base.ranks['BASE'][d].symbol)
            for window in (60,120):
                hist=returns.loc[returns.index<d,names].tail(window)
                assert hist.index.max()<d
                corr=hist.corr(min_periods=window//2).reindex(index=names,columns=names).fillna(1.).clip(-1,1)
                self.correlations[(d,window)]=corr

    def run(self,cfg,start,stress=False,full=False):
        if 'penalty' in cfg:
            e.SELECTOR=lambda d,q,held,count,buffer:select_diversified(q,held,count,self.correlations[(d,cfg['lookback'])],cfg['penalty'],cfg['retention'])
        else:e.SELECTOR=None
        stats,curve=self.base.run(cfg,start,stress=stress,full=full)
        assert (curve.stock_value>=-.01).all()
        stats.update(exposure_stats(curve));return stats,curve

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists();assert len(CONFIGS)==26
    save('protocol.json',dict(configs=CONFIGS,rf=.02,selection='Develop top2 medianSharpe with annual>=BASE-2pp,P10>=BASE-1pp,DD>=BASE-2pp and exposure gate. Freeze before validation.',
        exposure_gate='Every tested window mean stock exposure>=75%,fraction days below50%<=5%,maximum continuous below10%<=2 sessions. Candidates fixed90%target, no regime cash or NAV pauses.',
        validation='FullSharpe>=1,audit/bridge medianSharpe>=1;full annual>=BASE-2pp,fullDD>=BASE-2pp;audit annual>=BASE-2pp,P10>=BASE-1pp,DD>=BASE-2pp;stressSharpe>=BASE-.02 and annual>=BASE-2pp;exposure gate on all splits.',
        method='Among original top24,greedy rank-position alpha +held bonus -mean positive trailing correlation penalty;fixed6targets,inverse-downside power0/.5;60/120 prior-sessionreturns. Missing correlations conservatively1,priceforwardfill capped5 sessions.',
        caveats='Already-seen overlapping24dev/8bridge/24audit windows;localdailyproxy,earlyhistorygaps,approxactiondates;platformparity not established. IncludesC90 same exposure control;no leverage or funding assumptions.'))
    paths=[HERE/'monthly_A_invested_sharpe.py',HERE/'monthly_A_invested_engine.py',HERE/'supermind_performance.py',HERE/'cadence_multiround_100k/exact_date_factors.parquet',s.ALIGN/'action_ledger/manifest.json']
    save('inputs.json',[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
    study=Study();rows=[];dev={}
    def group(cfg,split,dates,stress=False):
        batch=[]
        for start in dates:
            z,_=study.run(cfg,start,stress);z.update(id=cfg['id'],split=split);rows.append(z);batch.append(z)
        result=summarize_group(batch);save('windows.json',rows);print(split,cfg['id'],json.dumps(result),flush=True);return result
    for cfg in CONFIGS:dev[cfg['id']]=group(cfg,'dev',study.dev);save('development.json',dev)
    b=dev['BASE'];pool=[c for c in CONFIGS[2:] if invested(dev[c['id']]) and dev[c['id']]['median']>=b['median']-.02 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2];save('frozen_winners.json',winners)
    validation={};full={}
    for c in [BASE,CONTROL]+winners:
        cid=c['id'];validation[cid]={}
        for split,dates,stress in [('bridge',study.bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:validation[cid][split]=group(c,split,dates,stress);save('validation.json',validation)
        full[cid],curve=study.run(c,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];f=full[cid];fb=full['BASE'];v=validation[cid];b=validation['BASE']
        checks=dict(full_sharpe=f['sharpe']>=1,audit_sharpe=v['audit']['sharpe']>=1,bridge_sharpe=v['bridge']['sharpe']>=1,
            full_risk_return=f['annualized']>=fb['annualized']-.02 and f['drawdown']>=fb['drawdown']-.02,
            audit_risk_return=v['audit']['median']>=b['audit']['median']-.02 and v['audit']['p10']>=b['audit']['p10']-.01 and v['audit']['drawdown']>=b['audit']['drawdown']-.02,
            stress=v['stress']['sharpe']>=b['stress']['sharpe']-.02 and v['stress']['median']>=b['stress']['median']-.02,
            invested=all(invested(z) for z in [dev[cid]]+list(v.values())) and f['mean_exposure']>=.75 and f['low_exposure_fraction']<=.05 and f['max_flat_streak']<=2)
        goals[cid]=dict(checks=checks,passed=all(checks.values()))
    result=dict(configs=CONFIGS,development=dev,winners=winners,validation=validation,full=full,goals=goals,windows=len(rows),rf=.02,platform_parity=False);save('summary.json',result)
    lines=['# 不长期空仓：低相关组合研究','','候选目标仓位固定90%，无空仓择时或净值冷静期。所有组合均实际计费用、最低佣金和整手限制。','',
        '|编号|开发年化中位数|最差回撤|Sharpe中位数|最差窗口平均仓位|最长空仓交易日|','|---|---:|---:|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|'%(c['id'],100*z['median'],-100*z['drawdown'],z['sharpe'],100*z['worst_mean_exposure'],z['max_flat_streak']))
    lines+=['','|编号|验证段|年化中位数|最差回撤|Sharpe中位数|最差平均仓位|最长空仓日|','|---|---|---:|---:|---:|---:|---:|']
    for cid,parts in validation.items():
        for split,z in parts.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|'%(cid,split,100*z['median'],-100*z['drawdown'],z['sharpe'],100*z['worst_mean_exposure'],z['max_flat_streak']))
    lines+=['','|编号|全期终值|年化|最大回撤|Sharpe|平均仓位|低于50%天数|低于10%天数|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|%d|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe'],100*z['mean_exposure'],z['low_exposure_days'],z['flat_days']))
    lines+=['','目标检查：'+json.dumps(goals,ensure_ascii=False),'窗口数：'+str(len(rows)),
        '平台公式、Rf暂按2%；全期2020-01-02至2026-09-11，初始10万元。开发24个2020/21起点、bridge8个2022/23起点、audit24个2024起点，各24个月。压力佣金/最低佣金/滑点翻倍，税不变。',
        '实际股票仓位用股票市值/总资产，扣除现金和应收分红，不是用目标仓位冒充。空仓诊断采用低于10%，低仓位采用低于50%。控制BASE80%和C90保留原选股机制；其约束结果也如实列出。',
        '历史多次使用且窗口重叠；不是独立样本外。日线成交代理、早期历史和部分公司行动日期仍有近似，未覆盖正式平台策略。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('DONE',json.dumps(dict(windows=len(rows),full=full,goals=goals)),flush=True)

if __name__=='__main__':main()
