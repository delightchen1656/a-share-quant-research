"""Return-oriented, regime-dependent exposure. Platform formulas, explicit RF=2%."""
import json,itertools,hashlib
import pandas as pd
import monthly_A_structure_research as s
from supermind_performance import measure
from robust_policy_search import summarize

HERE=s.HERE;OUT=HERE/'monthly_A_return_search_20260925'
BASE=dict(id='BASE',name='原月初A',strict=False,power=.5,buffer=24,strong=.8,weak=.8)
CONFIGS=[BASE]+[dict(id='G%02d'%(i+1),strict=True,power=p,buffer=b,strong=a,weak=w)
    for i,(a,w,p,b) in enumerate(itertools.product((.8,.9,1.),(.5,.65,.8),(0.,.25),(16,24)))]

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def eligible(a,b):
    return a['median']>=b['median']+.005 and a['sharpe']>=b['sharpe']-.02 and a['p10']>=b['p10']-.01 and a['drawdown']>=b['drawdown']-.02

def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'summary.json').exists(),'Preserve completed study'
    assert len(CONFIGS)==37
    save('protocol.json',dict(configs=CONFIGS,rf=.02,metrics='SuperMind documented250-day geometric annualization;population volatility;Sharpe=(annual-.02)/vol. RF is approximate, not claimed vendor-exact.',
        windows='24 development starts2020/21;8 bridge quarter starts2022/23;24 audit starts2024;each24months; overlapping previously-seen history.',
        selection='Dev only. Annual median gain>=.5pp;Sharpe>=base-.02;P10>=base-1pp;worstDD>=base-2pp. Freeze highest annual candidate and highest Sharpe distinct candidate.',
        validation='Audit annual>=base+.2pp,Sharpe>=base-.02,P10>=base-1pp,DD>=base-2pp;bridge annual>=base-1pp,Sharpe>=base-.05;double-cost audit annual>=base,Sharpe>=base-.02,P10>=base-1pp,DD>=base-2pp. Opposite-power dev neighbor annual>=base-1pp,Sharpe>=base-.05,DD>=base-2.5pp.',
        limits='10w,monthly,6targets,no leverage,fees/lot/cash checks inherited;daily price/volume proxy,pre2018 gaps,approx action dates;platform parity remains unproven. Original strategy untouched.'))
    paths=[HERE/'monthly_A_structure_research.py',HERE/'monthly_A_structure_engine.py',HERE/'supermind_performance.py',HERE/'monthly_A_return_search.py',HERE/'cadence_multiround_100k/exact_date_factors.parquet',s.ALIGN/'action_ledger/manifest.json']
    save('inputs.json',[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths])
    s.CONFIGS=CONFIGS;s.measure=lambda c:measure(c,risk_free_annual=.02)
    study=s.Study()
    idx=pd.read_parquet(s.e.DATA/'indices/000905.SH.parquet').sort_values('date');idx['date']=pd.to_datetime(idx.date)
    for cfg in CONFIGS:
        for d in study.exposures[cfg['id']]:
            h=idx[idx.date<d];assert len(h)>=120
            strong=h.close.iloc[-1]>h.close.tail(120).mean()
            study.exposures[cfg['id']][d]=cfg['strong'] if strong else cfg['weak']
    bridge=[d for d in sorted(study.ranks['BASE']) if d.year in (2022,2023) and d.month in (1,4,7,10) and d==min(x for x in study.ranks['BASE'] if x.year==d.year and x.month==d.month)]
    assert len(bridge)==8
    rows=[];development={}
    def run_group(cfg,split,starts,stress=False):
        group=[]
        for start in starts:
            z,_=study.run(cfg,start,stress=stress)
            z.update(id=cfg['id'],split=split,sharpe_rf15=(z['annualized']-.015)/z['volatility'],sharpe_rf25=(z['annualized']-.025)/z['volatility'])
            rows.append(z);group.append(z)
        out=summarize(group);save('windows.json',rows)
        print(split,cfg['id'],json.dumps(out),flush=True)
        return out
    for cfg in CONFIGS:
        development[cfg['id']]=run_group(cfg,'dev',study.dev);save('development.json',development)
    b=development['BASE'];pool=[c for c in CONFIGS[1:] if eligible(development[c['id']],b)]
    winners=[]
    if pool:
        winners.append(max(pool,key=lambda c:development[c['id']]['median']))
        remaining=[c for c in pool if c['id']!=winners[0]['id']]
        if remaining:winners.append(max(remaining,key=lambda c:development[c['id']]['sharpe']))
    save('frozen_winners.json',winners)
    validation={};full={}
    for cfg in [BASE]+winners:
        cid=cfg['id'];validation[cid]={}
        for split,starts,stress in [('bridge',bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:
            validation[cid][split]=run_group(cfg,split,starts,stress);save('validation.json',validation)
        full[cid],curve=study.run(cfg,study.dev[0],full=True)
        save(cid+'_full_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    previous=json.loads((HERE/'monthly_A_structure_20260925/summary.json').read_text(encoding='utf-8'))['full']['B00']
    assert abs(full['BASE']['final_equity']-previous['final_equity'])<1e-7
    passed={};neighbors={}
    for c in winners:
        cid=c['id'];v=validation[cid];base=validation['BASE'];a=v['audit'];b=base['audit'];x=v['stress'];y=base['stress']
        n=next(q for q in CONFIGS[1:] if all(q[k]==c[k] for k in ('strong','weak','buffer')) and q['power']!=c['power']);neighbors[cid]=n['id'];z=development[n['id']];d=development['BASE']
        tests=dict(audit=a['median']>=b['median']+.002 and a['sharpe']>=b['sharpe']-.02 and a['p10']>=b['p10']-.01 and a['drawdown']>=b['drawdown']-.02,
            bridge=v['bridge']['median']>=base['bridge']['median']-.01 and v['bridge']['sharpe']>=base['bridge']['sharpe']-.05,
            stress=x['median']>=y['median'] and x['sharpe']>=y['sharpe']-.02 and x['p10']>=y['p10']-.01 and x['drawdown']>=y['drawdown']-.02,
            neighbor=z['median']>=d['median']-.01 and z['sharpe']>=d['sharpe']-.05 and z['drawdown']>=d['drawdown']-.025)
        passed[cid]=dict(checks=tests,passed=all(tests.values()))
    result=dict(configs=CONFIGS,development=development,winners=winners,validation=validation,full=full,passed=passed,neighbors=neighbors,windows=len(rows),full_runs=len(full),platform_parity=False,rf=.02)
    save('summary.json',result)
    lines=['# 月初A收益优化：36组强弱市仓位组合','','统计使用平台公开公式，Rf暂按2%。此为近似本地研究，不是平台复现或独立样本外证明。','',
        '|编号|强市仓位|弱市仓位|风险权重指数|保留范围|开发年化中位数|最差回撤|Sharpe中位数|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for c in CONFIGS:
        z=development[c['id']];lines.append('|%s|%.0f%%|%.0f%%|%.2f|%d|%.2f%%|%.2f%%|%.3f|'%(c['id'],c['strong']*100,c['weak']*100,c['power'],c['buffer'],z['median']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','|编号|验证段|年化中位数|P10|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|---:|']
    for cid,parts in validation.items():
        for split,z in parts.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(cid,split,z['median']*100,z['p10']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','|编号|全期终值|年化|最大回撤|Sharpe|','|---|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(cid,z['final_equity'],z['annualized']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','通过情况：'+json.dumps(passed,ensure_ascii=False),'全期2020-01-02至2026-09-11，初始10万元。窗口总数：'+str(len(rows)),
        '开发24个2020/2021年入场窗口；bridge为8个2022/2023年季度首日起点；audit为24个2024年起点；各持有24个月。stress为audit佣金、最低佣金和滑点翻倍，印花税不变。',
        '所有窗口均来自已反复研究的历史，且相互重叠。强弱市判断只使用调仓前一日数据，并仅在月度调仓时改变目标仓位。严格6只是目标数；停牌、跌停等可能使旧持仓未能退出，实际持仓不保证始终不超6只。',
        '源码和数据校验值见inputs.json；正式策略未覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(dict(windows=len(rows),passed=passed,full=full)),flush=True)

if __name__=='__main__':main()
