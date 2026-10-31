"""Local parameter sweep around fixed v1, explicitly development-selected.

No production changes, no post2024 data. Baseline/source/code hashes pinned.
"""
import itertools
import json
from pathlib import Path
import pandas as pd
from study import ROOT,SOURCE,digest
import account_backtest as engine

OUT=ROOT/'results_v15_fixed_tuning'
GRID=dict(price=[6,8,10,12],deviation=[.08,.10,.12,.15],take_profit=[.04,.05,.06],
          forced_day=[2,3,4,5],slots=[3,5,7,10,15],stop_loss=[None,.05,.08])


def config_key(c):return tuple(c[k] for k in GRID)


def main():
    OUT.mkdir(exist_ok=True)
    old_path=ROOT/'results_v14_fixed_income/summary.json'
    old=json.loads(old_path.read_text(encoding='utf8'));baseline=old['winner']['persisted_result']
    frozen=json.loads((ROOT/'results_v14_fixed_income/FROZEN_RULE.json').read_text(encoding='utf8'))
    assert digest(ROOT/'account_backtest.py')==frozen['hashes']['account_backtest.py'],'Frozen baseline engine changed'
    assert digest(SOURCE/'MANIFEST.json')==frozen['market_manifest_sha256']
    protocol=dict(grid=GRID,combinations=2880,capital=100000,pool='Existing basic sample, no leader restriction',
        selection='All years are development. >=10 entries every year, each year positive, daily DD<=12%. Prefer all4 annual returns>=v1 and DD<=v1; then min annual>=v1,total>=v1,DD<=v1; then remaining qualified. Maximize min annual then total then lower DD.',
        stability='Neighbors differ by one adjacent grid value. Report neighbor median worst-year return, positive-year fraction, DD range. Prefer >=75% all-year-positive neighbors with median worst-year>=75% of own when available.',
        caveat='Repeated optimization on already explored2021-2024. This is NOT independent validation and does not imply future performance. No2025+ inputs.',
        baseline_summary_sha256=digest(old_path),engine_sha256=digest(ROOT/'account_backtest.py'))
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    inputs=list(engine.prepare());base=inputs[0].copy()
    f=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet')
    idsets={}
    for price,dev in itertools.product(GRID['price'],GRID['deviation']):
        sub=f.loc[(f.raw_signal_close<price)&(f.below_ma20<=-dev)]
        idsets[(price,dev)]=set(zip(sub.code,sub.date))
    configs=[dict(zip(GRID,values)) for values in itertools.product(*GRID.values())]
    excluded={tuple(x) for x in old['excluded_specials']};rows=[];iterations=[]
    old_min=min(y['return_pct'] for y in baseline['yearly']);old_total=baseline['summary']['total_return'];old_dd=-baseline['summary']['max_drawdown']
    def evaluate(c):
        ids=idsets[(c['price'],c['deviation'])];inputs[1]={'sample':ids,'leaders':ids}
        r=engine.run(*inputs,'sample',True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'],persist=False,quiet=True)
        annual=[y['return_pct'] for y in r['yearly']];dd=-r['summary']['max_drawdown']
        n=r['yearly_trades'];positive=all(x>0 for x in annual)
        qualified=positive and dd<=.12 and all(n.get(y,0)>=10 for y in range(2021,2025))
        all_dominant=qualified and dd<=old_dd+1e-9 and all(y['return_pct']>=b['return_pct']-1e-9 for y,b in zip(r['yearly'],baseline['yearly']))
        robust_dominant=qualified and dd<=old_dd+1e-9 and min(annual)>=old_min-1e-9 and r['summary']['total_return']>=old_total-1e-9
        return dict(config=c,result=r,worst_year=min(annual),qualified=qualified,
                    all_year_dominant=all_dominant,balanced_dominant=robust_dominant)
    for attempt in range(6):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
        new=set();rerun=0
        for i,c in enumerate(configs):
            if attempt and not (idsets[(c['price'],c['deviation'])]&last_new):continue
            row=evaluate(c);rerun+=1
            if attempt:rows[i]=row
            else:rows.append(row)
            for e in row['result']['specials']:new.add((e['code'],e['signal_date']))
            if (i+1)%100==0:
                good=sum(x['qualified'] for x in rows)
                print('progress',attempt,i+1,'/',len(configs),'qualified',good,flush=True)
                (OUT/'progress.json').write_text(json.dumps(dict(attempt=attempt,completed=i+1,total=len(configs),qualified=good),indent=2),encoding='utf8')
        iterations.append(dict(attempt=attempt,excluded=sorted(excluded),new=sorted(new),evaluated=rerun))
        if not new:break
        last_new=new.copy();excluded.update(new)
    else:raise RuntimeError('Special-case cleanup did not converge')
    bykey={config_key(x['config']):x for x in rows}
    for row in rows:
        c=row['config'];neighbors=[]
        for field,values in GRID.items():
            j=values.index(c[field])
            for k in [j-1,j+1]:
                if 0<=k<len(values):
                    other=dict(c);other[field]=values[k];neighbors.append(bykey[config_key(other)])
        n=len(neighbors);med=sorted(x['worst_year'] for x in neighbors)[n//2]
        positive=sum(x['worst_year']>0 for x in neighbors)/n
        stable=positive>=.75 and med>=.75*row['worst_year']
        row['neighborhood']=dict(n=n,positive_year_fraction=positive,median_worst_year=med,
            min_worst_year=min(x['worst_year'] for x in neighbors),max_worst_year=max(x['worst_year'] for x in neighbors),stable=stable)
    qualified=[x for x in rows if x['qualified']]
    if not qualified:raise RuntimeError('No qualified candidate; baseline retained')
    tiers=[('all_year_dominant',[x for x in qualified if x['all_year_dominant']]),
           ('balanced_dominant',[x for x in qualified if x['balanced_dominant']]),('positive_with_dd12',qualified)]
    tier,chosen_pool=next((name,g) for name,g in tiers if g)
    stable=[x for x in chosen_pool if x['neighborhood']['stable']]
    winner=max(stable or chosen_pool,key=lambda x:(x['worst_year'],x['result']['summary']['total_return'],x['result']['summary']['max_drawdown']))
    (OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
    c=winner['config'];ids=idsets[(c['price'],c['deviation'])];inputs[1]={'sample':ids,'leaders':ids};engine.OUT=OUT
    persisted=engine.run(*inputs,'sample',True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'])
    assert abs(persisted['summary']['final_equity']-winner['result']['summary']['final_equity'])<.01
    assert persisted['summary']['delayed_exits']==0
    result=dict(winner=winner,persisted_result=persisted,selected_tier=tier,baseline=baseline,grid_count=len(configs),
        qualified=len(qualified),all_year_dominant=sum(x['all_year_dominant'] for x in rows),balanced_dominant=sum(x['balanced_dominant'] for x in rows),
        excluded_specials=sorted(excluded),cleanup=iterations,protocol_sha256=digest(OUT/'PROTOCOL.json'),research_only=True,
        source_rule_hash=digest(ROOT/'results_v14_fixed_income/FROZEN_RULE.json'))
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('FINAL',json.dumps(dict(config=c,summary=persisted['summary'],yearly=persisted['yearly'],tier=tier,neighborhood=winner['neighborhood']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
