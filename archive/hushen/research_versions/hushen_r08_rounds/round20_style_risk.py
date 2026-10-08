"""Risk trigger tied to historical carry style; reference basket is not account NAV."""
import hashlib,itertools
import pandas as pd
import research as r
import round19_daily_risk as base
import round08_long_momentum as signals

INDICES=r.HERE/'style_price_indices.parquet'
CONFIGS=[dict(id='Z%02d'%(i+1),family='carry_long',size='mid',cadence='bimonthly',interval=40,
    count=count,buffer=2*count,exposure=.85,power=0,minimum=1500,affordable=True,risk_mode=source+'_'+mode)
    for i,(source,mode,count) in enumerate(itertools.product(('style','blend'),('trend60','trend120'),(8,12)))]

def reference_prices(style,market):
    market=market.reindex(style.index)
    assert market.notna().all(),'No future or backward filling missing reference values'
    returns=.5*style.pct_change(fill_method=None)+.5*market.pct_change(fill_method=None)
    blend=(1+returns.fillna(0.)).cumprod()
    return {'style':style,'blend':blend}

class Study(base.Study):
    def __init__(self,configs,features=None):
        super().__init__(configs,features)
        f=pd.read_parquet(INDICES);style=f[f['style']=='carry_mid'].sort_values('date').set_index('date').index_value
        market=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
        references=reference_prices(style,market)
        self.risk={source+'_'+mode:base.exposures(series,mode) for source,series in references.items() for mode in ('trend60','trend120')}

def install():
    r.e=base.engine;r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round20_style_risk';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='8 predeclared:historical carry_mid12stock monthly reference or50/50daily-return mix withCSI500 x60/120MA +/-1%hysteresis x8/12;65/95%target,existing-stock proportional risk resize;regular bimonthly selection and fees unchanged',
            reference_warning='Reference price basket is gross,no execution costs/lot limits;signals lag1day. NOT realized account NAV.',
            reference_sha256=hashlib.sha256(INDICES.read_bytes()).hexdigest(),
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
