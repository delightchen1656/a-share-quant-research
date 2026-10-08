"""Six fixed drawdown-pause rules; prior NAV only, ordinary execution costs."""
import json,itertools
import monthly_A_structure_research as s
import monthly_A_guard_engine as e
from supermind_performance import measure
from robust_policy_search import summarize
HERE=s.HERE;OUT=HERE/'monthly_A_guard_sharpe_20260925'
BASE=dict(id='BASE',strict=False)
CONFIGS=[BASE]+[dict(id='D%d'%(i+1),strict=True,guard=[d,n]) for i,(d,n) in enumerate(itertools.product((.06,.10,.14),(10,20)))]
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists()
    save('protocol.json',dict(configs=CONFIGS,rf=.02,selection='Freeze top2 devSharpe with annual>=BASE-2pp,P10>=BASE-1pp,DD>=BASE-2pp. Prior NAV drawdown6/10/14%,cooldown10/20trading sessions;no leverage;strict6targets;cash earns0.',
        goal='Full and audit median Sharpe>=1;annual>=BASE-2pp,DD>=BASE-2pp;stressSharpe>=BASE-.02,annual>=BASE-2pp.',
        caveats='Explicit additional branch after prior failures;history repeatedly seen and windows overlapping;daily execution and action approximations;not platform parity. Sell next open subject to limits;retry while paused;resume only on scheduled monthly date.'))
    s.e=e;s.CONFIGS=CONFIGS;s.measure=lambda c:measure(c,risk_free_annual=.02)
    study=s.Study();rows=[];dev={}
    def run(c,start,stress=False,full=False):
        e.NAV_GUARD=c.get('guard');e.GUARD_LOG=[]
        z,curve=study.run(c,start,stress=stress,full=full);z['guard_triggers']=len(e.GUARD_LOG)
        return z,curve
    def group(c,split,dates,stress=False):
        batch=[]
        for start in dates:
            z,_=run(c,start,stress);z.update(id=c['id'],split=split);batch.append(z);rows.append(z)
        result=summarize(batch);save('windows.json',rows);print(split,c['id'],json.dumps(result),flush=True);return result
    for c in CONFIGS:dev[c['id']]=group(c,'dev',study.dev);save('development.json',dev)
    b=dev['BASE'];pool=[c for c in CONFIGS[1:] if dev[c['id']]['median']>=b['median']-.02 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2];save('frozen_winners.json',winners)
    validation={};full={}
    for c in [BASE]+winners:
        cid=c['id'];validation[cid]={}
        for split,stress in [('audit',False),('stress',True)]:validation[cid][split]=group(c,split,study.audit,stress)
        full[cid],curve=run(c,study.dev[0],full=True);save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];f=full[cid];fb=full['BASE'];v=validation[cid];b=validation['BASE']
        checks=dict(full_sharpe=f['sharpe']>=1,audit_sharpe=v['audit']['sharpe']>=1,
            return_floor=f['annualized']>=fb['annualized']-.02 and v['audit']['median']>=b['audit']['median']-.02,
            drawdown=f['drawdown']>=fb['drawdown']-.02 and v['audit']['drawdown']>=b['audit']['drawdown']-.02,
            stress=v['stress']['sharpe']>=b['stress']['sharpe']-.02 and v['stress']['median']>=b['stress']['median']-.02)
        goals[cid]=dict(checks=checks,passed=all(checks.values()))
    result=dict(configs=CONFIGS,development=dev,validation=validation,full=full,winners=winners,goals=goals,windows=len(rows),rf=.02,platform_parity=False);save('summary.json',result)
    lines=['# 净值回撤冷静期研究','','仅使用前一交易日净值触发，下个交易日尝试退出；停牌/跌停等约束仍适用。冷静期后等月度调仓恢复，不自动在冷静期结束当日追买。','',
        '|版本|规则|开发年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|'%(c['id'],str(c.get('guard','无')),z['median']*100,-z['drawdown']*100,z['sharpe']))
    lines+=['','验证：'+json.dumps(validation,ensure_ascii=False),'全期：'+json.dumps(full,ensure_ascii=False),'目标检查：'+json.dumps(goals,ensure_ascii=False),
        '10万元，平台公式Rf暂按2%；全期2020-01-02至2026-09-11；24开发和24验证起点各24个月，压力佣金/最低费用/滑点翻倍。已使用历史不是独立样本外，分钟撮合和历史覆盖误差仍存在。原策略未覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(dict(windows=len(rows),full=full,goals=goals)),flush=True)

if __name__=='__main__':main()
