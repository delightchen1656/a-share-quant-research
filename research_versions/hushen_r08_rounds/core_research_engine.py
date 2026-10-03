"""Fresh strategy research. Strategy-free execution reused, signals rebuilt."""
import hashlib,itertools,json,sys,inspect
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
LEGACY=ROOT/'baselines/mainboard_baseline_2'
sys.path.insert(0,str(LEGACY))
import execution as e
from supermind_performance import measure

END=pd.Timestamp('2026-09-11')
FEATURES=HERE/'features_historical.parquet'
MIN_SIGNAL_VOL=.004
MIN_AMOUNT20=50e6
FEATURE_START='2020-01-02'
ROUND_NAME='round01_historical'
FAMILIES=('defensive','reversal','pullback','trend','liquidity','barbell','lowvol_reversal','turn_contraction')
CONFIGS=[dict(id='F%02d'%(i+1),family=family,size=size,interval=interval,count=8,buffer=16,exposure=.9,power=.5,minimum=1500)
    for i,(family,size,interval) in enumerate(itertools.product(FAMILIES,('all','small','mid'),(20,40)))]

def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def derive_prices(close):
    r=close.pct_change(fill_method=None)
    return pd.DataFrame(dict(ret5=close/close.shift(5)-1,ret20=close/close.shift(20)-1,
        mom=close.shift(20)/close.shift(120)-1,vol60=r.rolling(60).std(),
        vol_ratio=r.rolling(10).std()/r.rolling(60).std()),index=close.index)

def build_features():
    if FEATURES.exists():return pd.read_parquet(FEATURES)
    universe_path=e.DATA/'metadata/historical_mainboard_universe.csv'
    universe=pd.read_csv(universe_path)
    universe=universe[universe.symbol.map(e.is_ordinary_mainboard_a)].copy()
    cal=pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(e.DATA/'indices/000905.SH.parquet').date)).sort_values()
    next_session=pd.Series(cal[1:].to_numpy(),index=cal[:-1])
    parts=[];sources=[];missing=[]
    for i,item in enumerate(universe.to_dict('records')):
        symbol=item['symbol']
        path=e.qfq_path(symbol);rawpath=e.raw_path(symbol)
        if not path.exists() or not rawpath.exists():missing.append(symbol);continue
        q=pd.read_parquet(path,columns=['date','close']).sort_values('date');q['date']=pd.to_datetime(q.date)
        assert not q.date.duplicated().any()
        close=q.set_index('date').close.astype(float)
        extra=derive_prices(close)
        raw=pd.read_parquet(rawpath,columns=['date','amount','turn','volume','close','isST','tradestatus']).sort_values('date');raw['date']=pd.to_datetime(raw.date)
        assert not raw.date.duplicated().any()
        raw=raw.set_index('date')
        turn=pd.to_numeric(raw.turn,errors='coerce')
        amount=pd.to_numeric(raw.amount,errors='coerce')
        ret=close.pct_change(fill_method=None)
        extra['turn_ratio']=turn.rolling(5).mean()/turn.rolling(60).mean()
        extra['amihud']=ret.abs().div(amount.where(amount>0)).rolling(20).mean()
        extra['amount20']=amount.rolling(20).mean()
        extra['turn20']=turn.rolling(20).mean()
        extra['float_cap_proxy']=pd.to_numeric(raw.volume,errors='coerce').div(turn.where(turn>0)/100)*pd.to_numeric(raw.close,errors='coerce')
        extra['near_high']=close/close.rolling(120).max()
        extra['downside']=np.minimum(ret,0).pow(2).rolling(20).mean().pow(.5).clip(lower=.002)
        vol20=ret.rolling(20).std()
        eligible=(pd.Series(np.arange(len(close))+1,index=close.index)>=250)&vol20.between(MIN_SIGNAL_VOL,.08)&(extra.amount20>=MIN_AMOUNT20)
        eligible=eligible&(pd.to_numeric(raw.isST,errors='coerce').reindex(close.index)==0)&(pd.to_numeric(raw.tradestatus,errors='coerce').reindex(close.index)==1)
        extra['signal_date']=extra.index
        extra['execute_date']=next_session.reindex(extra.index).to_numpy()
        extra['symbol']=symbol
        if pd.notna(item['outDate']):eligible=eligible&(extra.signal_date<pd.Timestamp(item['outDate']))
        extra=extra[eligible & extra.execute_date.between(FEATURE_START,END)]
        parts.append(extra.reset_index(drop=True))
        sources.append(dict(symbol=symbol,qfq_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),raw_sha256=hashlib.sha256(rawpath.read_bytes()).hexdigest()))
        if i%500==0:print('FEATURES',i,flush=True)
    f=pd.concat(parts,ignore_index=True).replace([np.inf,-np.inf],np.nan)
    percentile=f.groupby('execute_date').float_cap_proxy.rank(pct=True)
    f['float_cap_proxy_group']=np.minimum(np.floor(percentile*3),2).fillna(-1).astype(int)
    assert (f.signal_date<f.execute_date).all()
    assert not f.duplicated(['execute_date','symbol']).any()
    f.to_parquet(FEATURES,index=False)
    save(FEATURES.with_name(FEATURES.stem+'_manifest.json'),dict(sources=sources,rows=len(f),dates=f.execute_date.nunique(),missing_files=missing,min_vol20=MIN_SIGNAL_VOL,min_amount20=MIN_AMOUNT20,
        universe_sha256=hashlib.sha256(universe_path.read_bytes()).hexdigest(),historical_universe=len(universe),
        delisted_universe=int(universe.outDate.notna().sum()),delisted_eligible=int(universe[universe.outDate.notna()].symbol.isin(f.symbol).sum()),
        feature_sha256=hashlib.sha256(FEATURES.read_bytes()).hexdigest(),limits='Rebuilt historical universe including known delistings;250bars,nonST,signaldaytradable,amount20>=configured min_amount20,vol20range. No dividend signal; provider coverage and corporate action limitations remain. Terminal delistings conservatively zero-valued,not assumed realizable liquidation.'))
    return f

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    if cfg['size']!='all':q=q[q.float_cap_proxy_group=={'small':0,'mid':1,'large':2}[cfg['size']]].copy()
    q=q.dropna(subset=['ret5','ret20','mom','vol60','vol_ratio','turn_ratio','turn20','float_cap_proxy','amihud'])
    h=lambda c:q[c].rank(pct=True)
    lowvol=1-h('vol60');lowturn=1-h('turn20');small=1-h('float_cap_proxy')
    family=cfg['family']
    if family=='defensive':score=.5*lowvol+.3*lowturn+.2*small
    elif family=='reversal':score=.45*(1-h('ret20'))+.35*(1-h('ret5'))+.2*lowvol
    elif family=='pullback':score=.35*h('mom')+.4*(1-h('ret5'))+.25*lowvol
    elif family=='trend':score=.5*h('mom')+.3*h('near_high')+.2*lowvol
    elif family=='liquidity':score=.4*lowturn+.3*small+.3*(1-h('amihud'))
    elif family=='barbell':score=.35*h('mom')+.35*(1-h('ret20'))+.3*lowvol
    elif family=='lowvol_reversal':score=.6*lowvol+.25*(1-h('ret5'))+.15*lowturn
    elif family=='turn_contraction':score=.4*(1-h('turn_ratio'))+.3*h('mom')+.3*lowvol
    else:raise ValueError(family)
    q['score']=score
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def exposure(curve):
    x=(curve.stock_value/curve.equity).clip(0,1);run=best=0
    for b in x<.1:run=run+1 if b else 0;best=max(best,run)
    return dict(mean_exposure=float(x.mean()),low_days=int((x<.5).sum()),flat_streak=best)

