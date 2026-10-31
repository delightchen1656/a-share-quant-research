import pathlib,json,hashlib,pandas as pd,numpy as np
ROOT=pathlib.Path('研究尝试/方向1_超跌反弹'); OUT=ROOT/'execution_rules_research_2020_2024'; BASE=ROOT/'inputs_pre2025/full_mainboard'
m=json.loads((BASE/'MANIFEST.json').read_text(encoding='utf-8-sig')); hashes={x['path']:x['sha256'] for x in m['files']}
def read(name):
 p=BASE/name;assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[name],name
 d=pd.read_parquet(p);assert str(d.date.max())[:10]<='2024-12-31' if 'date' in d else True
 return d
s=pd.read_csv(ROOT/'inputs_pre2025/execution_rules_2020_2024/SIGNALS.csv',dtype={'code':str});s.code=s.code.str.zfill(6)
cal=pd.to_datetime(read('calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist(); ix={d:i for i,d in enumerate(cal)}
data={}; rows=[]
for code,ss in s.groupby('code'):
 raw=read('raw/'+code+'.parquet');q=read('qfq/'+code+'.parquet')
 for df in [raw,q]:df['date']=pd.to_datetime(df.date).dt.strftime('%Y-%m-%d')
 raw=raw.set_index('date');q=q.set_index('date');raw=raw.apply(lambda c:pd.to_numeric(c,errors='coerce') if c.name in ['open','high','low','close','preclose','volume','amount','tradestatus','isST'] else c)
 q=q.apply(lambda c:pd.to_numeric(c,errors='coerce') if c.name in ['open','high','low','close'] else c)
 data[code]=(raw,q)
 for _,z in ss.iterrows():
  d=str(z.entry_date);j=ix.get(d);sig=str(z.signal_date)
  if j is None or d not in q.index:rows.append({'code':code,'signal_date':sig,'entry_date':d,'state':'missing_entry'});continue
  p=q.loc[d,'open']; path=q.reindex(cal[j:j+21]); future=path.iloc[1:]
  rows.append({'code':code,'signal_date':sig,'entry_date':d,'state':z.next_state,'year':int(d[:4]),'gap_from_signal':p/q.loc[sig,'close']-1,'peak20':path.high.max()/p-1,'trough20':path.low.min()/p-1,'close20':path.close.iloc[-1]/p-1 if len(path)==21 else np.nan,'tp20_touch':bool(future.high.max()>=p*1.2),'peak_giveback':(path.high.max()-path.close.iloc[-1])/p,'amount20':raw.loc[:sig].amount.tail(20).mean(),'ret20':z.ret20})
import pickle
with open(OUT/'verified_cache.pkl','wb') as f:pickle.dump((s,cal,data,pd.DataFrame(rows)),f)
r=pd.DataFrame(rows);r.to_csv(OUT/'event_price_diagnostics.csv',index=False)
summary={'signals':len(s),'stocks':len(data),'entry_states':s.next_state.value_counts().to_dict(),'per_year':{str(y):{'n':len(g),'median_peak20':g.peak20.median(),'touch20_rate':g.tp20_touch.mean(),'mean_close20':g.close20.mean(),'median_giveback':g.peak_giveback.median(),'p10_close20':g.close20.quantile(.1)}for y,g in r.dropna(subset=['year']).groupby('year')},'max_same_day_signals':int(s.groupby('entry_date').size().max()),'signal_days':int(s.entry_date.nunique())}
(OUT/'price_diagnostics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
