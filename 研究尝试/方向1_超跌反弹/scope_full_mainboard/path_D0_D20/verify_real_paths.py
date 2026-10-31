"""Independent adjusted-price formulas, summaries, source samples and flags.

Reads only this direction's outputs plus the specifically authorized input roots.
No account, classification, software or another direction's results.
"""
import hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd

P=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def good(x):return pd.notna(x) and np.isfinite(float(x)) and float(x)>0
def same(a,b,tol=2e-10):
    if pd.isna(a) or b is None or pd.isna(b):return pd.isna(a) and (b is None or pd.isna(b))
    return abs(float(a)-float(b))<=tol
def truth(x):return x is True or str(x).lower() in ['true','1','1.0']
cfg=read(P/'CONFIG.json');freeze=read(P/'RUN_FREEZE.json')
assert sha(P/'CONFIG.json')==freeze['config_sha256'] and sha(P/'path_engine.py')==freeze['engine_sha256']
assert sha(P.parent/'FULL_SIGNALS.csv')=='70ea8125a426c3d7a54aa39fcbe01e5bc1f71c6190e17fbd346bdf76b41843f7'
assert sha(Path(cfg['cohort']['path']))==cfg['cohort']['sha256']
wide=pd.read_csv(P/'all_event_paths.csv',dtype={'code':str,'signal_id':str,'event_id':str},low_memory=False)
source=pd.read_csv(cfg['cohort']['path'],dtype={'code':str,'signal_id':str})
assert len(wide)==3805 and set(wide.event_id)==set(source.signal_id) and wide.event_id.is_unique
wide['code']=wide.code.str.zfill(6)
price=Path(cfg['prices']['root']);pm=read(price/'MANIFEST.json');assert sha(price/'MANIFEST.json')==cfg['prices']['manifest_sha256']
listing={x['path']:x['sha256'] for x in pm['files']}
def whitelisted(relative,columns=None):
    path=(price/relative).resolve();assert price.resolve() in path.parents and sha(path)==listing[relative]
    if path.suffix=='.parquet':return pd.read_parquet(path,columns=columns)
    return read(path)
cal=whitelisted(pm['calendar'],['date']);calendar=pd.to_datetime(cal.date).dt.strftime('%Y-%m-%d').tolist();ordinal={day:i for i,day in enumerate(calendar)}
qm=whitelisted(pm['quote_manifest']);qlookup={(x['code'],x['mode']):x['path'] for x in qm['files']}
aa=read(P/'company_action_audit.json');by_event={}
for record in aa['records']:by_event.setdefault(record['event_id'],[]).append(record)
errors=[];checked=0;unexplained_checked=0;action_blocker_checked=0;noanchor=0
def check(condition,event,h,field):
    global checked
    checked+=1
    if not condition:errors.append(dict(event_id=event,h=h,field=field))
for row in wide.to_dict('records'):
    eid=row['event_id'];entry=pd.to_datetime(row['entry_date']).strftime('%Y-%m-%d');signal=pd.to_datetime(row['signal_date']).strftime('%Y-%m-%d')
    start=ordinal[signal]+1;anchor=truth(row['anchor_valid']);noanchor+=not anchor
    check(entry==calendar[start],eid,-1,'strict_entry_date')
    rp=row['entry_raw_open'];qp=row['entry_qfq_open'];maximum=None;unknown_prefix=False;prefix_suspended=False
    records=by_event.get(eid,[])
    for h in range(21):
        key=f'd{h}_';date=row[key+'date'];right=start+h>=len(calendar)
        check(truth(row[key+'right_censored'])==right,eid,h,'right_censored')
        check(truth(row[key+'no_anchor'])==(not anchor),eid,h,'no_anchor')
        if right:
            for f in ['high_return','close_return','cumulative_high_return']:check(pd.isna(row[key+f]),eid,h,f+'_right_censored')
            continue
        day=calendar[start+h];check(pd.to_datetime(date).strftime('%Y-%m-%d')==day,eid,h,'official_offset_date')
        status=row[key+'tradestatus'];volume=row[key+'raw_volume']
        active=status==1 and good(volume);suspended=status==0 or (pd.notna(volume) and float(volume)==0)
        gh=active and good(row[key+'raw_high']) and good(row[key+'qfq_high']);gc=active and good(row[key+'raw_close']) and good(row[key+'qfq_close'])
        unknown_prefix|=(not suspended and not gh);prefix_suspended|=suspended
        relevant=[r for r in records if truth(r['cross_entry']) and str(r['ex_date'])[:10]<=day]
        blocked=any(not truth(r['verified']) for r in relevant)
        check(truth(row[key+'action_blocked'])==blocked,eid,h,'declared_cross_entry_action_blocker');action_blocker_checked+=1
        check(int(row[key+'cross_entry_action_count'])==len(relevant),eid,h,'cross_entry_action_count')
        unexplained=False
        if anchor and not relevant:
            for kind in ['high','close']:
                r=row[key+'raw_'+kind];q=row[key+'qfq_'+kind]
                if good(r) and good(q):
                    raw_ratio=r/rp;q_ratio=q/qp;tol=max(.0002,.00011/qp*(1+abs(raw_ratio)))
                    unexplained|=abs(raw_ratio-q_ratio)>tol;unexplained_checked+=1
        check(truth(row[key+'unexplained_adjustment'])==unexplained,eid,h,'unexplained_fixed_tolerance')
        unknown_prefix|=unexplained
        hi=row[key+'qfq_high']/qp-1 if anchor and gh and not blocked and not unexplained else None
        cl=row[key+'qfq_close']/qp-1 if anchor and gc and not blocked and not unexplained else None
        if hi is not None:maximum=hi if maximum is None else max(maximum,hi)
        cum=maximum if anchor and maximum is not None and not unknown_prefix and not blocked else None
        for f,expected in [('high_return',hi),('close_return',cl),('cumulative_high_return',cum)]:check(same(row[key+f],expected),eid,h,f)
        check(truth(row[key+'prefix_has_suspension'])==prefix_suspended,eid,h,'suspension_prefix_flag')
        if h==0:check(row[key+'close_sale_assumption']=='T_plus_1_prohibited',eid,h,'D0_T_plus_1')
