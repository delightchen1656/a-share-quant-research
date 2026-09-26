"""Platform accounting reconciliation, explicitly separate from strategy reproduction."""
import ast,hashlib,json,re,shutil
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'国金_prade_留档与分析'
OUT=HERE/'platform_runs/supermind_20200102_20260918_100k'

def metrics(x,start,end,initial):
 z=x[x.date.between(start,end)].sort_values('date');prev=x[x.date<pd.Timestamp(start)]
 opening=float(prev.equity.iloc[-1]) if len(prev) else initial
 values=np.r_[opening,z.equity.to_numpy()];ret=values[1:]/values[:-1]-1
 dd=values/np.maximum.accumulate(values)-1
 years=(z.date.iloc[-1]-z.date.iloc[0]).days/365.25
 return dict(start=str(z.date.iloc[0].date()),end=str(z.date.iloc[-1].date()),opening=opening,final=float(values[-1]),total_return=float(values[-1]/opening-1),annualized=float((values[-1]/opening)**(1/years)-1),max_drawdown=float(dd.min()),sharpe=float(np.sqrt(252)*ret.mean()/ret.std(ddof=1)))

def main():
 OUT.mkdir(parents=True,exist_ok=True);rawdir=OUT/'originals';rawdir.mkdir(exist_ok=True)
 for name in ['outlog.txt','detal.csv','dailyposition.csv']:
  src=SOURCE/name;dst=rawdir/name
  if dst.exists():assert dst.read_bytes()==src.read_bytes(),'Existing archive differs; do not overwrite'
  else:shutil.copy2(src,dst)
 t=pd.read_csv(rawdir/'detal.csv').rename(columns={'日期':'date','时间':'time','代码':'symbol','操作':'side','成交价':'display_price','数量':'quantity','金额':'amount','佣金':'commission','印花税':'stamp_tax'})
 t['date']=pd.to_datetime(t.date);t['side']=t.side.map({'买入':'BUY','卖出':'SELL'});assert t.side.notna().all()
 t.quantity=t.quantity.abs();t.amount=t.amount.abs();t['effective_price']=t.amount/t.quantity
 t=t.sort_values(['date','symbol','side']).reset_index(drop=True)
 assert not t.duplicated(['date','symbol','side']).any()
 t['cashflow']=np.where(t.side=='BUY',-t.amount,t.amount)-t.commission-t.stamp_tax
 p=pd.read_csv(rawdir/'dailyposition.csv');p.columns=p.columns.str.strip()
 p['date']=pd.to_datetime(p['日期'].ffill())
 eq=p[p['总资产'].notna()][['date','总资产','现金']].rename(columns={'总资产':'equity','现金':'cash'}).sort_values('date')
 h=p[p['证券'].notna()].copy();h['symbol']=h['证券'].str.extract(r'(\d{6}\.(?:SH|SZ))');assert h.symbol.notna().all()
 h=h.rename(columns={'数量':'quantity','持仓':'market_value','收盘价':'close'})[['date','symbol','quantity','market_value','close']].sort_values(['date','symbol'])
 assert not eq.date.duplicated().any() and not h.duplicated(['date','symbol']).any()
 log=(rawdir/'outlog.txt').read_text(encoding='utf-8-sig')
 logs=pd.DataFrame([dict(date=pd.Timestamp(d),equity=float(v),cash=float(c),holdings=int(n)) for d,v,c,n in re.findall(r'(\d{4}-\d{2}-\d{2}) 15:30:00INFOBASELINE2 nav=([\d.]+) cash=([\d.]+) holdings=(\d+)',log)])
 lm=eq.merge(logs,on='date',suffixes=('_csv','_log'))
 assert np.allclose(lm.equity_csv,lm.equity_log,atol=.011,rtol=0)
 qty=h.pivot(index='date',columns='symbol',values='quantity').reindex(eq.date).fillna(0)
 signed=t.assign(signed=np.where(t.side=='BUY',t.quantity,-t.quantity)).pivot_table(index='date',columns='symbol',values='signed',aggfunc='sum').reindex(index=qty.index,columns=qty.columns).fillna(0)
 extra=qty.diff().fillna(qty)-signed
 share_events=extra.stack();share_events=share_events[share_events.abs()>.001].rename('unexplained_share_change').reset_index()
 flow=t.groupby('date').cashflow.sum().reindex(eq.date,fill_value=0).to_numpy()
 eq['trade_cashflow']=flow
 eq['nontrade_cashflow']=eq.cash.diff().fillna(0)-eq.trade_cashflow
 eq['holdings_value']=eq.date.map(h.groupby('date').market_value.sum()).fillna(0)
 eq['accounting_gap']=eq.equity-eq.cash-eq.holdings_value
 assert eq.accounting_gap.abs().max()<.02
 # Replay is observed execution + identified non-trade cash residuals, NOT a fresh backtest.
 eq['replay_cash']=float(eq.cash.iloc[0])+(eq.trade_cashflow+eq.nontrade_cashflow).cumsum()
 eq['replay_equity']=eq.replay_cash+eq.holdings_value
 events=eq[(eq.nontrade_cashflow.abs()>.03)&(eq.date>'2019-12-31')][['date','nontrade_cashflow']].copy()
 events['classification']='unattributed_nontrade_cashflow_not_verified_dividend'
 local=pd.read_csv(HERE/'pending_1_snapshot/defensive_bear_8_equity.csv',parse_dates=['date'])
 lt=pd.read_csv(HERE/'pending_1_snapshot/defensive_bear_8_trades.csv',parse_dates=['date'])
 tm=t.merge(lt,on=['date','symbol','side'],how='outer',suffixes=('_platform','_local'),indicator=True)
 matched=tm[tm._merge=='both'];exact=matched[np.isclose(matched.quantity_platform,matched.quantity_local)]
 common=eq.merge(local,on='date',suffixes=('_platform','_local'))
 common['equity_gap']=common.equity_local-common.equity_platform
 # Compare platform-held security closes to local independent raw market data.
 priced=[]
 for s,q in h.groupby('symbol'):
  fp=ROOT/'sh_sz_market_research/data_pipeline/data/raw'/s[-2:]/(s+'.parquet')
  if not fp.exists():continue
  x=pd.read_parquet(fp,columns=['date','close','open']);x['date']=pd.to_datetime(x.date)
  priced.append(q.merge(x,on='date',suffixes=('_platform','_local')))
 price=pd.concat(priced,ignore_index=True);price['value_gap']=(price.close_local-price.close_platform)*price.quantity
 tradeprice=t.merge(price[['date','symbol','open']],on=['date','symbol'],how='left')
 tradeprice['implied_open']=tradeprice.effective_price/np.where(tradeprice.side=='BUY',1.002,.998)
 tradeprice['open_gap']=tradeprice.implied_open-tradeprice.open
 # Logged selected names are output evidence, not inputs to the independent strategy.
 selected=[]
 from group_round3 import prepare
 import group_research as g
 rr,_,states,_=prepare(g.features(),[dict(name='control',family='control',value=0)])
 for d,state,names in re.findall(r'(\d{4}-\d{2}-\d{2}) 09:00:00INFOBASELINE2 regime=(\w+).*?selected=(\[[^\n]+\])',log):
  day=pd.Timestamp(d);actual=ast.literal_eval(names);ranked=rr['control'].get(day)
  prior=lt[lt.date<day].copy(); prior['signed']=np.where(prior.side=='BUY',prior.quantity,-prior.quantity)
  # For screening compare to top24, not a guessed local retained-positions order.
  top24=ranked.head(24).symbol.tolist() if ranked is not None else []
  selected.append(dict(date=d,platform_regime=state,platform_selected=';'.join(actual),local_top24=';'.join(top24),platform_names_in_local_buffer=len(set(actual)&set(top24))))
 stages={}
 for label,a,b in [('dev','2020-01-02','2023-12-31'),('2024','2024-01-01','2024-12-31'),('2025plus','2025-01-01','2026-09-18'),('common_full','2020-01-02','2026-09-11'),('platform_full','2020-01-02','2026-09-18')]:stages[label]=metrics(eq,a,b,100000)
 summary=dict(platform_rows=len(t),local_rows=len(lt),matched_date_symbol_side=len(matched),matched_quantity=len(exact),platform_match_rate=len(matched)/len(t),quantity_match_rate=len(exact)/len(t),common_final_platform=float(common.equity_platform.iloc[-1]),common_final_local=float(common.equity_local.iloc[-1]),common_final_gap=float(common.equity_gap.iloc[-1]),max_accounting_gap=float(eq.accounting_gap.abs().max()),log_nav_max_gap=float((lm.equity_csv-lm.equity_log).abs().max()),unattributed_cash_events=len(events),unattributed_cash_total=float(events.nontrade_cashflow.sum()),share_change_events=len(share_events),local_vs_platform_close_nonmatching_rows=int(((price.close_local-price.close_platform).abs()>.005).sum()),price_rows=len(price),stages=stages,status='ACCOUNTING_RECONCILED_STRATEGY_NOT_REPRODUCED')
 for name,df in [('platform_trades',t),('platform_daily_equity',eq),('platform_holdings',h),('trade_alignment',tm),('equity_alignment',common),('cash_events_unattributed',events),('share_events_unattributed',share_events),('price_alignment',price),('trade_price_alignment',tradeprice),('selection_alignment',pd.DataFrame(selected))]:df.to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig')
 (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False,indent=2))
 print('FIRST_DIFFERENCES',tm[tm.date==tm.date.min()].to_string(index=False))
 print('PRICE',tradeprice[['date','symbol','effective_price','open','implied_open','open_gap']].head(8).to_string(index=False))
 shutil.copy2(HERE/'supermind_mainboard_baseline_2_pending1.py',OUT/'submitted_strategy_reference.py')
 shutil.copy2(HERE/'execution_engine.py',OUT/'local_engine_before_alignment.py')
 manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='sha256.json'}
 (OUT/'sha256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
