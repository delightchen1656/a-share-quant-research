"""Ten predeclared structural directions; inherited data limitations stay explicit."""
import json,hashlib
import numpy as np
import pandas as pd
import group_research as g
import monthly_A_structure_engine as e
from start_date_robustness import measure
from robust_policy_search import summarize

HERE=g.HERE;OUT=HERE/'monthly_A_structure_20260925';ALIGN=HERE/'monthly_A_alignment_20260924'
CONFIGS=[dict(id='B00',name='原月初A',strict=False),
 dict(id='S01',name='严格6只'),dict(id='S02',name='等权',power=0),
 dict(id='S03',name='降低分红依赖',ranking='low_div'),dict(id='S04',name='去除分红因子',ranking='no_div'),
 dict(id='S05',name='弱市增加趋势项',ranking='weak_trend'),
 dict(id='S06',name='市场波动降仓',exposure_mode='vol'),
 dict(id='S07',name='均线趋势过滤',ranking='trend_filter'),
 dict(id='S08',name='扩大保留缓冲',buffer=40),dict(id='S09',name='减少小额调仓',minimum=5000),
 dict(id='S10',name='弱市温和降仓',exposure_mode='weak')]

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class Study:
    def __init__(self):
        index=pd.read_parquet(e.DATA/'indices/000905.SH.parquet').sort_values('date');index['date']=pd.to_datetime(index.date)
        self.cal=pd.DatetimeIndex(index.date);e.CALENDAR=self.cal;e.INITIAL_CASH=100000.
        first=pd.DatetimeIndex(g.features().execute_date.unique()).sort_values()
        expand=lambda dates:[self.cal[self.cal.get_loc(d)+n] for d in dates for n in (0,5,10)]
        self.dev=expand([d for d in first if d.year in (2020,2021) and d.month in (1,4,7,10)])
        self.audit=expand([d for d in first if d.year==2024 and d.month<=8])
        dates=set(first)|set(self.dev)|set(self.audit)
        factors=pd.read_parquet(HERE/'cadence_multiround_100k/exact_date_factors.parquet')
        self.ranks={c['id']:{} for c in CONFIGS};self.exposures={c['id']:{} for c in CONFIGS}
        union=set()
        for d,x in factors[factors.execute_date.isin(dates)].groupby('execute_date'):
            assert x.signal_date.max()<d
            hist=index[index.date<=x.signal_date.iloc[0]];strong=hist.close.iloc[-1]>hist.close.tail(120).mean()
            vol=hist.close.pct_change().tail(20).std()*np.sqrt(252)
            for cfg in CONFIGS:
                q=x.sort_values('symbol').copy();mode=cfg.get('ranking','base')
                if not strong:q=q[q.float_cap_proxy_group==1].copy()
                if mode=='trend_filter':
                    filtered=q[q.below_ma60<=1e-10]
                    if len(filtered)>=24:q=filtered.copy()
                hi=lambda col:q[col].rank(pct=True)
                if strong:
                    a,b,c=(.35,.30,.35) if mode=='low_div' else ((.55,.45,0) if mode=='no_div' else (.25,.20,.55))
                    q['score']=a*e.rank01(q.amount20.to_numpy(),True)+b*e.rank01(q.near_high.to_numpy())+c*e.rank01(q.dividend.to_numpy())
                elif mode=='low_div':q['score']=.35*hi('dividend')+.45*(1-hi('downside'))+.20*(1-hi('turn20'))
                elif mode=='no_div':q['score']=.65*(1-hi('downside'))+.35*(1-hi('turn20'))
                elif mode=='weak_trend':q['score']=.35*hi('dividend')+.30*(1-hi('downside'))+.15*(1-hi('turn20'))+.20*hi('near_high')
                else:q['score']=.55*hi('dividend')+.30*(1-hi('downside'))+.15*(1-hi('turn20'))
                ranked=q.dropna(subset=['score']).sort_values(['score','symbol'],ascending=[False,True]).head(cfg.get('buffer',24))
                assert len(ranked)>=6
                self.ranks[cfg['id']][d]=ranked[['symbol','downside']].copy();union.update(ranked.symbol)
                mode=cfg.get('exposure_mode','base')
                exposure=max(.4,.8*min(1.,.15/max(vol,1e-8))) if mode=='vol' else (.6 if mode=='weak' and not strong else .8)
                self.exposures[cfg['id']][d]=exposure
        self.panel=e.load_daily_panel(union);e.PREPARED={pd.Timestamp(d):x.set_index('symbol') for d,x in self.panel.groupby('date')}
        self.initial=(e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION);e.ACTION_LEDGER={}
        ledger=json.loads((ALIGN/'action_ledger/manifest.json').read_text(encoding='utf-8'))
        for item in ledger['results']:
            for row in item['rows']:
                d=pd.Timestamp(row['dividOperateDate']);num=lambda key:float(row.get(key) or 0)
                e.ACTION_LEDGER[(d,item['symbol'])]=dict(cash=num('dividCashPsBeforeTax'),bonus=num('dividStocksPs')+num('dividReserveToStockPs'),pay_date=pd.Timestamp(row.get('dividPayDate') or d),stock_date=pd.Timestamp(row.get('dividStockMarketDate') or d+pd.Timedelta(days=1)))

    def run(self,cfg,start,stress=False,full=False):
        end=pd.Timestamp('2026-09-11') if full else start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True;e.STRICT_TARGET=cfg.get('strict',True)
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.initial]
        dates={start}
        for due in pd.date_range(start.replace(day=1),end,freq='MS'):
            d=self.cal[self.cal.searchsorted(due)]
            if start<d<=end:dates.add(d)
        ranks={};exposures={}
        for d in sorted(dates):
            q=self.ranks[cfg['id']][d].copy();q['downside']=q.downside.pow(cfg.get('power',.5));ranks[d]=q
            exposures[d]=self.exposures[cfg['id']][d]
        curve,trades=e.simulate(ranks,.05,6,cfg.get('buffer',24),exposures,1.5,self.panel,min_adjustment=cfg.get('minimum',3000))
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        if e.STRICT_TARGET:assert all(len(t['selected'])<=6 for t in e.SELECTION_TRACE)
        return dict(**measure(curve),start=str(start.date()),end=str(curve.date.iloc[-1].date()),fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS)),curve

