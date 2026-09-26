"""Frozen-candidate, multi-start validation. Does not reselect on validation."""
import json
import pandas as pd
import research as r

def gates(full,long,rolling,stress,neighbors):
    a=r.summarize(long);b=r.summarize(rolling);c=r.summarize(stress)
    cohorts={year:r.summarize([z for z in long if z['start'].startswith(str(year))]) for year in range(2020,2025)}
    checks=dict(full=full['sharpe']>1 and full['annualized']>.12 and full['mean_exposure']>.5,
        multiple_start=a['joint_pass_fraction']>=.75 and a['min_exposure']>.5,
        entry_years=all(x['sharpe_median']>1 and x['annual_median']>.12 for x in cohorts.values()),
        rolling=b['sharpe_median']>1 and b['annual_median']>.12 and b['positive_fraction']>=.8 and b['min_exposure']>.5,
        not_cash_timing=max(a['max_flat_streak'],b['max_flat_streak'],full['flat_streak'])<=5,
        stress=c['annual_median']>.10 and c['sharpe_median']>.8 and c['min_exposure']>.5 and c['max_flat_streak']<=5,
        neighbors=all(x['positive_fraction']>=.75 and x['annual_median']>0 and x['min_exposure']>.5 and x['max_flat_streak']<=5 for x in neighbors.values()),
        corporate_actions=all(x['unresolved_actions']==0 for x in [full]+long+rolling+stress))
    return dict(checks=checks,passed=all(checks.values()),long=a,rolling=b,stress=c,entry_years=cohorts)

