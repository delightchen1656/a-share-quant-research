"""Same-start price-index comparisons for the completed58-account replay."""
from pathlib import Path
import json
import hashlib
import pandas as pd
import numpy as np

OUT=Path(__file__).resolve().parents[1]/'results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    annual=read(OUT/'annual_by_start.json');accounts=read(OUT/'all_starts.json')
    calendar=pd.DatetimeIndex(pd.read_parquet(OUT/'runtime_inputs/calendar.parquet').date)
    indexes={}
    for key,code in [('hs300','sh.000300'),('sse','sh.000001')]:
        d=pd.DataFrame(read(OUT/'benchmark_inputs'/(code+'.json'))['rows']);d.date=pd.to_datetime(d.date)
        assert not d.date.duplicated().any()
        for col in ['open','close']:d[col]=pd.to_numeric(d[col],errors='raise');assert d[col].gt(0).all()
        indexes[key]=d.set_index('date').sort_index()
    annual_rows=[];whole=[]
    for account in accounts:
        start=account['actual_start'];end=pd.Timestamp(account['end']);start_date=pd.Timestamp(start)
        full=dict(start=start,strategy_cagr=account['cagr'])
        for key,d in indexes.items():
            expected=calendar[(calendar>=start_date)&(calendar<=end)]
            assert expected.equals(d.loc[start_date:end].index),(key,start)
            # Keep the historical reporting convention: first-day index
            # close to final close. Store open-entry sensitivity separately.
            first=float(d.loc[start_date,'close']);last=float(d.loc[end,'close']);years=((end-start_date).days+1)/365.25
            full[key+'_cagr']=(last/first)**(1/years)-1
            full['excess_vs_'+key+'_cagr_pp']=account['cagr']-full[key+'_cagr']
            full[key+'_open_entry_cagr']=(last/float(d.loc[start_date,'open']))**(1/years)-1
        whole.append(full)
    for record in annual:
        start=pd.Timestamp(record['start']);year=record['year'];end=pd.Timestamp(record['period_end'])
        row=dict(record)
        for key,d in indexes.items():
            if year==start.year:base=float(d.loc[start,'close'])
            else:base=float(d.loc[d.index<pd.Timestamp(year=year,month=1,day=1),'close'].iloc[-1])
            total=float(d.loc[end,'close'])/base-1
            row[key+'_period_return']=total
            row['excess_vs_'+key+'_pp']=record['period_return']-total
        annual_rows.append(row)
    df=pd.DataFrame(annual_rows);summary=[]
    for year,g in df.groupby('year'):
        assert len(g)==58
        r=dict(year=int(year),strategy_return=float(g.period_return.mean()))
        for key in indexes:
            r[key+'_return']=float(g[key+'_period_return'].mean())
            r['excess_vs_'+key+'_pp']=float(g['excess_vs_'+key+'_pp'].mean())
            r['outperform_'+key+'_accounts']=int((g['excess_vs_'+key+'_pp']>0).sum())
        summary.append(r)
    full=pd.DataFrame(whole)
    full_summary={k:float(full[k].mean()) for k in full if k!='start'}
    answer=dict(convention='2019 index return starts at each actual entry-day close; later years use prior-year final close. Price indexes without dividends/fees. Excess is percentage-point subtraction, not wealth-ratio alpha.',annual=summary,whole_period_mean=full_summary)
    for name,value in [('annual_index_by_start.json',annual_rows),('full_index_by_start.json',whole),('INDEX_COMPARISON.json',answer)]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for r in summary:
        rows.append('<tr><td>'+str(r['year'])+'</td>'+''.join('<td>'+format(r[k],'+.2%' if k.startswith('excess') else '.2%')+'</td>' for k in ['strategy_return','hs300_return','excess_vs_hs300_pp','sse_return','excess_vs_sse_pp'])+'</tr>')
    page='<meta charset="utf-8"><title>沪深1逐年指数超额</title><style>body{font:16px sans-serif;margin:32px}td,th{padding:9px;border:1px solid #ccc}table{border-collapse:collapse}</style><h1>沪深1：2019Q1全起点逐年指数超额</h1><p>58个10万元独立起点，单边0.5%理想化保证成交，止于2026-10-29。2019为各自起点至年末，2026为年初至10月29日。指数为BaoStock沪深300/上证价格指数；首年以各自入场日收盘为基准，此后以上年末收盘为基准。策略已扣费，指数不含股息和交易费用。超额为直接收益差，单位百分点，非财富比率或回归Alpha。</p><table><tr><th>年</th><th>策略</th><th>沪深300</th><th>超额百分点</th><th>上证</th><th>超额百分点</th></tr>'+''.join(rows)+'</table><p>全期平均年化：策略'+format(full_summary['strategy_cagr'],'.2%')+'；沪深300'+format(full_summary['hs300_cagr'],'.2%')+'；上证'+format(full_summary['sse_cagr'],'.2%')+'。相对沪深300年化超额'+format(full_summary['excess_vs_hs300_cagr_pp']*100,'+.2f')+'个百分点，相对上证'+format(full_summary['excess_vs_sse_cagr_pp']*100,'+.2f')+'个百分点。</p>'
    (OUT/'index_comparison.html').write_text(page,encoding='utf-8')
    print(json.dumps(answer,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