def summarize(rows):
    return dict(count=len(rows),annual_median=float(np.median([x['annualized'] for x in rows])),
        annual_p10=float(np.quantile([x['annualized'] for x in rows],.1)),
        sharpe_median=float(np.median([x['sharpe'] for x in rows])),worst_dd=min(x['drawdown'] for x in rows),
        min_exposure=min(x['mean_exposure'] for x in rows),max_flat_streak=max(x['flat_streak'] for x in rows),
        joint_pass_fraction=float(np.mean([x['annualized']>.12 and x['sharpe']>1 and x['mean_exposure']>.5 for x in rows])),
        positive_fraction=float(np.mean([x['total_return']>0 for x in rows])))

class Study:
    def __init__(self,configs,features=None):
        self.configs=configs
        index=pd.read_parquet(e.DATA/'indices/000905.SH.parquet').sort_values('date')
        self.cal=pd.DatetimeIndex(pd.to_datetime(index.date));self.days=self.cal[(self.cal>='2020-01-02')&(self.cal<=END)]
        e.CALENDAR=self.cal;e.INITIAL_CASH=100000.;e.STRICT_TARGET=True;e.SELECTOR=None
        universe=pd.read_csv(e.DATA/'metadata/historical_mainboard_universe.csv')
        e.DELISTINGS={x['symbol']:pd.Timestamp(x['outDate']) for x in universe.to_dict('records') if pd.notna(x['outDate'])}
        self.dev=[self.cal[self.cal.searchsorted(pd.Timestamp(year=y,month=m,day=1))] for y in (2020,2021) for m in (1,4,7,10)]
        f=build_features() if features is None else features
        self.ranks={};union=set()
        cache=HERE/'rank_cache';cache.mkdir(exist_ok=True)
        fingerprint=hashlib.sha256(FEATURES.read_bytes()).hexdigest()[:16]+'_'+hashlib.sha256(inspect.getsource(rank).encode()).hexdigest()[:12]
        for family,size in sorted(set((c['family'],c['size']) for c in configs)):
            cfg=next(c for c in configs if c['family']==family and c['size']==size)
            cfg=dict(cfg,buffer=max(c['buffer'] for c in configs))
            rankfile=cache/('%s_%s_%s_%d.parquet'%(fingerprint,family,size,cfg['buffer']))
            rr={}
            if rankfile.exists():
                cached=pd.read_parquet(rankfile)
                rr={date:frame[['symbol','downside']].copy() for date,frame in cached.groupby('execute_date',sort=False)}
            else:
                for date,frame in f.groupby('execute_date'):
                    rr[date]=rank(frame,cfg)
                pd.concat([q.assign(execute_date=date) for date,q in rr.items()],ignore_index=True).to_parquet(rankfile,index=False)
            for q in rr.values():
                assert len(q)>=max(c['count'] for c in configs)
                union.update(q.symbol)
            self.ranks[(family,size)]=rr
            print('RANK',family,size,len(union),flush=True)
        self.panel=e.load_daily_panel(union)
        e.PREPARED={pd.Timestamp(d):x.set_index('symbol') for d,x in self.panel.groupby('date')}
        ledger=json.loads((LEGACY/'monthly_A_alignment_20260924/action_ledger/manifest.json').read_text(encoding='utf-8'))
        e.ACTION_LEDGER={}
        for item in ledger['results']:
            for row in item['rows']:
                d=pd.Timestamp(row['dividOperateDate']);num=lambda k:float(row.get(k) or 0)
                e.ACTION_LEDGER[(d,item['symbol'])]=dict(cash=num('dividCashPsBeforeTax'),bonus=num('dividStocksPs')+num('dividReserveToStockPs'),pay_date=pd.Timestamp(row.get('dividPayDate') or d),stock_date=pd.Timestamp(row.get('dividStockMarketDate') or d+pd.Timedelta(days=1)))
        self.cost=(e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION)

    def run(self,cfg,start,end=None,stress=False):
        end=min(END,start+pd.DateOffset(months=24)-pd.Timedelta(days=1)) if end is None else end
        e.START=start;e.END=end;e.ACTION_MODE='ledger';e.ROUND_FEES=True
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.DELISTING_EVENTS=[]
        e.SLIPPAGE,e.COMMISSION,e.MIN_COMMISSION=[x*(2 if stress else 1) for x in self.cost]
        dates=self.cal[(self.cal>=start)&(self.cal<=end)][::cfg['interval']]
        ranks={d:self.ranks[(cfg['family'],cfg['size'])][d].copy() for d in dates}
        for q in ranks.values():q['downside']=q.downside.pow(cfg['power'])
        curve,trades=e.simulate(ranks,.05,cfg['count'],cfg['buffer'],cfg['exposure'],1.5,self.panel,min_adjustment=cfg['minimum'])
        assert curve.cash.min()>=-.01
        assert (trades[trades.side=='BUY'].quantity%100==0).all()
        assert trades[trades.side=='BUY'].merge(trades[trades.side=='SELL'],on=['date','symbol']).empty
        assert all(len(z['selected'])<=cfg['count'] for z in e.SELECTION_TRACE)
        z=dict(**measure(curve,risk_free_annual=.02),**exposure(curve),start=str(start.date()),end=str(curve.date.iloc[-1].date()),
            fees=float((trades.commission+trades.stamp_tax).sum()),orders=len(trades),unresolved_actions=len(e.UNRESOLVED_ACTIONS),delisting_writeoffs=len(e.DELISTING_EVENTS))
        return z,curve,trades

