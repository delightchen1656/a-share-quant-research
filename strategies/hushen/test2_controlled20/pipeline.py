"""Time-isolated, cash-ledger controlled-variable D11 experiments."""
from pathlib import Path
from types import SimpleNamespace as NS
from functools import lru_cache
import importlib.util, json, hashlib, math, sys, time, socket, gc
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; BASE=HERE.parent; ROOT=BASE.parents[1]
ENTRY=BASE/'test2_weekly/uploaded_source.py'
RAW=ROOT/'sh_sz_market_research/data_pipeline/data'
FIELDS=['open','high','low','close','preclose','volume','amount','turn','tradestatus','isST','volume20','prev_actual','adjust_ratio']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8');tmp.replace(p)
def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
Q=read(HERE/'protocol.json')
def signature(c):return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:16]

def engine_module():
    # Only replace hardcoded scheduling in the shared execution adapter.
    source=BASE/'start_date_study/study.py'
    code=source.read_text(encoding='utf-8')
    old='if g.alpha_first or (index-1)%20==0:g.alpha_ranks=ranks[str(prev.date())]'
    assert code.count(old)==1
    code=code.replace(old,'if g.alpha_first or (index-1)%m.INTERVAL==0:g.alpha_ranks=ranks[str(prev.date())]')
    m=NS(__file__=str(source),__name__='controlled_engine')
    exec(compile(code,str(source),'exec'),m.__dict__)
    # Functions created by exec reference this same dictionary.
    m.load_model=lambda k:m.module(ENTRY,'controlled_export')
    return m

class Day:
    def __init__(self,stage,index):self.stage=stage;self.index=index;self.cache={}
    def get(self,s,default=None):
        if s not in self.stage.columns:return default
        if s not in self.cache:
            j=self.stage.columns[s];i=self.index
            if not self.stage.present[i,j]:self.cache[s]=None
            else:self.cache[s]=NS(**{k:float(v[i,j]) for k,v in self.stage.raw.items()})
        return self.cache[s] if self.cache[s] is not None else default
    def __contains__(self,s):return self.get(s) is not None
    def __getitem__(self,s):
        result=self.get(s)
        if result is None:raise KeyError(s)
        return result

class Days:
    def __init__(self,stage):self.stage=stage
    @lru_cache(maxsize=3)
    def __getitem__(self,d):return Day(self.stage,self.stage.dates.get_loc(d))

class Actions:
    """Fetch only missing stock-year events actually encountered by held shares."""
    def __init__(self,end):
        self.end=end;self.cache={};self.own=HERE/'additional_actions.json';self.connected=False;self.lookup={}
        paths=set(BASE.rglob('actions_*.json'))|set(BASE.rglob('action_part_*.json'))|set(BASE.rglob('additional_actions.json'))
        for p in sorted(paths):
            # Files are response caches, never result/ranking files.
            self.cache.update(read(p))
        self.extra=read(self.own) if self.own.exists() else {}
    def ensure(self,s,date):
        key=s+'/'+str(date.year)
        if key not in self.cache:
            import baostock as bs
            socket.setdefaulttimeout(35)
            if not self.connected:
                assert bs.login().error_code=='0';self.connected=True
            for attempt in range(4):
                try:
                    result=bs.query_dividend_data(code=s[-2:].lower()+'.'+s[:6],year=str(date.year),yearType='operate')
                    rows=[]
                    while result.error_code=='0' and result.next():rows.append(result.get_row_data())
                    if result.error_code!='0':raise RuntimeError(result.error_msg)
                    records=pd.DataFrame(rows,columns=result.fields).to_dict('records');break
                except Exception:
                    if attempt==3:raise
                    time.sleep(1);bs.login()
            self.cache[key]=records;self.extra[key]=records;dump(self.own,self.extra)
            if len(self.extra)%10==0:print('ACTION_RESPONSES',len(self.extra),flush=True)
        if key not in self.lookup:
            def num(x):return float(x) if str(x).strip() else 0.
            events={}
            for r in self.cache[key]:
                if not r['dividOperateDate']:continue
                d=pd.Timestamp(r['dividOperateDate'])
                if d>self.end:continue
                events[d]=dict(cash=num(r['dividCashPsBeforeTax']),stock=num(r['dividStocksPs'])+num(r['dividReserveToStockPs']),
                    taxable_stock=num(r['dividStocksPs']),pay=pd.Timestamp(r['dividPayDate'] or r['dividOperateDate']),
                    release=pd.Timestamp(r['dividStockMarketDate'] or r['dividOperateDate']))
            self.lookup[key]=events
        return self.lookup[key].get(date)
    def close(self):
        if self.connected:
            import baostock as bs
            bs.logout();self.connected=False

