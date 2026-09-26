"""Run platform pure factor functions on local inputs, without platform APIs."""
import ast,json
import numpy as np
import pandas as pd
import group_research as g

def main():
    path=g.HERE/'supermind_mainboard_baseline_2_monthly_A.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    names={'_features','_dividend_quality','_group_features','_rank01','_rank_candidates'}
    constants={'MIN_LISTING_BARS','MIN_VOL20','MAX_VOL20','MIN_AMOUNT20'}
    nodes=[n for n in tree.body if (isinstance(n,ast.FunctionDef) and n.name in names) or (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets))]
    scope=dict(np=np,pd=pd);exec(compile(ast.Module(body=nodes,type_ignores=[]),'platform-pure-functions','exec'),scope)
    cache=pd.read_parquet(g.HERE/'cadence_multiround_100k/exact_date_factors.parquet')
    signals=json.loads((g.HERE/'monthly_A_alignment_20260924/platform_signals.json').read_text(encoding='utf-8'))
    selected=[s for s in signals if s['date'] in ('2020-01-02','2024-01-02','2026-09-01')]
    rows=[]
    for signal in selected:
        f=cache[cache.execute_date==pd.Timestamp(signal['date'])].set_index('symbol')
        symbols=sorted(set(signal['selected'])|set(f.index[::max(1,len(f)//15)]))
        for symbol in symbols:
            if symbol not in f.index:continue
            item=f.loc[symbol];date=item.signal_date
            q=pd.read_parquet(g.bt.qfq_path(symbol));q['date']=pd.to_datetime(q.date)
            r=pd.read_parquet(g.bt.raw_path(symbol));r['date']=pd.to_datetime(r.date)
            q=q[(q.date<=date)&q.tradestatus.astype(str).eq('1')].set_index('date').tail(751).rename(columns={'amount':'turnover','isST':'is_st'})
            rt=r[(r.date<=date)&r.tradestatus.astype(str).eq('1')].set_index('date').tail(751)
            raw=r[r.date<=date].set_index('date').tail(20).rename(columns={'turn':'turnover_rate'})
            direct=scope['_features'](q,rt)
            if direct is None:raise AssertionError(('Eligibility mismatch',symbol,date))
            group=scope['_group_features'](raw)
            if group:direct.update(group)
            errors={k:abs(float(v)-float(item[k])) for k,v in direct.items() if k in item}
            rows.append(dict(date=str(date.date()),symbol=symbol,errors=errors))
    maxima={k:max(r['errors'].get(k,0) for r in rows) for r in rows for k in r['errors']}
    result=dict(checks=len(rows),max_absolute_errors=maxima,rows=rows,note='Identical local inputs only; does not prove platform input-data equality.')
    (g.HERE/'monthly_A_alignment_20260924/factor_formula_checks.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))

if __name__=='__main__':main()
