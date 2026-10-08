"""Predeclared signal research, fixed 80% exposure; no cash timing."""
import hashlib
import itertools
import json
import numpy as np
import pandas as pd
import monthly_A_structure_research as s
import monthly_A_invested_sharpe as p
import monthly_A_invested_engine as e
from supermind_performance import measure

HERE=s.HERE
OUT=HERE/'monthly_A_signal_blend_20260925'
CONFIGS=[dict(id='BASE',strict=False),dict(id='STRICT',strict=True)]+[
    dict(id='N%02d'%(i+1),strict=True,signal=signal,blend=blend)
    for i,(signal,blend) in enumerate(itertools.product(
        ('mom6','mom12','efficiency','reversal','mom_lowvol','trend_mom'),(.15,.30,.45)))]

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def price_signals(close):
    close=close.where(close>0)
    change=close.diff()
    return pd.DataFrame(dict(mom6=close.shift(21)/close.shift(126)-1,
        mom12=close.shift(21)/close.shift(252)-1,
        efficiency=(close-close.shift(126))/change.abs().rolling(126,min_periods=126).sum(),
        reversal=-(close/close.shift(21)-1)),index=close.index)

def blend_score(q,strong,signal=None,weight=0.):
    rank=lambda col:q[col].rank(pct=True)
    if strong:
        base=pd.Series(.25*e.rank01(q.amount20.to_numpy(),True)+.20*e.rank01(q.near_high.to_numpy())+.55*e.rank01(q.dividend.to_numpy()),index=q.index)
    else:base=.55*rank('dividend')+.30*(1-rank('downside'))+.15*(1-rank('turn20'))
    if signal is None:return base
    if signal=='mom_lowvol':extra=.5*rank('mom6').fillna(.5)+.5*(1-rank('downside').fillna(.5))
    elif signal=='trend_mom':extra=.5*rank('mom12').fillna(.5)+.5*rank('efficiency').fillna(.5)
    else:extra=rank(signal).fillna(.5)
    # Normalize base to comparable ordinal scale before mixing unrelated factors.
    return (1-weight)*base.rank(pct=True)+weight*extra

class Study:
    def __init__(self):
        s.e=e;s.CONFIGS=CONFIGS;s.measure=lambda c:measure(c,risk_free_annual=.02)
        self.base=s.Study();self.dev=self.base.dev;self.audit=self.base.audit
        dates=sorted(self.base.ranks['BASE'])
        self.bridge=[d for d in dates if d.year in (2022,2023) and d.month in (1,4,7,10) and d==min(x for x in dates if (x.year,x.month)==(d.year,d.month))]
        f=pd.read_parquet(HERE/'cadence_multiround_100k/exact_date_factors.parquet')
        f=f[f.execute_date.isin(dates)].copy()
        assert (f.signal_date<f.execute_date).all()
        chunks=[];coverage=[]
        for i,(symbol,rows) in enumerate(f.groupby('symbol')):
            path=e.qfq_path(symbol)
            if not path.exists():raise FileNotFoundError(path)
            prices=pd.read_parquet(path,columns=['date','close']).sort_values('date')
            prices['date']=pd.to_datetime(prices.date)
            assert not prices.date.duplicated().any()
            signals=price_signals(prices.set_index('date').close.astype(float))
            wanted=pd.DatetimeIndex(rows.signal_date)
            values=signals.reindex(wanted,method='ffill')
            last=pd.Series(signals.index,index=signals.index).reindex(wanted,method='ffill')
            stale=(wanted-last.to_numpy())>pd.Timedelta(days=10)
            values.loc[stale,:]=np.nan
            values.index=rows.index
            chunks.append(values)
            if i%500==0:print('FEATURES',i,flush=True)
        f=f.join(pd.concat(chunks))
        f.to_parquet(OUT/'signals.parquet',index=False)
        save('coverage.json',{k:float(f[k].notna().mean()) for k in ('mom6','mom12','efficiency','reversal')})
        index=pd.read_parquet(e.DATA/'indices/000905.SH.parquet').sort_values('date')
        union=set()
        for date,x in f.groupby('execute_date'):
            hist=index[index.date<=x.signal_date.iloc[0]]
            strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
            for cfg in CONFIGS:
                q=x.sort_values('symbol').copy()
                if not strong:q=q[q.float_cap_proxy_group==1].copy()
                q['score']=blend_score(q,strong,cfg.get('signal'),cfg.get('blend',0.))
                ranked=q.dropna(subset=['score']).sort_values(['score','symbol'],ascending=[False,True]).head(24)
                assert len(ranked)>=6
                if cfg['id']=='BASE':
                    assert list(ranked.symbol)==list(self.base.ranks['BASE'][date].symbol),(date,strong,list(ranked.symbol),list(self.base.ranks['BASE'][date].symbol))
                self.base.ranks[cfg['id']][date]=ranked[['symbol','downside']].copy()
                self.base.exposures[cfg['id']][date]=.8
                union.update(ranked.symbol)
        self.base.panel=e.load_daily_panel(union)
        e.PREPARED={pd.Timestamp(d):x.set_index('symbol') for d,x in self.base.panel.groupby('date')}
        e.SELECTOR=None

    def run(self,cfg,start,stress=False,full=False):
        z,curve=self.base.run(cfg,start,stress,full)
        z.update(p.exposure_stats(curve));return z,curve