def gate(a,b):
    return a['median']>b['median']+.001 and a['sharpe']>b['sharpe']+.01 and a['p10']>=b['p10']-.01 and a['drawdown']>=b['drawdown']-.02

def main():
    OUT.mkdir(exist_ok=True)
    assert not (OUT/'summary.json').exists(),'Completed study exists; preserve it.'
    save('protocol.json',dict(configs=CONFIGS,selection='Freeze up to two highest (annual gain/.02 + Sharpe gain/.1) among development gate passers against B00. No audit reselection.',gate='Median annual +.1pp; median Sharpe +.01; P10 not worse by1pp; worstDD not worse by2pp.',windows='24 development 2020/21 starts;24 audit 2024 starts;24months each; same offsets as prior100. Already seen and overlapping, not pristine OOS.',limitations='Incomplete pre2018 warmup; daily open/volume proxy; some corporate action payment dates approximated; no platform parity. Strict target on all S variants; B00 unchanged. Full period only after freezing.',screenshot=dict(return_pct=121.06,annual_pct=12.91,sharpe=.61,max_drawdown_pct=19.94,date_range='Not identifiable from screenshot; not used to calibrate local parameters.')))
    study=Study();rows=[];dev={}
    for cfg in CONFIGS:
        group=[]
        for start in study.dev:
            stat,_=study.run(cfg,start);row=dict(id=cfg['id'],split='dev',**stat);rows.append(row);group.append(row)
        dev[cfg['id']]=summarize(group);save('development.json',dev);save('windows.json',rows)
        print('DEVELOP',cfg['id'],json.dumps(dev[cfg['id']]),flush=True)
    base=dev['B00'];eligible=[c for c in CONFIGS[1:] if gate(dev[c['id']],base)]
    winners=sorted(eligible,key=lambda c:(dev[c['id']]['median']-base['median'])/.02+(dev[c['id']]['sharpe']-base['sharpe'])/.1,reverse=True)[:2]
    save('frozen_winners.json',winners)
    # Strict-count control is always audited so other structural effects can be distinguished.
    selected={c['id']:c for c in CONFIGS[:2]+winners};validation={};full={}
    for cfg in selected.values():
        validation[cfg['id']]={}
        for split,stress in [('audit',False),('stress',True)]:
            group=[]
            for start in study.audit:
                stat,_=study.run(cfg,start,stress);row=dict(id=cfg['id'],split=split,**stat);rows.append(row);group.append(row)
            validation[cfg['id']][split]=summarize(group);save('validation.json',validation);save('windows.json',rows)
            print('VALIDATE',cfg['id'],split,json.dumps(validation[cfg['id']][split]),flush=True)
        full[cfg['id']],curve=study.run(cfg,study.dev[0],full=True)
        save(cfg['id']+'_curve.json',json.loads(curve.to_json(orient='records',date_format='iso')))
    previous=json.loads((HERE/'monthly_A_100_rounds_existing_history/summary.json').read_text(encoding='utf-8'))['full']['R015']
    for key in ('final_equity','annualized','drawdown','sharpe'):assert abs(full['B00'][key]-previous[key])<1e-7,(key,full['B00'][key],previous[key])
    passed={}
    for cfg in winners:
        v=validation[cfg['id']];b=validation['B00'];a=v['stress'];s=b['stress']
        passed[cfg['id']]=bool(gate(v['audit'],b['audit']) and a['median']>=s['median'] and a['sharpe']>=s['sharpe'] and a['p10']>=s['p10']-.01 and a['drawdown']>=s['drawdown']-.02)
    summary=dict(development=dev,validation=validation,full=full,winners=winners,passed=passed,windows=len(rows),platform_parity=False,full_runs=len(full))
    save('summary.json',summary)
    lines=['# 月初A十方向结构研究','','原始平台策略未覆盖。全部结果仅为受数据/撮合限制的本地研究。','', '|编号|方向|开发年化中位数|P10|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|---:|']
    for c in CONFIGS:
        z=dev[c['id']];lines.append('|%s|%s|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(c['id'],c['name'],100*z['median'],100*z['p10'],-100*z['drawdown'],z['sharpe']))
    lines+=['','|编号|验证类型|年化中位数|最差回撤|Sharpe中位数|','|---|---|---:|---:|---:|']
    for cid,splits in validation.items():
        for split,z in splits.items():lines.append('|%s|%s|%.2f%%|%.2f%%|%.3f|'%(cid,split,100*z['median'],-100*z['drawdown'],z['sharpe']))
    lines+=['','|编号|全期终值|年化|最大回撤|Sharpe|','|---|---:|---:|---:|---:|']
    for cid,z in full.items():lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe']))
    lines+=['','候选验证通过：'+json.dumps(passed),'窗口数：'+str(len(rows)),'全期2020-01-02至2026-09-11，初始10万元，Sharpe按无风险利率0计算，不与截图0.61直接等同比较。','历史和窗口已反复使用；不能声称独立样本外。早期预热、平台排序与分钟撮合差异仍未解决。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('DONE',json.dumps({k:summary[k] for k in ('windows','passed','full_runs')}),flush=True)

if __name__=='__main__':main()