class Stage:
    def __init__(self,name):
        self.name=name;self.start,self.end=map(pd.Timestamp,Q['periods'][name])
        self.folder=HERE/name;self.folder.mkdir(exist_ok=True)
        if name=='heldout':
            assert (HERE/'frozen.json').exists() and (HERE/'confirmation/evaluation.json').exists()
            files=sorted((RAW/'raw').glob('*/*.parquet'));b=BASE/'start_date_study/benchmark.parquet';manifest=None
        else:
            if name=='confirmation':assert (HERE/'frozen.json').exists()
            manifest=read(BASE/'retrain_2022'/f'{name}_snapshot_manifest.json')
            folder=BASE/'retrain_2022'/f'{name}_snapshot'
            files=[folder/(r['symbol']+'.parquet') for r in manifest['files']];b=folder/'benchmark.parquet'
            assert sha(b)==manifest['benchmark_sha256']
        benchmark=pd.read_parquet(b);benchmark.date=pd.to_datetime(benchmark.date)
        benchmark=benchmark[benchmark.date<=self.end]
        self.dates=pd.DatetimeIndex(benchmark.date);self.symbols=sorted(p.stem for p in files);self.columns={s:i for i,s in enumerate(self.symbols)}
        shape=(len(self.dates),len(self.symbols))
        self.raw={k:np.full(shape,np.nan,dtype=np.float64) for k in FIELDS}
        self.present=np.zeros(shape,dtype=bool)
        self.feature={k:np.full(shape,np.nan,dtype=np.float32) for k in ['cap','age','amount20']+['vol'+str(v) for v in [20,40,60,120]]+['ov'+str(v) for v in [5,10,20,40,60]]+['intr'+str(v) for v in [5,10,20,40,60]]}
        expected={r['symbol']:r['sha256'] for r in manifest['files']} if manifest else {}
        inputs=[]
        for n,path in enumerate(files):
            h=sha(path)
            if expected:assert h==expected[path.stem]
            x=pd.read_parquet(path);x.date=pd.to_datetime(x.date)
            if manifest:assert x.date.max()<=self.end
            x=x[x.date<=self.end].set_index('date').sort_index()
            assert not x.index.has_duplicates
            for k in FIELDS[:10]:x[k]=pd.to_numeric(x[k],errors='raise')
            x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual
            ix=self.dates.get_indexer(x.index);mask=ix>=0;ix=ix[mask];x=x.iloc[np.flatnonzero(mask)];j=self.columns[path.stem]
            for k in FIELDS:self.raw[k][ix,j]=x[k].to_numpy()
            self.present[ix,j]=True
            y=x[x.close>0];iy=self.dates.get_indexer(y.index)
            r=(y.close/y.preclose-1).where(y.tradestatus.eq(1)&y.preclose.gt(0),0.)
            ov=np.log(y.open/y.preclose).replace([np.inf,-np.inf],np.nan).fillna(0.)
            intr=np.log(y.close/y.open).replace([np.inf,-np.inf],np.nan).fillna(0.)
            values=dict(cap=y.close*y.volume/(y.turn/100).replace(0,np.nan),age=np.arange(len(y))+1,amount20=y.amount.rolling(20).mean())
            for v in [20,40,60,120]:values['vol'+str(v)]=r.rolling(v).std()
            for v in [5,10,20,40,60]:values['ov'+str(v)]=ov.rolling(v).sum();values['intr'+str(v)]=intr.rolling(v).sum()
            for k,v in values.items():self.feature[k][iy,j]=np.asarray(v,dtype=np.float32)
            inputs.append(dict(symbol=path.stem,sha256=h,max_date=str(x.index.max().date())))
            if (n+1)%700==0:print('LOAD',name,n+1,len(files),flush=True)
        dump(self.folder/'inputs.json',dict(files=inputs,benchmark_sha256=sha(b),max_date=str(self.dates.max().date()),protocol_sha256=sha(HERE/'protocol.json')))
        self.sessions=self.dates[(self.dates>=self.start)&(self.dates<=self.end)]
        self.days=Days(self);self.actions=Actions(self.end);self.rank_key=None;self.rank_data=None
        meta=pd.read_csv(RAW/'metadata/historical_mainboard_universe.csv')
        self.outs={r.symbol:pd.Timestamp(r.outDate) for r in meta.itertuples() if pd.notna(r.outDate) and pd.Timestamp(r.outDate)<=self.end}
        self.engine=engine_module()
    def signals(self,c):
        keys=['smooth','min_smooth','weights','vol_window','return_window','amount_min','vol_max']
        sig=signature({k:c[k] for k in keys});p=self.folder/('signals_'+sig+'.json')
        if p.exists():return read(p)
        f=self.feature;v=f['vol'+str(c['vol_window'])]
        eligible=(f['age']>=252)&(f['amount20']>=c['amount_min'])&(self.raw['close']>=2)&(self.raw['isST']==0)&(self.raw['tradestatus']==1)&(v>.001)&(v<c['vol_max'])
        rank_key=(c['vol_window'],c['return_window'],c['amount_min'],c['vol_max'])
        if self.rank_key!=rank_key:
            self.rank_data=None;gc.collect()
            self.rank_data=[pd.DataFrame(f[k],index=self.dates,columns=self.symbols).where(eligible).rank(axis=1,pct=True,method='average').astype(np.float32)
                for k in ['cap','vol'+str(c['vol_window']),'ov'+str(c['return_window']),'intr'+str(c['return_window'])]]
            self.rank_key=rank_key
        a,b,d,e=c['weights'];rank=self.rank_data
        score=(-a*rank[0]-b*rank[1]+d*rank[2]-e*rank[3]).rolling(c['smooth'],min_periods=c['min_smooth']).mean().astype(np.float32).where(eligible)
        result={}
        for i in range(self.dates.get_loc(self.sessions[0])-1,len(self.dates)-1):
            x=score.iloc[i].dropna().sort_values(ascending=False,kind='mergesort').head(100)
            result[str(self.dates[i].date())]=x.index.tolist()
        dump(p,result);return result
    def simulate(self,c,cid):
        folder=self.folder/'runs';folder.mkdir(exist_ok=True);p=folder/(signature(c)+'.json')
        if p.exists():
            r=read(p);assert r['config']==c;return dict(r,id=cid)
        ranks=self.signals(c);a=self.engine.Account('D11',self.sessions[0],{},self.days,self.outs)
        a.m.BUFFER=c['buffer'];a.m.INTERVAL=c['interval'];a.m.COUNT=c['count']
        schedules=[]
        for date in self.sessions:
            i=self.dates.get_loc(date);due=a.m.g.alpha_first or (i-1)%c['interval']==0
            prior=a.curve[-1]['equity'] if a.curve else 100000.
            if due:
                n=c['count']
                if c['growth']:
                    n=a.m.COUNT;cap=max(15,c['count'])
                    while n<cap and prior>=100000*c['growth']**(n-c['count']+1):n+=1
                    while n>c['count'] and prior<100000*c['growth']**(n-c['count'])*(1-c['hysteresis']):n-=1
                a.m.COUNT=n
            # Corporate actions can happen with little price movement; query each held stock-year, not only visible price breaks.
            for s in a.holdings:
                act=self.actions.ensure(s,date)
                if act:a.actions[s,date]=act
            before=a.m.g.alpha_targets
            a.step(date,i,self.dates[i-1],ranks)
            assert (before is not a.m.g.alpha_targets)==due
            if due:
                assert sum(v>0 for v in a.m.g.alpha_targets.values())<=a.m.COUNT
                schedules.append(dict(date=date,prior_equity=prior,count=a.m.COUNT))
            a.curve[-1].update(limit=a.m.COUNT,holdings=len(a.holdings))
        curve=pd.DataFrame(a.curve);nav=curve.equity.to_numpy();returns=nav/np.r_[100000.,nav[:-1]]-1
        dd=1-nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]
        r=dict(id=cid,config=c,start=str(self.sessions[0].date()),end=str(self.sessions[-1].date()),final_equity=float(nav[-1]),
            cagr=float((nav[-1]/100000)**(365.25/((self.sessions[-1]-self.sessions[0]).days+1))-1),total_return=float(nav[-1]/100000-1),
            max_drawdown=float(dd.max()),sharpe=float(returns.mean()/returns.std(ddof=1)*np.sqrt(252)),trades=len(a.trades),
            avg_exposure=float(curve.exposure.mean()),fees=a.fees,dividend_tax=a.tax,final_limit=a.m.COUNT,
            issues=a.issues,reference_differences=a.reference_diffs,capacity_rejections=a.capacity_hits)
        assert curve.cash.min()>=-.01
        assert all(t['qty']%100==0 for t in a.trades if t['qty']>0)
        curve.to_parquet(folder/(signature(c)+'_equity.parquet'),index=False)
        pd.DataFrame(a.trades).to_parquet(folder/(signature(c)+'_trades.parquet'),index=False)
        dump(folder/(signature(c)+'_schedule.json'),schedules);dump(p,r)
        print('RESULT',self.name,cid,'CAGR',round(r['cagr'],4),'DD',round(r['max_drawdown'],4),'issues',len(r['issues']),flush=True)
        return r
    def close(self):self.actions.close();self.days.__getitem__.cache_clear()