def main(round_name='round01_historical'):
    out=r.HERE/round_name
    assert not (out/'validation_summary.json').exists(),'Preserve completed validation'
    source=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    if 'feature_path' in source:r.FEATURES=r.Path(source['feature_path'])
    if round_name=='round22_staggered':
        import round22_staggered
        round22_staggered.install()
    if round_name=='round21_breadth_retention':
        import round21_breadth_retention
        round21_breadth_retention.install()
    if round_name=='round20_style_risk':
        import round20_style_risk
        round20_style_risk.install()
    if round_name=='round19_daily_risk':
        import round19_daily_risk
        round19_daily_risk.install()
    if round_name=='round18_earnings_value':
        import round18_earnings_value
        round18_earnings_value.install()
    if round_name=='round17_broad_quality':
        import round17_broad_quality
        round17_broad_quality.install()
    if round_name=='round16_financial_quality':
        import round16_financial_quality
        round16_financial_quality.install()
    if round_name=='round15_historical_dividend':
        import round15_historical_dividend
        round15_historical_dividend.install()
    if round_name=='round14_style_adaptation':
        import round14_style_adaptation
        round14_style_adaptation.install()
    if round_name=='round13_liquidity_universe':
        import round13_liquidity_universe
        round13_liquidity_universe.install()
    if round_name=='round12_core_neighborhood':
        import round12_core_neighborhood
        round12_core_neighborhood.install()
    if round_name=='round11_high_floor':
        import round11_high_floor
        round11_high_floor.install()
    if round_name=='round10_cluster_rotation':
        import round10_cluster_rotation
        round10_cluster_rotation.install()
    if round_name=='round09_affordability':
        import round09_affordability
        round09_affordability.install()
    if round_name=='round08_long_momentum':
        import round08_long_momentum
        round08_long_momentum.install()
    if round_name=='round07_diversification':
        import round07_diversification
        round07_diversification.install()
    if round_name=='round06_learning':
        import round06_learning
        round06_learning.install()
    if round_name in ('round04_adjustment','round05_adjustment_weights'):
        import round04
        round04.install()
    if round_name=='round03_calendar_regime':
        import round03
        original_study=r.Study
        def construct_calendar_study(configs):
            r.Study=original_study
            try:return round03.Study()
            finally:r.Study=construct_calendar_study
        r.Study=construct_calendar_study
    winners=source['winners'];assert winners,'No frozen candidates to validate'
    configs=list(winners);near={}
    for cfg in winners:
        near[cfg['id']]=[]
        perturb=[('count',cfg['count']-2),('count',cfg['count']+2)]
        perturb += [('buffer',cfg['buffer']-4),('buffer',cfg['buffer']+4)] if 'cadence' in cfg else [('interval',cfg['interval']-5),('interval',cfg['interval']+5)]
        for key,value in perturb:
            c=dict(cfg,**{key:value});c['id']=cfg['id']+'_'+key+str(value)
            near[cfg['id']].append(c);configs.append(c)
    r.save(out/'validation_protocol.json',dict(frozen=winners,neighbors=near,selection='No validation reselection; all frozen candidates reported',protocol=(r.HERE/'PROTOCOL.md').read_text(encoding='utf-8')))
    study=r.Study(configs)
    longs=[]
    for year in range(2020,2025):
        for month in (1,4,7,10):
            pos=study.cal.searchsorted(pd.Timestamp(year=year,month=month,day=1))
            longs.extend(study.cal[pos+k] for k in (0,5,10,15))
    rolling=[d for d in longs if d.year>=2022 and d+pd.DateOffset(months=24)-pd.Timedelta(days=1)<=r.END]
    rows=[];results={}
    def batch(cfg,split,starts,stress=False,common_end=False):
        found=[]
        for start in starts:
            z,_,_=study.run(cfg,start,end=r.END if common_end else None,stress=stress)
            z.update(id=cfg['id'],split=split);found.append(z);rows.append(z)
        r.save(out/'validation_windows.json',rows)
        print('VALIDATE',cfg['id'],split,json.dumps(r.summarize(found)),flush=True)
        return found
    for cfg in winners:
        a=batch(cfg,'common_end',longs,common_end=True)
        b=batch(cfg,'rolling24',rolling)
        c=batch(cfg,'stress24',rolling,stress=True)
        neighbor={}
        for n in near[cfg['id']]:neighbor[n['id']]=r.summarize(batch(n,'neighbor_dev',study.dev))
        result=gates(source['full'][cfg['id']],a,b,c,neighbor);result['neighbors']=neighbor
        # Unknown development-period adjustments are not clean training evidence.
        development=json.loads((out/'windows.json').read_text(encoding='utf-8'))
        clean=all(z['unresolved_actions']==0 for z in development if z['id']==cfg['id'])
        result['checks']['development_actions']=clean
        if round_name in ('round16_financial_quality','round17_broad_quality','round18_earnings_value'):
            # Late UPDATE_DATE is conservative, but cannot prove original-vintage
            # field contents. Numeric gates alone must never certify this study.
            result['checks']['financial_vintage_verified']=False
            result['financial_vintage_note']='Exploratory current-vintage financials. Original filing verification and audited features required before completion.'
        result['passed']=all(result['checks'].values())
        results[cfg['id']]=result;r.save(out/'validation_progress.json',results)
    summary=dict(results=results,windows=len(rows),passed=[k for k,v in results.items() if v['passed']],
        common_end_starts=len(longs),rolling_starts=len(rolling),goal_achieved=any(v['passed'] for v in results.values()))
    r.save(out/'validation_summary.json',summary)
    lines=['# 沪深从零研究：'+round_name,'','全期及多起点验收；失败结果全部保留，不根据验证结果重新选择。','',
        '|候选|全期年化|全期回撤|全期Sharpe|实际平均仓位|不同起点同时达标比例|两年窗口Sharpe中位数|全部门槛通过|','|---|---:|---:|---:|---:|---:|---:|---|']
    for cid,z in results.items():
        f=source['full'][cid]
        lines.append('|%s|%.2f%%|%.2f%%|%.3f|%.2f%%|%.1f%%|%.3f|%s|'%(cid,100*f['annualized'],-100*f['drawdown'],f['sharpe'],100*f['mean_exposure'],100*z['long']['joint_pass_fraction'],z['rolling']['sharpe_median'],z['passed']))
    lines+=['','逐项验收：'+json.dumps(results,ensure_ascii=False),'',
        '10万元，截止2026-09-11；平台公式近似，Rf暂按2%。不是平台实测。不同窗口重叠、历史已见，多轮研究不等于独立样本外。具体交易与数据限制见PROTOCOL.md。']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(summary),flush=True)

if __name__=='__main__':
    import sys
    main(sys.argv[1] if len(sys.argv)>1 else 'round01_historical')
