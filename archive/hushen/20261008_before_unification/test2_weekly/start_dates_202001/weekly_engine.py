"""Frozen cutoff R08 / D11: Q1-2021 starts, daily-data execution approximation.
No training, parameter search, or forward-return labels are used.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import sys, types, importlib.util, json, hashlib, math, socket, warnings, time
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'
END=pd.Timestamp('2026-09-30')
FILES={'R08':'supermind_mainboard_baseline_1_cutoff_20241130.py',
       'D11':'supermind_test2_D11_fast_cutoff_20241130.py'}
warnings.filterwarnings('ignore', category=FutureWarning)
def dump(name,x):
    payload=json.dumps(x,ensure_ascii=False,indent=2,default=str)
    for attempt in range(5):
        try:
            p=HERE/(name+'.tmp');p.write_text(payload,encoding='utf-8');p.replace(HERE/name);return
        except OSError:
            if attempt==4:raise
            time.sleep(.2*(attempt+1))
def read(name): return json.loads((HERE/name).read_text(encoding='utf-8'))
def bs_frame(r):
    rows=[]
    while r.error_code=='0' and r.next():rows.append(r.get_row_data())
    if r.error_code!='0':raise RuntimeError(r.error_msg)
    return pd.DataFrame(rows,columns=r.fields)
def module(path,name):
    sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def load_model(k): return module(HERE.parent/FILES[k],'model_'+k)
def benchmark():
    p=HERE/'benchmark.parquet'
    if not p.exists():
        import baostock as bs
        socket.setdefaulttimeout(45)
        assert bs.login().error_code=='0'
        try:
            r=bs.query_history_k_data_plus('sh.000905','date,close',start_date='2018-01-01',end_date='2026-09-30',frequency='d',adjustflag='3')
            assert r.error_code=='0',r.error_msg
            x=bs_frame(r);x.date=pd.to_datetime(x.date);x.close=pd.to_numeric(x.close);x.to_parquet(p,index=False)
        finally: bs.logout()
    x=pd.read_parquet(p).set_index('date').close
    assert x.index[-1]==END
    return x
def prepare():
    market=benchmark();dates=market.index
    starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]
    wanted=set(starts);last=None
    for i,d in enumerate(dates):
        if d<starts[0]:continue
        if last is None or (d.month!=last and d.month%2==1) or (i-1)%20==0:wanted.add(d)
        last=d.month
    signal_dates=pd.DatetimeIndex(sorted({dates[dates.get_loc(d)-1] for d in wanted}))
    models={k:load_model(k) for k in FILES}
    rawfiles=sorted((DATA/'raw').glob('*/*.parquet'));symbols=[p.stem for p in rawfiles]
    matrices={k:pd.DataFrame(np.nan,index=dates,columns=symbols,dtype=np.float32) for k in ('cap','vol','overnight','intraday')}
    eligible=pd.DataFrame(False,index=dates,columns=symbols)
    chunks=[];hashes={};panels=[];parity=[]
    for i,p in enumerate(rawfiles):
        s=p.stem;x=pd.read_parquet(p);x.date=pd.to_datetime(x.date);x=x[x.date<=END].set_index('date').sort_index()
        x=x[['open','high','low','close','preclose','volume','amount','turn','isST','tradestatus']].apply(pd.to_numeric,errors='coerce')
        assert not x.index.has_duplicates
        hashes[s]=hashlib.sha256(p.read_bytes()).hexdigest()
        # Old alias histories end before this study; require a current-day row.
        if x.empty:continue
        age=pd.Series(np.arange(len(x))+1,index=x.index)
        c=(x.close/x.preclose).where(lambda z:(z>0)&np.isfinite(z)).cumprod();r=c.pct_change(fill_method=None)
        a=np.log(c.reindex(dates)).diff();b=np.log(market).diff()
        va=a.rolling(252,min_periods=220).var();vb=b.rolling(252,min_periods=220).var()
        beta=a.rolling(252,min_periods=220).cov(b)/vb
        mom=a.rolling(232,min_periods=220).sum().shift(20);bm=b.rolling(232,min_periods=220).sum().shift(20)
        event=x.close.shift()/x.preclose-1
        f=pd.DataFrame(index=dates)
        f['float_cap_proxy']=x.volume/(x.turn.where(x.turn>0)/100)*x.close
        f['distribution_proxy']=event.where(event.between(.0005,.08),0).clip(upper=.04).rolling(250).sum()
        f['long_risk']=mom/(va.shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232))
        f['market_adjusted']=(mom-beta.shift(20)*bm)/((va-beta.pow(2)*vb).shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232))
        f['vol60']=r.rolling(60).std();f['ret5']=c/c.shift(5)-1;f['turn20']=x.turn.rolling(20).mean()
        ok=(age>=250)&x.isST.eq(0)&x.tradestatus.eq(1)&r.rolling(20).std().between(.001,.08)&x.amount.rolling(20).mean().ge(50e6)
        ok &= x.preclose.gt(0).rolling(250).sum().eq(250)
        take=f.reindex(signal_dates).loc[ok.reindex(signal_dates,fill_value=False)].copy();take['symbol']=s;take.index.name='date';chunks.append(take.reset_index())
        rr=(x.close/x.preclose-1).where(x.tradestatus.eq(1)&x.preclose.gt(0),0)
        vol=rr.rolling(60).std()
        ff={'cap':x.close*x.volume/(x.turn/100).replace(0,np.nan),'vol':vol,
            'overnight':np.log(x.open/x.preclose).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum(),
            'intraday':np.log(x.close/x.open).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum()}
        for k,v in ff.items():matrices[k][s]=v.astype(np.float32).reindex(dates)
        eligible[s]=((age>=252)&x.amount.rolling(20).mean().ge(1e7)&x.close.ge(2)&x.isST.eq(0)&x.tradestatus.eq(1)&vol.gt(.001)&vol.lt(.09)).reindex(dates,fill_value=False)
        x['volume20']=x.volume.rolling(20).mean();x['prev_actual']=x.close.shift();x['adjust_ratio']=x.preclose/x.prev_actual
        x['symbol']=s;panels.append(x.reset_index())
        # Independent exported scalar R08 feature parity on a representative date.
        if len(parity)<20 and len(take):
            d=take.index[-1];raw=x.loc[:d].tail(320).rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'}).copy();raw['is_paused']=1-raw.tradestatus
            check=models['R08'].stock_features(raw,raw,market.loc[:d].tail(320))
            if check:
                for key,v in check.items():assert np.isclose(v,f.loc[d,key],rtol=1e-7,atol=1e-9,equal_nan=True),(s,key)
                parity.append(s)
        if (i+1)%400==0:print('FEATURES',i+1,'/',len(rawfiles),flush=True)
    ranks={k:v.where(eligible).rank(axis=1,pct=True).astype(np.float32) for k,v in matrices.items()}
    score=(-.30*ranks['cap']-.25*ranks['vol']+.25*ranks['overnight']-.20*ranks['intraday']).rolling(5,min_periods=3).mean().astype(np.float32).where(eligible)
    d11={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist() for d in signal_dates}
    allf=pd.concat(chunks,ignore_index=True)
    r08={str(d.date()):models['R08'].rank_candidates(x).symbol.tolist() for d,x in allf.groupby('date')}
    candidates=set(s for rows in [r08,d11] for v in rows.values() for s in v)
    panel=pd.concat(panels,ignore_index=True);panel=panel[panel.symbol.isin(candidates)]
    panel.to_parquet(HERE/'candidate_daily.parquet',index=False)
    allf.to_parquet(HERE/'r08_features.parquet',index=False)
    dump('rankings.json',{'R08':r08,'D11':d11});dump('input_hashes.json',hashes)
    req=set()
    for s,x in panel.groupby('symbol'):
        z=x[(x.date>='2021-01-01')&((x.adjust_ratio-1).abs()>1e-5)]
        req.update((s,int(y)) for y in z.date.dt.year.unique())
    dump('action_requests.json',sorted(req));dump('preparation.json',{'starts':[str(d.date()) for d in starts],'candidates':len(candidates),'action_requests':len(req),'r08_scalar_parity':parity,'strategy_hashes':{k:hashlib.sha256((HERE.parent/v).read_bytes()).hexdigest() for k,v in FILES.items()}})
    print('PREPARED',len(starts),len(candidates),len(req),flush=True)

def fetch_actions(worker=0,workers=1):
    import baostock as bs
    socket.setdefaulttimeout(40)
    name='actions_%d.json'%worker;cache=read(name) if (HERE/name).exists() else {}
    requests=read('action_requests.json')[worker::workers]
    assert bs.login().error_code=='0'
    try:
        for i,(s,y) in enumerate(requests):
            key=s+'/'+str(y)
            if key in cache:continue
            for attempt in range(5):
                try:
                    r=bs.query_dividend_data(code=s[-2:].lower()+'.'+s[:6],year=str(y),yearType='operate')
                    if r.error_code!='0':raise RuntimeError(r.error_msg)
                    cache[key]=bs_frame(r).to_dict('records');break
                except Exception:
                    if attempt==4:raise
                    time.sleep(1);bs.login()
            if i%10==0:dump(name,cache);print('ACTIONS',worker,i,'/',len(requests),flush=True)
    finally:dump(name,cache);bs.logout()

def action_map():
    cache={}
    for p in HERE.glob('actions_*.json'):cache.update(json.loads(p.read_text(encoding='utf-8')))
    missing=[(s,y) for s,y in read('action_requests.json') if s+'/'+str(y) not in cache]
    assert not missing,('missing corporate action responses',len(missing))
    result={}
    def number(x):return float(x) if str(x).strip() else 0.
    for key,rows in cache.items():
        s=key.split('/')[0]
        for r in rows:
            if not r['dividOperateDate']:continue
            d=pd.Timestamp(r['dividOperateDate'])
            result[s,d]=dict(cash=number(r['dividCashPsBeforeTax']),stock=number(r['dividStocksPs'])+number(r['dividReserveToStockPs']),
                taxable_stock=number(r['dividStocksPs']),pay=pd.Timestamp(r['dividPayDate'] or r['dividOperateDate']),
                release=pd.Timestamp(r['dividStockMarketDate'] or r['dividOperateDate']))
    return result

class Account:
    def __init__(self,model,start,actions,days,meta,capacity_scale=1):
        self.model=model;self.start=start;self.actions=actions;self.days=days;self.meta=meta;self.capacity_scale=capacity_scale
        self.cash=100000.;self.holdings={};self.receivables=[];self.trades=[];self.issues={};self.reference_diffs={};self.capacity_hits=0;self.tax=0.;self.fees=0.;self.curve=[]
        self.m=load_model(model);m=self.m;m.g=NS();m.log=NS(info=lambda *a:None,warn=lambda *a:None)
        for name in ['set_benchmark','set_slippage','set_commission','set_volume_limit','enable_open_bar']:setattr(m,name,lambda *a,**kw:None)
        m.PriceSlippage=lambda *a:None;m.PerShare=lambda **kw:None
        m.get_datetime=lambda:self.date.to_pydatetime().replace(hour=9,minute=31)
        m.get_open_orders=lambda:[];m.order=self.order
        self.positions={};self.stock=NS(available_cash=self.cash,frozen_cash=0,total_value=self.cash)
        self.context=NS(portfolio=NS(positions=self.positions,stock_account=self.stock))
        m.init(self.context)
    def available(self,s):return sum(l['q'] for l in self.holdings[s]['lots'] if l['release']<=self.date and l['buy']<self.date)
    def sync(self):
        self.positions.clear()
        value=0.
        for s,p in self.holdings.items():
            if p['qty']<=0:continue
            row=self.day.get(s);price=float(row.open) if row is not None and row.open>0 else p['last']
            self.positions[s]=NS(amount=p['qty'],available_amount=self.available(s),last_price=p['last'])
            value+=p['qty']*price
        self.stock.available_cash=self.cash
        self.stock.frozen_cash=sum(a for d,a in self.receivables)
        self.stock.total_value=self.cash+value+self.stock.frozen_cash
    def corporate(self):
        pending=[]
        for pay,amount in self.receivables:
            if pay<=self.date:self.cash+=amount
            else:pending.append((pay,amount))
        self.receivables=pending
        for s,p in list(self.holdings.items()):
            row=self.day.get(s);act=self.actions.get((s,self.date))
            if act:
                old=p['qty'];amount=old*act['cash']
                if act['pay']<=self.date:self.cash+=amount
                else:self.receivables.append((act['pay'],amount))
                # FIFO tax liability follows original acquisition date, including bonus shares.
                # One-year-exempt lots acquire no new liability. Stock dividend par is CNY1.
                additions=[];remaining=int(math.floor(old*act['stock']+1e-8))
                for j,lot in enumerate(list(p['lots'])):
                    bonus=min(remaining,int(math.floor(lot['q']*act['stock']+1e-8)))
                    if j==len(p['lots'])-1:bonus=remaining
                    remaining-=bonus
                    taxable=(act['cash']+act['taxable_stock']) if self.date<=lot['buy']+pd.DateOffset(years=1) else 0.
                    liability=lot['div']+taxable
                    adjusted=liability*lot['q']/(lot['q']+bonus)
                    lot['div']=adjusted
                    if bonus:additions.append(dict(q=bonus,buy=lot['buy'],release=act['release'],div=adjusted))
                p['lots'].extend(additions);p['lots'].sort(key=lambda l:(l['buy'],l['release']))
                p['qty']=sum(l['q'] for l in p['lots'])
                if row is not None:p['last']=row.preclose
                if row is not None and abs(row.preclose-(row.prev_actual-act['cash'])/(1+act['stock']))>max(.025,row.preclose*.0001):
                    self.reference_diffs[s+'/'+str(self.date.date())]=[row.prev_actual,row.preclose,act]
            if row is not None and np.isfinite(row.adjust_ratio) and abs(row.adjust_ratio-1)>1e-5 and not act:
                self.issues[s+'/'+str(self.date.date())]=float(row.adjust_ratio)
            out=self.meta.get(s)
            if out is not None and self.date>=out:
                self.issues[s+'/'+str(self.date.date())]='delisting zero-recovery assumption'
                del self.holdings[s]
    def order(self,s,qty,price=None):
        row=self.day.get(s);b=self.bars.get(s)
        if row is None or row.tradestatus!=1 or row.volume<=0:return None
        # Daily capacity is only a proxy for R08's unavailable 09:31-minute volume.
        cap=int(row.volume*(.05 if self.model=='R08' else .25)*self.capacity_scale/100)*100
        if abs(qty)>cap:self.capacity_hits+=1;return None
        if qty>0 and b.open>=b.high_limit-.000001:return None
        if qty<0 and b.open<=b.low_limit+.000001:return None
        if price is None:price=row.open*(1+(.002 if qty>0 else -.002))
        # Conservative slippage, constrained to historical traded range / order limit.
        price=min(max(price,row.low),row.high)
        price=min(max(price,b.low_limit),b.high_limit)
        price=round(float(price),2)
        value=round(abs(qty)*price,2)
        commission=round(max(5,value*.0003),2)
        transfer=round(value*(.00002 if self.date<pd.Timestamp('2022-04-29') else .00001),2)
        stamp=round(value*(.001 if self.date<pd.Timestamp('2023-08-28') else .0005),2) if qty<0 else 0.
        fees=commission+transfer+stamp;divtax=0.
        if qty>0:
            if value+fees>self.cash+1e-6:return None
            assert qty%100==0
            self.cash-=value+fees
            p=self.holdings.setdefault(s,dict(qty=0,last=price,lots=[]));p['qty']+=qty
            p['lots'].append(dict(q=qty,buy=self.date,release=self.date+pd.Timedelta(days=1),div=0.))
        else:
            assert s in self.holdings and -qty<=self.available(s)
            p=self.holdings[s];remaining=-qty
            for lot in p['lots']:
                if lot['release']>self.date or lot['buy']>=self.date:continue
                q=min(remaining,lot['q']);remaining-=q;lot['q']-=q
                rate=.2 if self.date<=lot['buy']+pd.DateOffset(months=1) else (.1 if self.date<=lot['buy']+pd.DateOffset(years=1) else 0.)
                divtax+=q*lot['div']*rate
                if remaining==0:break
            assert remaining==0
            divtax=round(divtax,2);p['lots']=[l for l in p['lots'] if l['q']];p['qty']+=qty
            self.cash+=value-fees-divtax
            if not p['qty']:del self.holdings[s]
        self.fees+=fees;self.tax+=divtax
        self.trades.append(dict(model=self.model,start=self.start,date=self.date,symbol=s,qty=qty,price=price,commission=commission,transfer=transfer,stamp=stamp,dividend_tax=divtax))
        self.sync();return len(self.trades)
    def step(self,date,index,prev,ranks):
        self.date=date;self.day=self.days[date];m=self.m;g=m.g
        self.corporate();self.bars={}
        needed=set(self.holdings)|set(ranks.get(str(prev.date()),[]))
        if self.model=='D11':needed.update(g.alpha_targets)
        for s in needed:
            row=self.day.get(s)
            if row is None:continue
            pct=.05 if row.isST and date<pd.Timestamp('2026-07-06') else .1
            high=math.floor(row.preclose*(1+pct)*100+.5)/100;low=math.floor(row.preclose*(1-pct)*100+.5)/100
            self.bars[s]=NS(open=row.open,high_limit=high,low_limit=low,is_paused=row.tradestatus!=1,is_st=bool(row.isST),volume=row.volume)
        self.sync()
        if self.model=='R08':
            due=m.rebalance_due(date,g.last_month);g.last_month=date.year*100+date.month
            g.pending_date=date.date() if due else None;g.ranked=ranks.get(str(prev.date())) if due else None
            m.handle_bar(self.context,self.bars)
        else:
            for s,old in g.alpha_close_shares.items():
                now=self.holdings.get(s,{}).get('qty',0)
                if old>0 and now>0 and old!=now and s in g.alpha_targets:g.alpha_targets[s]=int(math.floor(g.alpha_targets[s]*now/old+1e-8))
            g.alpha_index=index;g.alpha_ready=True;g.alpha_last_data=str(prev.date())
            g.alpha_rebalance_due=m._weekly_rebalance_due(date,prev,g.alpha_first)
            if g.alpha_rebalance_due:g.alpha_ranks=ranks[str(prev.date())]
            g.alpha_info={s:dict(volume20=self.days[prev][s].volume20,previous_st=bool(self.days[prev][s].isST)) for s in needed if s in self.days[prev]}
            m._handle_bar(self.context,self.bars);m._after_trading(self.context)
        marketvalue=0.
        for s,p in self.holdings.items():
            row=self.day.get(s)
            if row is not None and row.close>0:p['last']=float(row.close)
            marketvalue+=p['qty']*p['last']
            assert p['qty']==sum(l['q'] for l in p['lots'])
        assert self.cash>=-.01,self.cash
        equity=self.cash+marketvalue+sum(a for d,a in self.receivables)
        self.curve.append(dict(model=self.model,start=self.start,date=date,equity=equity,cash=self.cash,market_value=marketvalue,exposure=marketvalue/equity))

def run():
    dates=benchmark().index;starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]
    actions=action_map();rankings=read('rankings.json');panel=pd.read_parquet(HERE/'candidate_daily.parquet')
    days={d:{} for d in dates}
    for row in panel.itertuples(index=False):
        if row.date in days:days[row.date][row.symbol]=row
    meta=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv');outs={r.symbol:pd.Timestamp(r.outDate) for r in meta.itertuples() if pd.notna(r.outDate)}
    results=[];curves=[];trades=[];issues={};ref={}
    for model in FILES:
        for j,start in enumerate(starts):
            a=Account(model,start,actions,days,outs)
            for i in range(dates.get_loc(start),len(dates)):a.step(dates[i],i,dates[i-1],rankings[model])
            x=pd.DataFrame(a.curve);nav=x.equity.to_numpy();peaks=np.maximum.accumulate(np.r_[100000,nav])[1:]
            results.append(dict(model=model,start=start,end=END,final_equity=nav[-1],total_return=nav[-1]/100000-1,
                cagr=(nav[-1]/100000)**(365.25/((END-start).days+1))-1,max_drawdown=float(np.min(nav/peaks-1)),
                trades=len(a.trades),fees=a.fees,dividend_tax=a.tax,final_cash=a.cash,final_market_value=x.market_value.iloc[-1],
                avg_exposure=x.exposure.mean(),capacity_rejections=a.capacity_hits,unresolved_actions=len(a.issues)))
            curves.extend(a.curve);trades.extend(a.trades);issues.update(a.issues);ref.update(a.reference_diffs)
            print('RUN',model,j+1,'/',len(starts),'END',round(nav[-1],2),'ISSUES',len(a.issues),flush=True)
        pd.DataFrame(results).to_csv(HERE/'start_results.csv',index=False,encoding='utf-8-sig')
        pd.DataFrame(curves).to_parquet(HERE/'daily_equity.parquet',index=False);pd.DataFrame(trades).to_parquet(HERE/'trades.parquet',index=False)
        dump('unresolved_actions.json',issues);dump('reference_differences.json',ref)


if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='actions':fetch_actions(int(sys.argv[2]),int(sys.argv[3]))
    elif sys.argv[1]=='run':run()
