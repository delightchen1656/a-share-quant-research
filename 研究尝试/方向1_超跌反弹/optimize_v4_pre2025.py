"""One predeclared factor/account experiment; never reads posterior paths.

Parent context is exposed: logical file guarding is NOT clean context isolation.
"""
import itertools,json,sys,types,hashlib
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
OUT=HERE/'experiments/v4_pre2025'
WORK=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())

def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    reads=set();denied=[]
    allowed={HERE/x for x in ['engine.py','reproduce.py','RULE.json','structure.py','results/development/RESULT.json']}
    def guard(event,args):
        if event!='open' or isinstance(args[0],int):return
        p=Path(args[0]).resolve()
        if not p.is_relative_to(WORK):return
        if 'holdout_restricted' in p.parts:
            denied.append(str(p));raise PermissionError('Posterior access forbidden')
        write=bool(args[1] and any(x in str(args[1]) for x in 'wax+')) or bool(args[2]&3)
        if write:
            if not p.is_relative_to(OUT):raise PermissionError('Write outside current experiment')
        elif p.is_relative_to(OUT) or p.is_relative_to(HERE/'inputs_pre2025') or p.is_relative_to(WORK/'quant_env') or p in allowed:
            reads.add(str(p.relative_to(WORK)))
        else:raise PermissionError('Input outside whitelist: '+str(p))
    sys.addaudithook(guard)
    import reproduce
    protocol=dict(boundary='2024-12-31',selection_period='2021-01-01/2023-12-31',check_period='2024',
        untouched_current_rule=True,context_isolation_claimed=False,posterior_read_allowed=False,
        scope='Frozen v3 820-signal cohort; same historical eligibility and four fixed special exclusions.',
        objective='Prefer all training annual returns >= baseline, training DD <= baseline+0.2pp, >=10 closed trades per year; then highest worst-year return, total return, lower DD.',
        minimum_factor_signal_retention=.65,top_factor_candidates=3,
        account_grid=dict(slots=[4,5,6],forced_day=[2,3,4],take_profit=[.06,.08,.10],stop_loss=[None,.08]),
        validation='Freeze one candidate from training only, then evaluate 2024 and full development exactly once; do not use 2024 to reselect.',
        limitation='All development years were explored previously; neither split is a fresh untouched holdout. Signal cohort has historical maturity selection. Parent has seen posterior.')
    dump(OUT/'PROTOCOL.json',protocol)
    d,dates,pos,quotes,factors,actions,pending=reproduce.prepare('development')
    assert d.date.max()<='2024-12-31'
    manifest=reproduce.read(HERE/'inputs_pre2025/MANIFEST.json')
    lookup={(x['code'],x['mode']):x for x in manifest['files']}
    features=[]
    for code,g in d.groupby('code'):
        frames=[]
        for mode in ['raw','qfq']:
            x=lookup[(code,mode)];p=HERE/x['path'];assert sha(p)==x['sha256']
            z=pd.read_parquet(p).sort_values('date');z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');frames.append(z)
        r,q=frames;valid=(pd.to_numeric(r.tradestatus)==1)&r.volume.gt(0)&r.open.gt(0)
        r=r.loc[valid].reset_index(drop=True);q=q.loc[valid].reset_index(drop=True);c=q.close
        span=(r.high-r.low).replace(0,np.nan)
        f=pd.DataFrame(dict(date=r.date,price=r.close,body=(r.close-r.open)/span,upper=(r.high-r.close)/span,
            volume=r.volume/r.volume.shift().rolling(20).mean(),volatility=c.pct_change().rolling(20).std(),
            deviation=c/c.rolling(20).mean()-1,position=(c-c.rolling(120,min_periods=60).min())/(c.rolling(120,min_periods=60).max()-c.rolling(120,min_periods=60).min()),
            ret5=c.shift()/c.shift(6)-1,ret20=c.shift()/c.shift(21)-1,signal_return=c/c.shift()-1))
        f['code']=code;features.append(f.loc[f.date.isin(g.date)])
    f=d[['code','date']].merge(pd.concat(features),on=['code','date'],validate='one_to_one')
    f.to_parquet(OUT/'asof_features.parquet',index=False)
    defs=[('base',{})]
    for field,op,values in [('price','le',[5,6,7]),('body','ge',[.55,.65,.75]),('upper','le',[.1,.2]),
        ('volume','le',[1,1.5,2]),('volume','ge',[.6,1,1.5]),('volatility','le',[.025,.035,.045]),
        ('deviation','le',[-.10,-.12]),('position','le',[.15,.3]),('ret5','ge',[-.15,-.2]),('signal_return','le',[.04,.06])]:
        for value in values:defs.append((f'{field}_{op}_{value}',{field:(op,value)}))
    def ids(spec):
        mask=pd.Series(True,index=f.index)
        for field,(op,value) in spec.items():mask &= f[field].le(value) if op=='le' else f[field].ge(value)
        return set(zip(f.loc[mask,'code'],f.loc[mask,'date']))
    train=d.loc[d.year.le(2023)].copy()
    source=(HERE/'engine.py').read_text(encoding='utf8')
    def module(end):
        src=source.replace("'2021-01-01'<=x<='2024-12-31'", "'2021-01-01'<=x<="+repr(end))
        # Mark remaining positions/receivables at each window boundary.
        src=src.replace("assert not hold and not payments, 'Unsettled holdings/receivables at research boundary'", "ending_open_pnl=sum(h['sale_net']+(h['available']+sum(x['qty'] for x in h['locked']))*h['last_price']+h['div_net']-h['cost'] for h in hold.values())")
        src=src.replace("assert abs(cash-capital-t.pnl.sum())<.01", "assert abs(float(f.equity.iloc[-1])-capital-t.pnl.sum()-ending_open_pnl)<.01")
        src=src.replace('final_equity=cash,total_return=cash/capital-1','final_equity=float(f.equity.iloc[-1]),total_return=float(f.equity.iloc[-1])/capital-1')
        days=(pd.Timestamp(end)-pd.Timestamp('2021-01-01')).days+1
        src=src.replace('(cash/capital)**(365.25/1461)',f'(float(f.equity.iloc[-1])/capital)**(365.25/{days})')
        m=types.ModuleType('training_engine');m.__file__=str(OUT/'training_engine.py');exec(compile(src,m.__file__,'exec'),m.__dict__)
        return m,src
    engine,src=module('2023-12-31');(OUT/'training_engine.py').write_text(src,encoding='utf8')
    baseconfig=dict(slots=5,forced_day=3,take_profit=.08,stop_loss=None)
    cache={};rows=[]
    def evaluate(name,spec,config):
        chosen=ids(spec);selected=train.loc[[(r.code,r.date) in chosen for r in train.itertuples()]]
        key=(tuple(sorted(chosen)),tuple(config.values()))
        if key in cache:return cache[key]
        row=dict(name=name,spec=spec,config=config,retention=len(selected)/len(train))
        if row['retention']<.65:return None
        try:
            result=engine.run(train,{'sample':chosen},dates,pos,quotes,factors,actions,'sample',True,100000,persist=False,quiet=True,**config)
            if result['specials']:raise ValueError('New delayed-exit candidate; no adaptive sample cleaning allowed')
            row['result']=result;row['worst_year']=min(x['return_pct'] for x in result['yearly'])
            row['eligible']=all(result['yearly_trades'].get(y,0)>=10 for y in range(2021,2024)) and result['summary']['max_drawdown']>=-.12 and row['worst_year']>0
        except (ValueError,AssertionError) as e:row.update(error=str(e),eligible=False)
        cache[key]=row;rows.append(row)
        if len(rows)%25==0:print('TRAINING trials',len(rows),flush=True)
        return row
    baseline=evaluate('base',{},baseconfig)
    def score(row):
        if not row or not row.get('eligible'):return (-1,-1,-1,-1)
        result=row['result'];b=baseline['result']
        dominant=all(y['return_pct']>=z['return_pct']-1e-10 for y,z in zip(result['yearly'],b['yearly'])) and result['summary']['max_drawdown']>=b['summary']['max_drawdown']-.002
        return (int(dominant),row['worst_year'],result['summary']['total_return'],result['summary']['max_drawdown'])
    factorscored=[evaluate(name,spec,baseconfig) for name,spec in defs]
    leaders=sorted([x for x in factorscored if x and x.get('eligible')],key=score,reverse=True)[:4]
    for a,b in itertools.combinations(leaders,2):
        if set(a['spec'])&set(b['spec']):continue
        spec={**a['spec'],**b['spec']}
        factorscored.append(evaluate(a['name']+' & '+b['name'],spec,baseconfig))
    top=sorted([x for x in factorscored if x and x.get('eligible')],key=score,reverse=True)[:3]
    configs=[dict(zip(protocol['account_grid'],v)) for v in itertools.product(*protocol['account_grid'].values())]
    for a in top:
        for config in configs:evaluate(a['name'],a['spec'],config)
    winner=max([x for x in rows if x.get('eligible')],key=score)
    # Local perturbations in account parameters were all computed using training only.
    near=[]
    for field,values in protocol['account_grid'].items():
        value=winner['config'][field];i=values.index(value)
        for j in [i-1,i+1]:
            if 0<=j<len(values):
                c=dict(winner['config']);c[field]=values[j]
                row=evaluate(winner['name'],winner['spec'],c)
                if row and row.get('eligible'):near.append(row['worst_year'])
    frozen=dict(name=winner['name'],spec=winner['spec'],config=winner['config'],selected_from='2021-2023 only',rule_base_sha256=sha(HERE/'RULE.json'),context_isolation_claimed=False,
        neighborhood=dict(valid=len(near),median_worst_year=float(np.median(near)) if near else None),training_result=winner['result'])
    dump(OUT/'FROZEN_CANDIDATE.json',frozen)
    dump(OUT/'TRAINING_TRIALS.json',rows)
    # No selection after this point. One candidate and the baseline only.
    engine,src=module('2024-12-31');(OUT/'full_engine.py').write_text(src,encoding='utf8')
    full={}
    for name,spec,config in [('v3',{},baseconfig),('v4_candidate',winner['spec'],winner['config'])]:
        directory=OUT/name;directory.mkdir();engine.OUT=directory
        full[name]=engine.run(d,{'sample':ids(spec)},dates,pos,quotes,factors,actions,'sample',True,100000,quiet=True,**config)
        assert not full[name]['specials']
    gold=json.loads((HERE/'results/development/RESULT.json').read_text(encoding='utf8'))
    assert abs(full['v3']['summary']['final_equity']-gold['summary']['final_equity'])<.01
    result=dict(candidate=frozen,training_trials=len(rows),full_development=full,
        validation_2024_pass=full['v4_candidate']['yearly'][-1]['return_pct']>=full['v3']['yearly'][-1]['return_pct'] and full['v4_candidate']['yearly'][-1]['max_drawdown']>=full['v3']['yearly'][-1]['max_drawdown'],
        current_v3_replaced=False,post2024_files_read=False,context_isolation_claimed=False)
    dump(OUT/'RESULT.json',result)
    dump(OUT/'INPUT_ACCESS_AUDIT.json',dict(workspace_reads=sorted(reads),denied_reads=denied,logical_guard_only=True))
    print('FINAL',json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