def rankkey(r):return (-r['cagr'],-r['sharpe'],r['max_drawdown'],r['id'])
def valid(r,baseline,stage):
    return not r['issues'] and not r['reference_differences'] and r['trades']>=(40 if stage=='training' else 10) and r['avg_exposure']>=.15 and r['max_drawdown']<=baseline['max_drawdown']+.02
def training(combined=False):
    assert not (HERE/'frozen.json').exists(),'Frozen; training prohibited'
    name='combined_training' if combined else 'group_training'
    if (HERE/(name+'.json')).exists():return
    trials=read(HERE/'combined_candidates.json') if combined else Q['trials']
    stage=Stage('training')
    try:
        baseline=stage.simulate(Q['base'],'baseline');rows=[dict(stage.simulate(t['config'],t['id']),group=t.get('group','combined')) for t in trials]
        shortlist={}
        for g in ['combined'] if combined else Q['groups']:
            ok=[r for r in rows if r['group']==g and valid(r,baseline,'training')]
            shortlist[g]=[r['id'] for r in sorted(ok,key=rankkey)[:3]]
        dump(HERE/(name+'.json'),dict(baseline=baseline,results=rows,shortlist=shortlist))
    finally:stage.close()

def selection(combined=False):
    assert not (HERE/'frozen.json').exists(),'Frozen; selection prohibited'
    dest=HERE/('combined_selection.json' if combined else 'group_selection.json')
    if dest.exists():return
    tr=read(HERE/('combined_training.json' if combined else 'group_training.json'))
    stage=Stage('selection')
    try:
        baseline=stage.simulate(Q['base'],'baseline');rows=[];winners={}
        for group,ids in tr['shortlist'].items():
            candidates=[r for r in tr['results'] if r['id'] in ids]
            if combined:
                candidates+=list(read(HERE/'group_selection.json')['winners'].values())
            tested=[stage.simulate(t['config'],t['id']) for t in candidates]
            rows.extend(dict(t,group=group) for t in tested)
            eligible=[r for r in tested if valid(r,baseline,'selection')]+[baseline]
            winners[group]=sorted(eligible,key=rankkey)[0]
        dump(dest,dict(baseline=baseline,results=rows,winners=winners,protocol_sha256=sha(HERE/'protocol.json')))
        if not combined:
            combinations=[]
            for i,groups in enumerate(Q['combined_subsets']):
                c=dict(Q['base'])
                for group in groups:
                    for key in Q['group_keys'][group]:c[key]=winners[group]['config'][key]
                combinations.append(dict(id=f'combined_{i+1:02}',config=c,groups=groups))
            dump(HERE/'combined_candidates.json',combinations)
        else:
            dump(HERE/'frozen.json',dict(winner=winners['combined'],group_winners=read(HERE/'group_selection.json')['winners'],
                source_sha256=sha(ENTRY),engine_sha256=sha(BASE/'start_date_study/study.py'),pipeline_sha256=sha(__file__),protocol_sha256=sha(HERE/'protocol.json'),
                group_training_sha256=sha(HERE/'group_training.json'),group_selection_sha256=sha(HERE/'group_selection.json'),
                combined_training_sha256=sha(HERE/'combined_training.json'),combined_selection_sha256=sha(dest),
                evaluation_not_started=True,combined_unique=len({signature(t['config']) for t in read(HERE/'combined_candidates.json')})))
    finally:stage.close()

