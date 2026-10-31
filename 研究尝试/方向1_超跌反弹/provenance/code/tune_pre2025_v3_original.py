"""Pre2025-only continuation of previously documented grid-boundary research.

Parent chat already contains posterior facts: this is NOT clean isolated research.
The calculation process denies all holdout_restricted paths and pins inputs.
"""
import itertools
import json
import shutil
import sys
from pathlib import Path
import pandas as pd
from study import ROOT,SOURCE,digest
import account_backtest as engine

OUT=ROOT/'results_v16_pre2025_local'
GRID=dict(price=[8,10,12],deviation=[.06,.07,.08,.09,.10],take_profit=[.05,.06,.07,.08],
          forced_day=[2,3,4],slots=[5,6,7,8,9,10],stop_loss=[None,.05,.08])


class InputGuard:
    def __init__(self):
        self.workspace=ROOT.parent.resolve();self.out=OUT.resolve();self.reads=set();self.parquet_reads=set();self.denied=[]
        self.allowed_dirs=[SOURCE.resolve(),(ROOT/'results_v4_decline_first').resolve(),
            (ROOT/'results_v5_long_position').resolve(),(ROOT/'results_v8_precision40').resolve(),
            (ROOT/'results_v15_fixed_tuning').resolve(),(ROOT/'results_v9_accounts/action_responses').resolve(),
            (self.workspace/'quant_env').resolve()]
        self.allowed_files={(ROOT/'results_v9_accounts/corporate_action_records.json').resolve()}
    def check(self,path,write=False):
        if isinstance(path,int):return
        if isinstance(path,bytes):path=path.decode()
        p=Path(path).resolve()
        if not p.is_relative_to(self.workspace):return
        if 'holdout_restricted' in p.parts:
            self.denied.append(str(p));raise PermissionError('Posterior/restricted input forbidden')
        if write:
            if not p.is_relative_to(self.out):raise PermissionError('Writes allowed only in this run output')
            return
        if p.is_relative_to(self.out):return
        if p in self.allowed_files or any(p.is_relative_to(a) for a in self.allowed_dirs) or (p.parent==ROOT and p.suffix=='.py'):
            self.reads.add(str(p.relative_to(self.workspace)));return
        self.denied.append(str(p));raise PermissionError('Workspace input not on explicit whitelist')
    def hook(self,event,args):
        if event=='open':
            mode=args[1];flags=args[2]
            write=bool(mode and any(x in str(mode) for x in ['w','a','x','+'])) or bool(flags & 0x1 or flags & 0x2)
            self.check(args[0],write=write)
    def install(self):
        original=pd.read_parquet
        def guarded(path,*args,**kwargs):
            self.check(path);self.parquet_reads.add(str(Path(path).resolve().relative_to(self.workspace)))
            return original(path,*args,**kwargs)
        pd.read_parquet=guarded;sys.addaudithook(self.hook)


def key(c):return tuple(c[k] for k in GRID)


