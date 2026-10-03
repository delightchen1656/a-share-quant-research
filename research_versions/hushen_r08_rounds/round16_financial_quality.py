"""Exploratory conservative-lag annual financial quality, historical 98-stock pool.

Current-vintage source is NOT proven original-vintage PIT. Any candidate passing
numeric gates still requires source filing verification before goal completion.
"""
import hashlib,itertools,json
import numpy as np
import pandas as pd
import research as r
from round09_affordability import Study
from round15_historical_dividend import FEATURES as BASE

DIRECTORY=r.HERE/'public_sources/historical_financials'
FEATURES=r.HERE/'features_financial_quality.parquet'
FIELDS={'fin_roe':'ROEJQ','fin_margin':'XSJLL','fin_growth':'PARENTNETPROFITTZ'}
CONFIGS=[dict(id='Q%02d'%(i+1),family=family,size='all',cadence=cadence,
    interval=20 if cadence=='monthly' else 40,count=count,buffer=2*count,
    exposure=.85,power=0,minimum=1500,affordable=True)
    for i,(family,cadence,count) in enumerate(itertools.product(
        ('roe_lowvol','quality_trend','profit_growth','cash_quality'),('monthly','bimonthly'),(8,12)))]

def available_annual(rows):
    f=pd.DataFrame(rows)
    if f.empty:return f
    for col in ('REPORT_DATE','NOTICE_DATE','UPDATE_DATE'):
        f[col]=pd.to_datetime(f[col],errors='coerce')
    f=f.dropna(subset=['REPORT_DATE','NOTICE_DATE','UPDATE_DATE']).copy()
    f=f[(f.REPORT_DATE.dt.month==12)&(f.REPORT_DATE.dt.day==31)]
    f['available']=f[['NOTICE_DATE','UPDATE_DATE']].max(axis=1)
    f=f[f.available>f.REPORT_DATE].sort_values(['REPORT_DATE','available'])
    for name,col in FIELDS.items():f[name]=pd.to_numeric(f[col],errors='coerce').clip(-100,100)
    eps=pd.to_numeric(f.EPSJB,errors='coerce')
    f['fin_cash']=pd.to_numeric(f.MGJYXJJE,errors='coerce').div(eps.where(eps>0)).clip(-5,5)
    return f.replace([np.inf,-np.inf],np.nan)

def point_in_time(rows,dates):
    f=available_annual(rows);result=[]
    for date in dates:
        row=dict(fin_available=pd.NaT,fin_report=pd.NaT,fin_roe=np.nan,
            fin_margin=np.nan,fin_growth=np.nan,fin_cash=np.nan)
        if not f.empty:
            q=f[(f.available<date)&(f.REPORT_DATE>=date-pd.Timedelta(days=900))]
            if not q.empty:
                last=q.iloc[-1]
                row.update({name:last[name] for name in (*FIELDS,'fin_cash')})
                row.update(fin_available=last.available,fin_report=last.REPORT_DATE)
        result.append(row)
    return pd.DataFrame(result,index=dates)

def build():
    if FEATURES.exists():return
    summary=json.loads((DIRECTORY/'download_summary.json').read_text(encoding='utf-8'))
    assert not summary['missing'],'Do not silently drop unavailable symbols'
    f=pd.read_parquet(BASE);parts=[]
    for symbol,group in f.groupby('symbol'):
        raw=json.loads((DIRECTORY/(symbol+'.json')).read_text(encoding='utf-8'))
        rows=(raw.get('result') or {}).get('data') or []
        z=point_in_time(rows,pd.DatetimeIndex(group.signal_date));z.index=group.index
        parts.append(z)
    f=f.join(pd.concat(parts))
    known=f.fin_available.notna()
    assert (f.loc[known,'fin_available']<f.loc[known,'signal_date']).all()
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),known_fraction=float(known.mean()),
        missing_neutral='rank=0.5, never remove whole stock based on missing financial history',
        date_policy='annual only; strictly earlier than signalday max(NOTICE_DATE,UPDATE_DATE); report age<=900days; latest report_date then latest available; no backfill',
        vintage_warning='Current-vintage historical database, conservative update lag, not verified original PIT; passing candidates require original filing verification',
        sources=summary['downloaded'],implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest()))

def rank(frame,cfg):
    q=frame.sort_values('symbol').copy()
    h=lambda c:q[c].rank(pct=True).fillna(.5)
    low=1-h('vol60');roe=h('fin_roe');margin=h('fin_margin');growth=h('fin_growth');cash=h('fin_cash')
    if cfg['family']=='roe_lowvol':score=.6*roe+.4*low
    elif cfg['family']=='quality_trend':score=.4*roe+.3*h('long_risk')+.3*low
    elif cfg['family']=='profit_growth':score=.4*roe+.3*growth+.3*low
    elif cfg['family']=='cash_quality':score=.3*roe+.3*cash+.2*margin+.2*low
    else:raise ValueError(cfg)
    q['score']=score
    return q.sort_values(['score','symbol'],ascending=[False,True]).head(cfg['buffer'])[['symbol','downside']]

def install():
    r.FEATURES=FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round16_financial_quality';r.Study=Study

if __name__=='__main__':
    build();install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='16 predeclared conservative-lag financial quality configs; historical98stocks; unchanged execution; missing factors neutral not deleted',
            source_vintage_verification_required=True,
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
