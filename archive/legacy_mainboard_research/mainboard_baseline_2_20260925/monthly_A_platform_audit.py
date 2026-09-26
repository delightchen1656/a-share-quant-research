"""Read-only source audit and immutable copy of monthly-A platform exports."""
import ast
import hashlib
import json
import shutil
from pathlib import Path
import re
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'monthly_A_alignment_20260924'
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'

def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def read_text(path):
    raw=path.read_bytes()
    for enc in ('utf-8-sig','gb18030'):
        try:return raw.decode(enc),enc
        except UnicodeDecodeError:pass
    raise ValueError('Cannot decode '+str(path))

def main():
    OUT.mkdir(exist_ok=True);archive=OUT/'source';archive.mkdir(exist_ok=True)
    manifest=[]
    for name in ('detal.csv','dailyposition.csv','outlog.txt'):
        source=ROOT/name;dest=archive/name
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if dest.exists():assert hashlib.sha256(dest.read_bytes()).hexdigest()==digest
        else:shutil.copy2(source,dest)
        manifest.append(dict(file=name,bytes=source.stat().st_size,sha256=digest))
    save('source_manifest.json',manifest)
    text,enc=read_text(archive/'outlog.txt')
    assert '月初A V1.0 initialized; count=6 exposure=80% risk_power=0.50' in text
    nav=[];signals=[]
    for line in text.splitlines():
        m=re.search(r'^(\d{4}-\d{2}-\d{2}).*BASELINE2_A nav=([\d.]+) cash=([\d.]+) holdings=(\d+)',line)
        if m:nav.append(dict(date=m[1],equity=float(m[2]),cash=float(m[3]),holdings=int(m[4])))
        m=re.search(r'^(\d{4}-\d{2}-\d{2}).*BASELINE2_A regime=(\w+) qfq=(\d+) raw=(\d+) eligible=(\d+) selected=(\[.*\])',line)
        if m:signals.append(dict(date=m[1],regime=m[2],qfq=int(m[3]),raw=int(m[4]),eligible=int(m[5]),selected=ast.literal_eval(m[6])))
    nav=pd.DataFrame(nav).sort_values('date');assert nav.date.is_unique
    _,enc=read_text(archive/'detal.csv');tr=pd.read_csv(archive/'detal.csv',encoding=enc)
    tr=tr.rename(columns=dict(zip(tr.columns,['date','time','symbol','name','side','display_price','quantity','amount','commission','stamp_tax'])))
    tr['source_row']=np.arange(len(tr))+2
    tr['side']=tr.side.map({'买入':'BUY','卖出':'SELL'});assert tr.side.notna().all()
    tr['quantity']=tr.quantity.abs();tr['amount']=tr.amount.abs();tr['effective_price']=tr.amount/tr.quantity
    tr['commission_expected']=np.maximum(5,tr.amount*.0003).round(2)
    tr['tax_expected']=np.where(tr.side=='SELL',(tr.amount*.001).round(2),0)
    tr=tr.sort_values(['date','source_row'])
    market=[]
    for symbol in tr.symbol.unique():
        p=DATA/'raw'/symbol[-2:]/(symbol+'.parquet')
        if not p.exists():continue
        x=pd.read_parquet(p);x['date']=pd.to_datetime(x.date).dt.strftime('%Y-%m-%d');x['symbol']=symbol
        market.append(x[['date','symbol','open','close','volume','preclose']])
    prices=pd.concat(market,ignore_index=True)
    matched=tr.merge(prices,on=['date','symbol'],how='left')
    matched['signed_gap']=(matched.effective_price/matched.open-1)*np.where(matched.side=='BUY',1,-1)
    matched['old_fill_gap']=matched.effective_price/(matched.open*np.where(matched.side=='BUY',1.002,.998))-1
    _,enc=read_text(archive/'dailyposition.csv');raw=pd.read_csv(archive/'dailyposition.csv',encoding=enc)
    raw.columns=['date','equity','cash','security','quantity','market_value','close','pnl']
    headers=raw[raw.date.notna()].copy();headers['date']=pd.to_datetime(headers.date).dt.strftime('%Y-%m-%d')
    raw['date']=raw.date.ffill();pos=raw[raw.security.notna()].copy()
    pos['symbol']=pos.security.str.extract(r'([0-9]{6}\.(?:SH|SZ))');assert pos.symbol.notna().all()
    pos['date']=pd.to_datetime(pos.date).dt.strftime('%Y-%m-%d')
    totals=pos.groupby('date').market_value.sum().rename('positions_value')
    reconciliation=headers.merge(totals,on='date',how='left').fillna({'positions_value':0})
    joined=headers.merge(nav,on='date',suffixes=('_export','_log'))
    pc=pos.merge(prices[['date','symbol','close']],on=['date','symbol'],how='left',suffixes=('_platform','_local'))
    common=nav[nav.date<='2026-09-11'].copy()
    eq=np.r_[100000,common.equity];rr=eq[1:]/eq[:-1]-1
    years=(pd.Timestamp(common.date.iloc[-1])-pd.Timestamp(common.date.iloc[0])).days/365.25
    summary=dict(version='monthly_A_V1.0',source_start=nav.date.min(),source_end=nav.date.max(),common_end=common.date.iloc[-1],
        common_final=float(eq[-1]),common_annual=float((eq[-1]/100000)**(1/years)-1),common_dd=float((eq/np.maximum.accumulate(eq)-1).min()),common_sharpe=float(np.sqrt(252)*rr.mean()/rr.std(ddof=1)),
        nav_rows=len(nav),trade_rows=len(tr),signal_rows=len(signals),times=tr.time.value_counts().to_dict(),
        commission_max_error=float((tr.commission-tr.commission_expected).abs().max()),tax_max_error=float((tr.stamp_tax-tr.tax_expected).abs().max()),
        accounting_max_error=float((reconciliation.equity-reconciliation.cash-reconciliation.positions_value).abs().max()),log_nav_max_error=float((joined.equity_export-joined.equity_log).abs().max()),
        close_prices_compared=int(pc.close_local.notna().sum()),close_price_max_error=float((pc.close_platform-pc.close_local).abs().max()),
        trade_prices_compared=int(matched.open.notna().sum()),signed_gap_quantiles=matched.signed_gap.quantile([0,.1,.5,.9,1]).to_dict(),
        early_signed_gap_median=float(matched.loc[matched.date<'2024-01-01','signed_gap'].median()),
        post_signed_gap_median=float(matched.loc[matched.date>='2024-01-01','signed_gap'].median()),
        first_signals=signals[:3],first_trades=tr.head(12).to_dict('records'))
    for name,frame in [('platform_nav.json',nav),('platform_trades.json',tr),('trade_price_comparison.json',matched),('platform_positions.json',pos)]:
        save(name,json.loads(frame.to_json(orient='records',force_ascii=False)))
    save('platform_signals.json',signals);save('audit_summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
