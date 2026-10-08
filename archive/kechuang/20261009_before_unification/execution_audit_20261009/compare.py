from pathlib import Path
import pandas as pd,json,csv
HERE=Path(__file__).resolve().parent
local=HERE.parent/'baseline_3_1_start_dates_500k_20261008/results/2026-01-01'
raw=HERE/'inputs/detal.csv'
if not raw.exists():raw=HERE.parents[2]/'detal.csv'
p=pd.read_csv(raw);p=p.rename(columns={'日期':'date','代码':'symbol','操作':'side','数量':'qty','金额':'amount','成交价':'price'})
p['side']=p.side.map({'买入':'BUY','卖出':'SELL'});p['qty']=p.qty.abs();p['date']=pd.to_datetime(p.date)
l=pd.read_parquet(local/'trades.parquet')
m=p.merge(l,on=['date','symbol','side'],how='outer',suffixes=('_platform','_local'),indicator=True)
m['date']=m.date.dt.strftime('%Y-%m-%d')
records=json.loads(m.to_json(orient='records',force_ascii=False))
out={'platform_only':int(sum(m._merge=='left_only')),'local_only':int(sum(m._merge=='right_only')),'matched_keys':int(sum(m._merge=='both')),'first_platform_trades':json.loads(p.sort_values('date').head(3).to_json(orient='records',date_format='iso',force_ascii=False)),'first_local_trades':json.loads(l.head(3).to_json(orient='records',date_format='iso')),'all_rows':records}
(HERE/'trade_comparison.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='all_rows'},ensure_ascii=True,indent=2))
