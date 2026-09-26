"""Broad group-conditioned research, point-in-time price/volume groups."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
import execution_engine as bt
HERE=Path(__file__).resolve().parent; OUT=HERE/'group_research_100k'
DIMENSIONS=['float_cap_proxy','turn20','vol60','amount20','ret60','price','dividend','downside']
METHODS=['reversal','trend','quality']

def features():
 p=OUT/'features.parquet'
 if p.exists():return pd.read_parquet(p)
 f=bt.build_factor_cache();parts=[]
 for i,(symbol,q) in enumerate(f.groupby('symbol'),1):
  raw=pd.read_parquet(bt.raw_path(symbol)); adj=pd.read_parquet(bt.qfq_path(symbol))
  for x in [raw,adj]:x['date']=pd.to_datetime(x.date);x.sort_values('date',inplace=True)
  raw=raw.drop_duplicates('date').set_index('date');adj=adj.drop_duplicates('date').set_index('date')
  for c in ['turn','volume','close']:raw[c]=pd.to_numeric(raw[c],errors='coerce')
  price=pd.to_numeric(adj.close,errors='coerce');ret=price.pct_change(fill_method=None)
  raw['turn20']=raw.turn.rolling(20).mean();raw['float_cap_proxy']=raw.volume.div(raw.turn.where(raw.turn>0)/100)*raw.close
  raw['vol60']=ret.rolling(60).std();raw['ret60']=price.pct_change(60,fill_method=None);raw['price']=raw.close
  extra=raw[['turn20','float_cap_proxy','vol60','ret60','price']].reindex(pd.DatetimeIndex(q.signal_date)).reset_index(drop=True)
  z=q.reset_index(drop=True);parts.append(pd.concat([z,extra],axis=1))
  if i%500==0:print('FEATURE',i,flush=True)
 f=pd.concat(parts,ignore_index=True)
 industry=pd.read_csv(bt.DATA/'metadata/current_industry_map.csv').drop_duplicates('symbol').set_index('symbol').industry
 f['industry']=f.symbol.map(industry).fillna('UNKNOWN');f['exchange']=f.symbol.str[-2:]
 for col in DIMENSIONS:
  rank=f.groupby('execute_date')[col].rank(pct=True)
  f[col+'_group']=np.minimum(np.floor(rank*3),2).fillna(-1).astype(int)
 f.to_parquet(p,index=False);return f

def score(q,method):
 q=q.copy()
 hi=lambda col:q[col].rank(pct=True)
 if method=='reversal':q['score']=.5*hi('below_high')+.25*hi('below_ma60')+.25*hi('dividend')
 elif method=='trend':q['score']=.5*hi('ret60')+.25*hi('near_high')+.25*(1-hi('vol60'))
 else:q['score']=.55*hi('dividend')+.3*(1-hi('downside'))+.15*(1-hi('turn20'))
 return q.dropna(subset=['score']).sort_values(['score','symbol'],ascending=[False,True])

def configs():
 rows=[]
 for dim in DIMENSIONS:
  for group in range(3):
   for method in METHODS:rows.append(dict(name=f'{dim}_g{group}_{method}',dim=dim,group=group,method=method,kind='single'))
 for a,b in [('float_cap_proxy','turn20'),('float_cap_proxy','vol60'),('turn20','vol60'),('ret60','vol60')]:
  for ga in range(3):
   for gb in range(3):rows.append(dict(name=f'{a}{ga}_{b}{gb}',dim=a,group=ga,other=b,other_group=gb,method='reversal',kind='cross'))
 for dim in DIMENSIONS:
  for method in METHODS:rows.append(dict(name=f'rotate_{dim}_{method}',dim=dim,method=method,kind='rotate'))
 for ex in ['SH','SZ']:
  for method in METHODS:rows.append(dict(name=f'{ex}_{method}',exchange=ex,method=method,kind='exchange'))
 return rows

def main():
 OUT.mkdir(exist_ok=True);bt.INITIAL_CASH=100000.;f=features();cs=configs()
 # Industry grouping is exploratory because classification is a current snapshot.
 for industry in sorted(f.industry.unique()):
  if industry=='UNKNOWN':continue
  if f[(f.signal_date<'2024-01-01')&(f.industry==industry)].groupby('execute_date').size().median()>=15:
   cs.append(dict(name='industry_'+industry,industry=industry,method='reversal',kind='industry'))
 (OUT/'protocol.json').write_text(json.dumps({'capital':100000,'count':10,'buffer':30,'exposure':.8,'cadence':'quarterly','min_adjustment':3000,'selection':'development 2020-2023 only; CAGR+.05Sharpe-.5abs(MDD), MDD<=35%; current-industry excluded from formal selection','dimensions':DIMENSIONS,'configurations':cs,'caveats':['float_cap_proxy inferred from volume/turnover; not total market cap','industry classification current snapshot only','historical periods already explored; not pristine OOS','same inherited cost and corporate-action approximations as baseline2']},ensure_ascii=False,indent=2),encoding='utf-8')
 days={d:q for d,q in f.groupby('execute_date') if d.month in [1,4,7,10]};allranks={};union=set()
 for cfg in cs:
  ranks={}
  for d,x in days.items():
   kind=cfg['kind'];q=x
   if kind in ['single','cross']:q=q[q[cfg['dim']+'_group']==cfg['group']]
   if kind=='cross':q=q[q[cfg['other']+'_group']==cfg['other_group']]
   if kind=='industry':q=q[q.industry==cfg['industry']]
   if kind=='exchange':q=q[q.exchange==cfg['exchange']]
   if kind=='rotate':
    # Group preference at each date uses only trailing momentum, not future PnL.
    gs=q[q[cfg['dim']+'_group']>=0].groupby(cfg['dim']+'_group').ret60.median()
    q=q[q[cfg['dim']+'_group']==gs.idxmax()] if len(gs) else q.iloc[:0]
   q=score(q,cfg['method'])
   if len(q)<10:q=q.iloc[:0]
   ranks[d]=q;union.update(q.head(30).symbol)
  allranks[cfg['name']]=ranks
 panel=bt.load_daily_panel(union);rows=[];best=None;best_score=-np.inf
 baseline=pd.read_csv(HERE/'small_account_100k/daily_equity.csv',parse_dates=['date']).set_index('date').equity.pct_change()
 for i,cfg in enumerate(cs,1):
  n=cfg['name'];print(f'RUN {i}/{len(cs)} {n}',flush=True)
  c,t=bt.simulate(allranks[n],.05,10,30,.8,1.5,panel,min_adjustment=3000)
  row=dict(cfg)
  for label,start,end in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   z=c[c.date.between(start,end)];prev=c[c.date<pd.Timestamp(start)]
   m=bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else 100000)
   for k in ['annualized_return','max_drawdown','sharpe','final_equity']:row[label+'_'+k]=m[k]
  row.update(orders=len(t),commission=float(t.commission.sum()) if len(t) else 0,average_holdings=c.holdings.mean(),coverage=np.mean([len(q)>=10 for q in allranks[n].values()]),correlation=c.set_index('date').equity.pct_change().corr(baseline))
  row['score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
  row['dev_coverage']=float(np.mean([len(q)>=10 for d,q in allranks[n].items() if d<pd.Timestamp('2024-01-01')]))
  row['eligible']=bool(cfg['kind']!='industry' and row['dev_max_drawdown']>=-.35 and row['dev_coverage']>=.8)
  rows.append(row)
  if row['eligible'] and row['score']>best_score:
   best_score=row['score'];best=row
   c.to_csv(OUT/'candidate_equity.csv',index=False,encoding='utf-8-sig');t.to_csv(OUT/'candidate_trades.csv',index=False,encoding='utf-8-sig')
   (OUT/'candidate.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
  pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
 result=pd.DataFrame(rows);result.sort_values('score',ascending=False).to_csv(OUT/'ranking.csv',index=False,encoding='utf-8-sig')
 lines=['# 10万元沪深分组研究','',f'共测试{len(cs)}条路线。所有分位组按每个信号日截面重算；交叉组内重新排名。市值为流通市值代理，行业使用当前分类，仅作探索。', '', '组间轮动按过去60日组内收益中位数选组，再进行组内选股。统一10只、80%仓位、季度调仓，3000元小额调整门槛。', '', '候选按2020—2023开发期评分选定；2024与2025后仅展示。全期排名不能作为新的选参依据。样本已反复研究，须用未来新增数据验证。', '', '|路线|开发年化|2024年化|2025后年化|全期年化|回撤|Sharpe|与原版相关性|','|---|---:|---:|---:|---:|---:|---:|---:|']
 for z in result[result.eligible].sort_values('score',ascending=False).head(15).itertuples():lines.append(f'|{z.name}|{z.dev_annualized_return:.2%}|{z.validation_annualized_return:.2%}|{z.observed_annualized_return:.2%}|{z.full_annualized_return:.2%}|{z.full_max_drawdown:.2%}|{z.full_sharpe:.3f}|{z.correlation:.3f}|')
 lines+=['','冻结候选：'+str(best),'','成本继承基准2：佣金万三最低5元、双边0.2%滑点、卖出固定0.1%税率用于比较；原始价格撮合与整数手限制。公司行动近似、初始股票池偏差、日成交量不代表开盘容量等限制继续存在。当前未覆盖可靠历史估值、盈利质量、机构持仓、历史行业变更和总市值；不以缺失数据拼造分组。']
 (OUT/'README.md').write_text('\n'.join(lines),encoding='utf-8');print('BEST',best,flush=True)

if __name__=='__main__':main()