def main():
    OUT.mkdir(exist_ok=True);guard=InputGuard();guard.install()
    # Test rejection before any file operation; no posterior file is opened.
    try:guard.check(ROOT/'holdout_restricted/__forbidden_probe__.json')
    except PermissionError:pass
    else:raise AssertionError('Restricted-path rejection failed')
    guard.denied.clear()
    baseline_path=ROOT/'results_v15_fixed_tuning/summary.json'
    old=json.loads(baseline_path.read_text(encoding='utf8'));baseline_original=old['persisted_result']
    frozen=json.loads((ROOT/'results_v15_fixed_tuning/FROZEN_RULE.json').read_text(encoding='utf8'))
    for name,expected in frozen['hashes'].items():
        assert digest(ROOT.parent/name)==expected,name
    protocol=dict(grid=GRID,combinations=3240,capital=100000,cutoff='2024-12-31',
        rationale='Extend deviation8%/TP6% grid boundaries documented in pre-posterior v15 explanation; refine slots around7. No posterior outcomes used to set values/objective.',
        selection='Same v15 goal: all4 annual returns positive, >=10 entries/year, DD<=12%; prefer all4 annual returns>=v2 and DD<=v2, then balanced dominance. Stable local neighborhood preferred; maximize worst year then total then lower DD.',
        limitation='Parent context has seen posterior; this cannot be called clean isolated research. Calculation denies restricted paths, but cannot remove context exposure. All2021-2024 are previously explored development.',
        baseline_summary_sha256=digest(baseline_path),engine_sha256=digest(ROOT/'account_backtest.py'))
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    # Localize only audited pre2025 action evidence; do not touch previous results.
    shutil.copyfile(ROOT/'results_v9_accounts/corporate_action_records.json',OUT/'corporate_action_records.json')
    action_dir=OUT/'action_responses';action_dir.mkdir(exist_ok=True)
    source_actions=ROOT/'results_v9_accounts/action_responses'
    manifest=json.loads((source_actions/'manifest.json').read_text(encoding='utf8'))
    for filename,info in manifest.items():
        assert int(info['key'].split('/')[-1])<=2024
        assert digest(source_actions/filename)==info['sha256']
        shutil.copyfile(source_actions/filename,action_dir/filename)
    shutil.copyfile(source_actions/'manifest.json',action_dir/'manifest.json')
    engine.OUT=OUT;inputs=list(engine.prepare());base=inputs[0].copy()
    f=pd.read_parquet(ROOT/'results_v5_long_position/events.parquet')
    assert f.date.max()<='2024-12-31' and base.date.max()<='2024-12-31'
    ids={}
    for price,dev in itertools.product(GRID['price'],GRID['deviation']):
        a=f.loc[(f.raw_signal_close<price)&(f.below_ma20<=-dev)];ids[(price,dev)]=set(zip(a.code,a.date))
    excluded={tuple(x) for x in old['excluded_specials']};configs=[dict(zip(GRID,v)) for v in itertools.product(*GRID.values())];rows=[];iterations=[]
    for attempt in range(6):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy();new=set();n=0
        for i,c in enumerate(configs):
            selected=ids[(c['price'],c['deviation'])]
            if attempt and not selected&last_new:continue
            inputs[1]={'sample':selected,'leaders':selected}
            r=engine.run(*inputs,'sample',True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'],persist=False,quiet=True)
            annual=[y['return_pct'] for y in r['yearly']]
            good=all(x>0 for x in annual) and -r['summary']['max_drawdown']<=.12 and all(r['yearly_trades'].get(y,0)>=10 for y in range(2021,2025))
            row=dict(config=c,result=r,worst_year=min(annual),qualified=good)
            if attempt:rows[i]=row
            else:rows.append(row)
            n+=1
            for e in r['specials']:new.add((e['code'],e['signal_date']))
            if (i+1)%150==0:print('progress',attempt,i+1,'/',len(configs),flush=True)
        iterations.append(dict(attempt=attempt,excluded=sorted(excluded),new=sorted(new),evaluated=n))
        if not new:break
        last_new=new.copy();excluded.update(new)
    else:raise RuntimeError('Special-case cleanup did not converge')
    # Re-run v2 with exactly the same cleanup. This is fairness, not hindsight fitting.
    inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
    sub=f.loc[(f.raw_signal_close<10)&(f.below_ma20<=-.08)];selected=set(zip(sub.code,sub.date));inputs[1]={'sample':selected,'leaders':selected}
    baseline_dir=OUT/'baseline_common';baseline_dir.mkdir(exist_ok=True);engine.OUT=baseline_dir
    baseline=engine.run(*inputs,'sample',True,100000,7,forced_day=3,take_profit=.06,quiet=True)
    assert not baseline['specials']
    old_min=min(y['return_pct'] for y in baseline['yearly']);old_dd=-baseline['summary']['max_drawdown'];old_total=baseline['summary']['total_return']
    lookup={key(x['config']):x for x in rows}
    for row in rows:
        r=row['result'];row['all_year_dominant']=row['qualified'] and -r['summary']['max_drawdown']<=old_dd+1e-9 and all(y['return_pct']>=b['return_pct']-1e-9 for y,b in zip(r['yearly'],baseline['yearly']))
        row['balanced_dominant']=row['qualified'] and row['worst_year']>=old_min-1e-9 and r['summary']['total_return']>=old_total-1e-9 and -r['summary']['max_drawdown']<=old_dd+1e-9
        neighbors=[];c=row['config']
        for field,values in GRID.items():
            j=values.index(c[field])
            for p in [j-1,j+1]:
                if 0<=p<len(values):
                    other=dict(c);other[field]=values[p];neighbors.append(lookup[key(other)])
        worsts=sorted(x['worst_year'] for x in neighbors);median=worsts[len(worsts)//2];positive=sum(x>0 for x in worsts)/len(worsts)
        row['neighborhood']=dict(n=len(neighbors),median_worst_year=median,positive_fraction=positive,
            min_worst_year=min(worsts),max_worst_year=max(worsts),stable=positive>=.75 and median>=.75*row['worst_year'])
    qualified=[x for x in rows if x['qualified']]
    tiers=[('all_year_dominant',[x for x in qualified if x['all_year_dominant']]),('balanced_dominant',[x for x in qualified if x['balanced_dominant']])]
    tier,pool=next(((name,g) for name,g in tiers if g),(None,[]))
    if not pool:
        winner=None;persisted=None
    else:
        stable=[x for x in pool if x['neighborhood']['stable']]
        winner=max(stable or pool,key=lambda x:(x['worst_year'],x['result']['summary']['total_return'],x['result']['summary']['max_drawdown']))
        c=winner['config'];selected=ids[(c['price'],c['deviation'])];inputs[1]={'sample':selected,'leaders':selected};engine.OUT=OUT
        persisted=engine.run(*inputs,'sample',True,100000,c['slots'],forced_day=c['forced_day'],take_profit=c['take_profit'],stop_loss=c['stop_loss'])
        assert abs(persisted['summary']['final_equity']-winner['result']['summary']['final_equity'])<.01 and not persisted['specials']
    (OUT/'comparison.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    result=dict(winner=winner,persisted_result=persisted,baseline=baseline,baseline_original=baseline_original,selected_tier=tier,
        candidates=len(configs),qualified=len(qualified),all_year_dominant=sum(x['all_year_dominant'] for x in rows),balanced_dominant=sum(x['balanced_dominant'] for x in rows),
        excluded_specials=sorted(excluded),cleanup=iterations,post2024_files_read=False,context_isolation_claimed=False,
        protocol_sha256=digest(OUT/'PROTOCOL.json'))
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    assert not guard.denied
    (OUT/'INPUT_ACCESS_AUDIT.json').write_text(json.dumps(dict(workspace_reads=sorted(guard.reads),parquet_reads=sorted(guard.parquet_reads),
        denied_actual_reads=guard.denied,restricted_probe_rejected=True,quote_boundary_assertions_passed=True,
        guard_limit='Logical Python audit guard plus explicit Parquet wrapper, not OS sandbox; parent context is not clean isolation.'),ensure_ascii=False,indent=2),encoding='utf8')
    print('FINAL',json.dumps(dict(config=None if winner is None else winner['config'],result=persisted,
        baseline_original_equity_difference=baseline['summary']['final_equity']-baseline_original['summary']['final_equity']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