def main():
    out=HERE/ROUND_NAME;out.mkdir(exist_ok=True)
    assert not (out/'summary.json').exists(),'Preserve completed round'
    save(out/'protocol.json',dict(configs=CONFIGS,min_vol20=MIN_SIGNAL_VOL,feature_path=str(FEATURES),protocol=(HERE/'PROTOCOL.md').read_text(encoding='utf-8'),code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    study=Study(CONFIGS);rows=[];dev={}
    for cfg in CONFIGS:
        batch=[]
        for start in study.dev:
            z,_,_=study.run(cfg,start);z.update(id=cfg['id'],split='dev');rows.append(z);batch.append(z)
        dev[cfg['id']]=summarize(batch)
        save(out/'windows.json',rows);save(out/'development.json',dev)
        print('DEV',cfg['id'],json.dumps(dev[cfg['id']]),flush=True)
    eligible=[c for c in CONFIGS if dev[c['id']]['annual_median']>.12 and dev[c['id']]['sharpe_median']>.85 and dev[c['id']]['annual_p10']>0 and dev[c['id']]['worst_dd']>=-.35 and dev[c['id']]['min_exposure']>.5 and dev[c['id']]['max_flat_streak']<=5]
    winners=sorted(eligible,key=lambda c:dev[c['id']]['sharpe_median'],reverse=True)[:3]
    save(out/'frozen_winners.json',winners)
    full={}
    for cfg in winners:
        z,curve,trades=study.run(cfg,study.dev[0],END);full[cfg['id']]=z
        save(out/(cfg['id']+'_curve.json'),json.loads(curve.to_json(orient='records',date_format='iso')))
        save(out/(cfg['id']+'_trades.json'),json.loads(trades.to_json(orient='records',date_format='iso')))
    result=dict(configs=CONFIGS,development=dev,winners=winners,full=full,windows=len(rows),feature_path=str(FEATURES),goal_achieved=False,validation_pending=bool(winners))
    save(out/'summary.json',result);print('DONE',json.dumps(result),flush=True)

if __name__=='__main__':main()