def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'summary.json').exists(),'Preserve completed study'
    save('protocol.json',dict(configs=CONFIGS,exposure=.8,rf=.02,
        method='Original regime and universe; blend original ordinal rank with momentum126-21,252-21,signed126day path efficiency,21day reversal,50:50 momentum/lowdownside or efficiency/momentum. Weights15/30/45%. Missing signal neutral rank. Fixed80% target,6stocks,monthly,buffer24,originalcosts/minadjustment.',
        selection='Top2 development Sharpe among candidates with Sharpe>BASE+.01,medianannual>=BASE-.01,P10>=BASE-.01,worstDD>=BASE-.02,exposuregate. Freeze before bridge/audit/stress/full. No replacement if none eligible.',
        upgrade='Full and audit Sharpe improve by>.02 with annual>=BASE-1pp and DD>=BASE-2pp;bridge Sharpe>=BASE-.02;stress Sharpe>=BASE-.02;exposure gates every split. Sharpe1 is separate target.',
        limits='Repeated,overlapping known history;not independent OOS. Qfq caches/provider issues remain. Daily execution proxy,not exactSuperMindminute.250dayannualRFfixed2%.'))
    save('inputs.json',[dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in
        (HERE/'monthly_A_signal_blend.py',HERE/'monthly_A_invested_engine.py',HERE/'cadence_multiround_100k/exact_date_factors.parquet',s.ALIGN/'action_ledger/manifest.json')])
    study=Study();rows=[];dev={};validation={};full={}
    def group(cfg,split,dates,stress=False):
        batch=[]
        for start in dates:
            z,_=study.run(cfg,start,stress);z.update(id=cfg['id'],split=split);rows.append(z);batch.append(z)
        z=p.summarize_group(batch);save('windows.json',rows);print(split,cfg['id'],json.dumps(z),flush=True);return z
    for cfg in CONFIGS:
        dev[cfg['id']]=group(cfg,'dev',study.dev);save('development.json',dev)
    b=dev['BASE']
    pool=[c for c in CONFIGS[2:] if p.invested(dev[c['id']]) and dev[c['id']]['sharpe']>b['sharpe']+.01 and dev[c['id']]['median']>=b['median']-.01 and dev[c['id']]['p10']>=b['p10']-.01 and dev[c['id']]['drawdown']>=b['drawdown']-.02]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe'],reverse=True)[:2]
    save('frozen_winners.json',winners)
    for c in CONFIGS[:2]+winners:
        cid=c['id'];validation[cid]={}
        for split,dates,stress in [('bridge',study.bridge,False),('audit',study.audit,False),('stress',study.audit,True)]:
            validation[cid][split]=group(c,split,dates,stress);save('validation.json',validation)
        full[cid],curve=study.run(c,study.dev[0],full=True)
        save(cid+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    assert abs(full['BASE']['final_equity']-245749.27)<1e-7
    goals={}
    for c in winners:
        cid=c['id'];f=full[cid];b=full['BASE'];a=validation[cid]['audit'];ab=validation['BASE']['audit']
        checks=dict(full=f['sharpe']>b['sharpe']+.02 and f['annualized']>=b['annualized']-.01 and f['drawdown']>=b['drawdown']-.02,
            audit=a['sharpe']>ab['sharpe']+.02 and a['median']>=ab['median']-.01 and a['drawdown']>=ab['drawdown']-.02,
            bridge=validation[cid]['bridge']['sharpe']>=validation['BASE']['bridge']['sharpe']-.02,
            stress=validation[cid]['stress']['sharpe']>=validation['BASE']['stress']['sharpe']-.02,
            invested=all(p.invested(z) for z in [dev[cid]]+list(validation[cid].values())) and f['mean_exposure']>=.75 and f['low_exposure_fraction']<=.05 and f['max_flat_streak']<=2)
        goals[cid]=dict(checks=checks,upgrade=all(checks.values()),sharpe1=f['sharpe']>=1 and a['sharpe']>=1 and validation[cid]['bridge']['sharpe']>=1)
    result=dict(configs=CONFIGS,development=dev,winners=winners,validation=validation,full=full,goals=goals,windows=len(rows),rf=.02,platform_parity=False)
    save('summary.json',result)
    lines=['# 保持持仓：新增价格信号研究','','固定80%目标仓位，不设置空仓择时。18组预先定义候选，只有开发筛选通过者进入后续验证。平台公式近似，Rf暂按2%。','',
        '|版本|开发年化中位数|最差回撤|Sharpe中位数|最低窗口平均仓位|','|---|---:|---:|---:|---:|']
    for cid,z in dev.items():lines.append('|%s|%.2f%%|%.2f%%|%.3f|%.2f%%|'%(cid,100*z['median'],-100*z['drawdown'],z['sharpe'],100*z['worst_mean_exposure']))
    lines+=['','|版本|全期资金|年化|最大回撤|Sharpe|实际平均仓位|低于50%天数|','|---|---:|---:|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe'],100*z['mean_exposure'],z['low_exposure_days']))
    lines+=['','冻结候选：'+json.dumps(winners,ensure_ascii=False),'检查：'+json.dumps(goals,ensure_ascii=False),'窗口数：'+str(len(rows)),
        '全期10万元，2020-01-02至2026-09-11。开发24个2020/21起点、中段8个2022/23起点、后段24个2024起点，各24个月。成本压力佣金/最低佣金/滑点翻倍，税不变。历史已反复使用且窗口重叠，不能称独立样本外；分钟撮合及历史数据差异仍在。原平台策略不覆盖。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps(result['full']),json.dumps(goals),flush=True)

if __name__=='__main__':main()