def evaluation(name):
    frozen=read(HERE/'frozen.json');assert frozen['protocol_sha256']==sha(HERE/'protocol.json')
    assert frozen['source_sha256']==sha(ENTRY) and frozen['engine_sha256']==sha(BASE/'start_date_study/study.py')
    assert frozen['pipeline_sha256']==sha(__file__),'Frozen pipeline changed'
    if (HERE/name/'evaluation.json').exists():return
    stage=Stage(name)
    try:
        baseline=stage.simulate(Q['base'],'baseline')
        rows=[dict(stage.simulate(w['config'],w['id']),group=g) for g,w in frozen['group_winners'].items()]
        winner=stage.simulate(frozen['winner']['config'],frozen['winner']['id'])
        passed=winner['cagr']>0 and winner['cagr']>=baseline['cagr'] and winner['max_drawdown']<=baseline['max_drawdown']+.02 and not winner['issues'] and not winner['reference_differences']
        dump(stage.folder/'evaluation.json',dict(baseline=baseline,groups=rows,winner=winner,confirmation_passed=passed if name=='confirmation' else None,frozen_sha256=sha(HERE/'frozen.json')))
    finally:stage.close()

if __name__=='__main__':
    command=sys.argv[1]
    if command=='group_train':training()
    elif command=='group_select':selection()
    elif command=='combined_train':training(True)
    elif command=='combined_select':selection(True)
    elif command in ['confirmation','heldout']:evaluation(command)
