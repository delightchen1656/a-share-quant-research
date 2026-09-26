"""Exploratory aggressive comparator. Never relabel original gate failure as pass."""
import json
import pandas as pd
import monthly_A_return_search as r
import monthly_A_structure_research as s
from supermind_performance import measure
from robust_policy_search import summarize

OUT=r.HERE/'monthly_A_return_frontier_20260925'
def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists()
    parent=json.loads((r.OUT/'summary.json').read_text(encoding='utf-8'))
    aggressive=max(parent['configs'][1:],key=lambda c:parent['development'][c['id']]['median'])
    save('frozen_protocol.json',dict(candidate=aggressive,selection='Highest development median annual among36, deliberately without drawdown gate. Supplement added after observing some development results, not part of original predeclared gate. Freeze before its own validation. NOT a robust upgrade.',rf=.02,limitations='All history already seen, daily execution proxy, incomplete warmup, no platform parity. No automatic promotion.'))
    s.CONFIGS=[r.BASE,aggressive];s.measure=lambda c:measure(c,risk_free_annual=.02)
    study=s.Study();idx=pd.read_parquet(s.e.DATA/'indices/000905.SH.parquet').sort_values('date');idx['date']=pd.to_datetime(idx.date)
    for cfg in s.CONFIGS:
        for d in study.exposures[cfg['id']]:
            h=idx[idx.date<d];strong=h.close.iloc[-1]>h.close.tail(120).mean()
            study.exposures[cfg['id']][d]=cfg['strong'] if strong else cfg['weak']
    bridge=[d for d in sorted(study.ranks['BASE']) if d.year in (2022,2023) and d.month in (1,4,7,10) and d==min(x for x in study.ranks['BASE'] if x.year==d.year and x.month==d.month)]
    validation={};full={};rows=[]
    for cfg in s.CONFIGS:
        cid=cfg['id'];validation[cid]={}
        for split,dates,stress in [('bridge',bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:
            group=[]
            for start in dates:
                stat,_=study.run(cfg,start,stress=stress);stat.update(id=cid,split=split);rows.append(stat);group.append(stat)
            validation[cid][split]=summarize(group);save('windows.json',rows)
            print(cid,split,json.dumps(validation[cid][split]),flush=True)
        full[cid],curve=study.run(cfg,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    result=dict(candidate=aggressive,development=parent['development'][aggressive['id']],validation=validation,full=full,windows=len(rows),robust_upgrade=False,platform_parity=False)
    save('summary.json',result)
    lines=['# 进取对照：收益与回撤的取舍','','本项不是原36组筛选门槛的通过者，而是另取开发期年化最高组合观察风险收益。未经平台验证，不能视作正式升级。','',
        '参数：'+json.dumps(aggressive,ensure_ascii=False),'','|版本|区间|年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|']
    for cid,parts in validation.items():
        for split,z in parts.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|'%(cid,split,100*z['median'],-100*z['drawdown'],z['sharpe']))
    lines+=['','|版本|全期终值|年化|最大回撤|Sharpe|','|---|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe']))
    lines+=['','全期2020-01-02至2026-09-11，初始10万元；统计采用平台公开公式，Rf暂按2%。','bridge：8个2022/2023季度起点；audit：24个2024起点；均24个月；stress为audit佣金、最低佣金、滑点翻倍，印花税不变。',
        '历史反复使用、窗口重叠、早期历史和分钟撮合仍有误差。只展示明确风险收益交换，原基准不覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(result),flush=True)

if __name__=='__main__':main()
