"""Always-invested covariance weights, original selection and turnover buffer."""
import json,itertools
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import monthly_A_invested_sharpe as p
import monthly_A_covweight_engine as e
HERE=p.HERE;OUT=HERE/'monthly_A_covweight_20260925'
CONFIGS=[p.BASE,p.CONTROL]+[dict(id='W%02d'%(i+1),strict=True,exposure=.9,power=.5,kind=kind,window=window,shrink=shrink) for i,(kind,window,shrink) in enumerate(itertools.product(('minvar','riskparity'),(60,120),(.25,.75)))]

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def weights(cov,kind,shrink):
    n=len(cov);a=np.asarray(cov,float);diag=np.diag(a).copy();valid=diag[np.isfinite(diag)&(diag>1e-10)]
    fallback=max(float(valid.max()) if len(valid) else 0.,.0004)
    diag=np.where(np.isfinite(diag)&(diag>1e-10),diag,fallback)
    a=np.nan_to_num(a,nan=0.);np.fill_diagonal(a,diag);a=(a+a.T)/2
    a=(1-shrink)*a+shrink*np.diag(diag)
    values,vectors=np.linalg.eigh(a);a=(vectors*np.maximum(values,1e-10))@vectors.T;a/=np.mean(np.diag(a))
    def objective(w):
        if kind=='minvar':return float(w@a@w)
        rc=w*(a@w);return float(np.sum((rc/rc.sum()-1/n)**2))
    result=minimize(objective,np.ones(n)/n,method='SLSQP',bounds=[(.05,1.5/n)]*n,constraints=[dict(type='eq',fun=lambda w:w.sum()-1)],options=dict(ftol=1e-10,maxiter=200))
    if not result.success or abs(result.x.sum()-1)>1e-6:raise ValueError('Weight optimization failed: '+result.message)
    return result.x

class Study(p.Study):
    def __init__(self):
        p.e=e;p.CONFIGS=CONFIGS;super().__init__()
        names=sorted(set().union(*(set(q.symbol) for q in self.base.ranks['BASE'].values())))
        prices={}
        for sym in names:
            q=pd.read_parquet(e.qfq_path(sym),columns=['date','close']);q['date']=pd.to_datetime(q.date);prices[sym]=q.set_index('date').close.astype(float)
        ret=pd.DataFrame(prices).sort_index().ffill(limit=5).pct_change(fill_method=None);self.cov={};self.weight_cache={}
        for d,q in self.base.ranks['BASE'].items():
            for n in (60,120):
                hist=ret.loc[ret.index<d,list(q.symbol)].tail(n);assert hist.index.max()<d
                self.cov[(d,n)]=hist.cov(min_periods=n//2)

    def run(self,cfg,start,stress=False,full=False):
        if 'kind' in cfg:
            def choose(d,selected):
                key=(cfg['id'],d,tuple(selected))
                if key not in self.weight_cache:self.weight_cache[key]=weights(self.cov[(d,cfg['window'])].loc[selected,selected],cfg['kind'],cfg['shrink'])
                return self.weight_cache[key]
            e.WEIGHTER=choose
        else:e.WEIGHTER=None
        return super().run(cfg,start,stress,full)

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists()
    save('protocol.json',dict(configs=CONFIGS,rf=.02,method='Original stock selection;fully invested target90%;long-only covariance minimum variance or equal risk contributions;60/120 prior returns,25/75%diagonal shrinkage;weights5..25%each;no cash timing;min adjustment3000.',
        selection='Dev top2 Sharpe with annual>=BASE-2pp,P10>=BASE-1pp,DD>=BASE-2pp and exposure gate. Freeze before validation.',
        goal='Full,audit median,bridge median Sharpe>=1;full annual>=BASE-2pp,DD>=BASE-2pp;auditannual>=BASE-2pp,DD>=BASE-2pp;stressSharpe>=BASE-.02 and annual>=BASE-2pp;actual exposure gate every split.',
        exposure_gate='Every window mean exposure>=75%;days below50%<=5%;continuous days below10%<=2.',limitations='Repeated overlapping history,10w capital,approx daily fills/company actions and earlyhistory gaps;not platform parity.'))
    study=Study();rows=[];dev={}
    def group(c,split,dates,stress=False):
        batch=[]
        for start in dates:
            z,_=study.run(c,start,stress);z.update(id=c['id'],split=split);rows.append(z);batch.append(z)
        out=p.summarize_group(batch);save('windows.json',rows);print(split,c['id'],json.dumps(out),flush=True);return out
    for c in CONFIGS:dev[c['id']]=group(c,'dev',study.dev);save('development.json',dev)
    b=dev['BASE'];pool=[c for c in CONFIGS[2:] if p.invested(dev[c['id']]) and dev[c['id']]['median']>=b['median']-.02 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2];save('frozen_winners.json',winners);validation={};full={}
    for c in CONFIGS[:2]+winners:
        cid=c['id'];validation[cid]={}
        for split,dates,stress in [('bridge',study.bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:validation[cid][split]=group(c,split,dates,stress)
        full[cid],curve=study.run(c,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];f=full[cid];fb=full['BASE'];v=validation[cid];b=validation['BASE']
        checks=dict(full_sharpe=f['sharpe']>=1,audit_sharpe=v['audit']['sharpe']>=1,bridge_sharpe=v['bridge']['sharpe']>=1,
            full_risk_return=f['annualized']>=fb['annualized']-.02 and f['drawdown']>=fb['drawdown']-.02,
            audit_risk_return=v['audit']['median']>=b['audit']['median']-.02 and v['audit']['drawdown']>=b['audit']['drawdown']-.02,
            stress=v['stress']['sharpe']>=b['stress']['sharpe']-.02 and v['stress']['median']>=b['stress']['median']-.02,
            invested=all(p.invested(z) for z in [dev[cid]]+list(v.values())) and f['mean_exposure']>=.75 and f['low_exposure_fraction']<=.05 and f['max_flat_streak']<=2)
        goals[cid]=dict(checks=checks,passed=all(checks.values()))
    result=dict(configs=CONFIGS,development=dev,winners=winners,validation=validation,full=full,goals=goals,windows=len(rows),rf=.02,platform_parity=False);save('summary.json',result)
    lines=['# 固定高仓位：协方差权重研究','','目标90%仓位，不设置空仓或冷静期。股票选择不变，仅用历史协方差调整6只股票权重，仍扣实际费用并保留小额调仓过滤。','',
        '|编号|开发年化中位数|最差回撤|Sharpe中位数|最差窗口平均仓位|最长空仓日|','|---|---:|---:|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|'%(c['id'],100*z['median'],-100*z['drawdown'],z['sharpe'],100*z['worst_mean_exposure'],z['max_flat_streak']))
    lines+=['','|编号|全期终值|年化|最大回撤|Sharpe|平均仓位|低于50%天数|空仓天数|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|%d|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe'],100*z['mean_exposure'],z['low_exposure_days'],z['flat_days']))
    lines+=['','验证：'+json.dumps(validation,ensure_ascii=False),'目标检查：'+json.dumps(goals,ensure_ascii=False),
        '10万元，2020-01-02至2026-09-11；平台公式Rf暂按2%。24开发/8中段/24后段起点各24个月；压力佣金、最低费用、滑点翻倍。已见历史且窗口重叠，不是独立样本外，平台分钟成交仍未复现。原策略未覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('DONE',json.dumps(dict(windows=len(rows),full=full,goals=goals)),flush=True)

if __name__=='__main__':main()