check(noanchor==6,'ALL',-1,'six_no_anchor_events_retained')

# Direct whitelist price checks for a deterministic representative sample.
sample=set(wide.sort_values('event_id').head(12).event_id)|set(wide.sort_values(['entry_date','event_id']).tail(12).event_id)|set(wide.loc[~wide.anchor_valid].event_id)
for flag in ['suspended','unknown_high','action_blocked','unexplained_adjustment','right_censored']:
    mask=np.logical_or.reduce([wide[f'd{h}_{flag}'].map(truth).to_numpy() for h in range(21)])
    sample.update(wide.loc[mask].sort_values('event_id').head(8).event_id)
cache={};source_price_checks=0
for row in wide.loc[wide.event_id.isin(sample)].to_dict('records'):
    code=row['code'];eid=row['event_id']
    for mode in ['raw','qfq']:
        if (code,mode) not in cache:
            z=whitelisted(qlookup[(code,mode)],['date','open','high','close']);z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');cache[code,mode]=z.set_index('date')
    for h in range(21):
        key=f'd{h}_'
        if truth(row[key+'right_censored']):continue
        day=pd.to_datetime(row[key+'date']).strftime('%Y-%m-%d')
        for mode in ['raw','qfq']:
            z=cache[code,mode]
            for field in ['open','high','close']:
                expected=z.loc[day,field] if day in z.index else None
                check(same(row[key+mode+'_'+field],expected),eid,h,'source_'+mode+'_'+field);source_price_checks+=1

# Four aggregate statistics recomputed independently from all fixed event rows.
engine_summary=pd.read_csv(P/'summary_D0_D20.csv');independent=[];denom=[]
for h in range(21):
    high=pd.to_numeric(wide[f'd{h}_high_return'],errors='coerce');cum=pd.to_numeric(wide[f'd{h}_cumulative_high_return'],errors='coerce');close=pd.to_numeric(wide[f'd{h}_close_return'],errors='coerce')
    values=dict(h=h,total_events=len(wide),valid_n_high=int(high.notna().sum()),valid_n_cumulative=int(cum.notna().sum()),valid_n_close=int(close.notna().sum()),average_daily_high=float(high.mean()),average_cumulative_high=float(cum.mean()),average_close_return=float(close.mean()),close_win_rate=float((close.dropna()>0).mean()),close_wins=int((close>0).sum()),close_ties=int((close==0).sum()),close_losses=int((close<0).sum()))
    actual=engine_summary.loc[engine_summary.h==h].iloc[0]
    for field,value in values.items():check(same(actual[field],value), 'SUMMARY',h,field)
    independent.append(values)
    for metric,series in [('high',high),('cumulative',cum),('close',close)]:
        reasons={}
        for i in wide.index[series.isna()]:
            r=wide.loc[i];prefix=f'd{h}_'
            if truth(r[prefix+'no_anchor']):reason='no_anchor'
            elif truth(r[prefix+'right_censored']):reason='right_censored'
            elif truth(r[prefix+'action_blocked']):reason='declared_cross_entry_action_unverified'
            elif truth(r[prefix+'unexplained_adjustment']):reason='current_unexplained_adjustment'
            elif metric!='cumulative' and truth(r[prefix+'suspended']):reason='confirmed_suspended_observation'
            elif metric=='cumulative':reason='unknown_high_or_adjustment_prefix'
            elif truth(r[prefix+('unknown_high' if metric=='high' else 'unknown_close')]):reason='unknown_current_quote'
            else:reason='other_unavailable'
            reasons[reason]=reasons.get(reason,0)+1
        check(int(series.notna().sum())+sum(reasons.values())==3805,'DENOMINATOR',h,metric)
        denom.append(dict(h=h,metric=metric,total_events=3805,anchor_valid_events=3805-noanchor,valid_n=int(series.notna().sum()),invalid_n=int(series.isna().sum()),**reasons))
save(P/'INDEPENDENT_VALIDATION.json',dict(passed=not errors,total_checks=checked,errors=errors,formula_checks_all_events=True,source_price_sample_events=len(sample),source_price_checks=source_price_checks,explicit_action_blocker_checks=action_blocker_checked,no_action_tolerance_comparisons=unexplained_checked,four_summary_stats_and_counts_all_21_horizons=True,cohort_rows=3805,no_anchor_events=noanchor,original_cohort_hash_unchanged=True,engine_hash_unchanged=True,partial_action_coverage_not_assumed_complete=True,not_an_account=True))
pd.DataFrame(independent).to_csv(P/'independent_summary_D0_D20.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(denom).fillna(0).to_csv(P/'DENOMINATORS.csv',index=False,encoding='utf-8-sig')
assert not errors,errors[:10]
print(json.dumps(read(P/'INDEPENDENT_VALIDATION.json'),ensure_ascii=False))
