"""Common-calendar style rotation, never empty, prior-session index states."""
import itertools,json,hashlib
import numpy as np
import pandas as pd
import research as r

OUT=r.HERE/'round03_calendar_regime'
ROUTES={'balanced':(('barbell','mid'),('defensive','small')),
        'liquidity':(('turn_contraction','small'),('defensive','large')),
        'small':(('barbell','small'),('defensive','small'))}
CONFIGS=[dict(id='C%02d'%(i+1),route=route,cadence=cadence,mode=mode,count=count,buffer=count*2,power=.5,minimum=1500)
    for i,(route,cadence,mode,count) in enumerate(itertools.product(ROUTES,('weekly','biweekly','monthly'),('fixed','floor60'),(8,12)))]

def calendar_dates(cal,start,end,cadence):
    if cadence=='monthly':due=pd.date_range('2020-01-01',end,freq='MS')
    else:due=pd.date_range('2020-01-06',end,freq='7D' if cadence=='weekly' else '14D')
    dates={start}
    for d in due:
        p=cal.searchsorted(d)
        if p<len(cal) and start<cal[p]<=end:dates.add(cal[p])
    return sorted(dates)

class Study:
    def __init__(self):
        r.FEATURES=r.HERE/'features_historical_lowvol.parquet'
        base=[dict(family=f,size=s,count=12,buffer=40) for f,s in sorted(set(x for route in ROUTES.values() for x in route))]
        self.base=r.Study(base);self.cal=self.base.cal
        self.dev=[self.cal[self.cal.get_loc(d)+n] for d in self.base.dev for n in (0,5,10)]
        idx=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
        strong=(idx>idx.rolling(120).mean()).shift(1)
        self.strong=strong.to_dict()

    def run(self,cfg,start,end=None,stress=False):
        e=r.e;end=min(r.END,start+pd.DateOffset(months=24)-pd.Timedelta(days=1)) if end is None else end
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.DELISTING_EVENTS=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[v*(2 if stress else 1) for v in self.base.cost]
        ranks={};exposures={}
        for d in calendar_dates(self.cal,start,end,cfg['cadence']):
            strong=bool(self.strong[d]);route=ROUTES[cfg['route']][0 if strong else 1]
            q=self.base.ranks[route][d].copy();q['downside']=q.downside.pow(cfg['power']);ranks[d]=q
            exposures[d]=.85 if cfg['mode']=='fixed' else (.95 if strong else .6)
        curve,trades=e.simulate(ranks,.05,cfg['count'],cfg['buffer'],exposures,1.5,self.base.panel,min_adjustment=cfg['minimum'])
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        assert all(len(x['selected'])<=cfg['count'] for x in e.SELECTION_TRACE)
        z=dict(**r.measure(curve,risk_free_annual=.02),**r.exposure(curve),start=str(start.date()),end=str(curve.date.iloc[-1].date()),
            fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS),delisting_writeoffs=len(e.DELISTING_EVENTS))
        return z,curve,trades

def main():
    OUT.mkdir(exist_ok=True);assert not (OUT/'summary.json').exists()
    r.save(OUT/'protocol.json',dict(configs=CONFIGS,routes=ROUTES,
        method='Common Monday,14day anchored2020Jan6,or month-start rebalance. Immediate first entry then shared calendar. PriorcloseCSI500>prior120MA chooses offensive vs defensive signals. Fixed85% or95/60%target,neverempty.',
        dev='24 starts:2020/21quarter first,+5,+10sessions;24months. Top3 medianSharpe,annualmedian>12%,Sharpe>.85,P10>0,DD>=-35%,meanexposure>50%each,flatstreak<=5,no unresolved actions.',
        acceptance=(r.HERE/'PROTOCOL.md').read_text(encoding='utf-8'),source_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest()))
    study=Study();rows=[];dev={}
    for cfg in CONFIGS:
        batch=[]
        for start in study.dev:
            z,_,_=study.run(cfg,start);z.update(id=cfg['id'],split='dev');rows.append(z);batch.append(z)
        dev[cfg['id']]=r.summarize(batch)
        r.save(OUT/'windows.json',rows);r.save(OUT/'development.json',dev)
        print('DEV',cfg['id'],json.dumps(dev[cfg['id']]),flush=True)
    pool=[c for c in CONFIGS if dev[c['id']]['annual_median']>.12 and dev[c['id']]['sharpe_median']>.85 and dev[c['id']]['annual_p10']>0 and dev[c['id']]['worst_dd']>=-.35 and dev[c['id']]['min_exposure']>.5 and dev[c['id']]['max_flat_streak']<=5 and all(z['unresolved_actions']==0 for z in rows if z['id']==c['id'])]
    winners=sorted(pool,key=lambda c:dev[c['id']]['sharpe_median'],reverse=True)[:3]
    r.save(OUT/'frozen_winners.json',winners);full={}
    for c in winners:
        z,curve,trades=study.run(c,study.dev[0],r.END);full[c['id']]=z
        r.save(OUT/(c['id']+'_curve.json'),json.loads(curve.to_json(orient='records',date_format='iso')))
        r.save(OUT/(c['id']+'_trades.json'),json.loads(trades.to_json(orient='records',date_format='iso')))
    result=dict(configs=CONFIGS,development=dev,winners=winners,full=full,windows=len(rows),goal_achieved=False)
    r.save(OUT/'summary.json',result);print('DONE',json.dumps(dict(winners=winners,full=full,windows=len(rows))),flush=True)

if __name__=='__main__':main()
