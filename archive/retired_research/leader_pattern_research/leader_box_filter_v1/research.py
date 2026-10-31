"""Exploratory leader-only box filter, with pre-2025 whitelist and frozen time audit.

The root prepares snapshots; search reads ONLY its whitelist and train/validation
labels. No post-2024 labels are loaded or used by any mode in this experiment.
"""
from pathlib import Path
import argparse,datetime,hashlib,itertools,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
RESEARCH=HERE.parent
INPUT=HERE/'inputs_pre2025'
OUT=HERE/'holdout_restricted'
BOUNDARY='2024-12-31'
GRID={
 'decline_return':[-.35,-.30,-.25,-.20,-.15],
 'flat_width':[.04,.06,.08,.10],
 'flat_net_change':[-.03,-.01,0,.01,.03],
 'base_decline_volume_ratio':[1.1,1.2,1.5,2,3],
 'volume_multiple':[1.3,1.5,1.8,2,2.5,3,4],
 'body_range_ratio':[.65,.70,.75,.80,.90],
 'upper_shadow_ratio':[.05,.10,.15],
 'day_change':[.01,.02,.03,.05,.07],
 'close_relative_ma60':[-.25,-.15,-.05,0,.05,.15],
 'box_position_num':[.5,.8,1,1.1,1.2,1.5],
 'return20':[-.30,-.20,-.10,0,.10],
 'return60':[-.40,-.20,0,.20],
 'ma20_slope20':[-.20,-.10,-.05,0,.05],
 'close_high60':[-.50,-.30,-.20,-.10,-.05],
 'volatility20':[.010,.015,.020,.030,.040],
 'volume5_prior20':[.8,1,1.2,1.5,2],
 'is_st':[0],
}
EVENT_FEATURES=['decline_return','flat_width','flat_net_change','base_decline_volume_ratio',
 'volume_multiple','body_range_ratio','upper_shadow_ratio','day_change','close_relative_ma60',
 'box_high','box_low','signal_close']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def spec():
    return dict(instruction_boundary_version='public-pre2025-v2',cutoff=BOUNDARY,
        scope='leader_flag_only_existing_mainboard_box_volume12_signals',
        label='bad iff D+1..D+60 max adjusted high / signal close -1 <10%, complete60 only',
        nonleader_behavior='always keep; no change to underlying box or duplicate selection',
        inputs_available_by='signal close; no future fields among features',
        train='signal before2023; label window ends by2022-12-31',
        validation='signal in2023; label window ends by2023-12-31',
        sealed_audit='signal in2024; label window ends by2024-12-31; read only after freeze',
        purge='late-year labels crossing split boundary excluded from selection',
        grids=GRID,rejection_rules='one condition or AND of two conditions on distinct features; <= or >',
        missing_features='keep signal, never reject solely because missing',
        minimum_training_bad_removed=2,minimum_training_rejected_signal_years=2,
        ranking='zero good removed on train; most bad removed, fewer clauses, more years, lexical tie',
        max_distinct_training_rejection_masks_validated=10,
        validation_pass='zero good removed and at least one bad removed in2023',
        selection='first validation pass in fixed training rank; no audit-based reselection',
        no_post2024_outcomes=True,no_production_change=True,
        limitations='Current leader pool used retrospectively; small-sample and many-rule selection bias remain.')

def prepare():
    assert not (INPUT/'manifest.json').exists(),'Preserve registered inputs; use a new experiment for changes.'
    INPUT.mkdir(parents=True,exist_ok=True);OUT.mkdir(exist_ok=True)
    dump(HERE/'SEARCH_SPEC.json',spec()) # freeze grids before reading any outcomes
    current=RESEARCH/'market_wide/holdout_restricted/CURRENT.json'
    bundle=json.loads(current.read_text(encoding='utf-8'))
    assert bundle['structure_version']=='base_volume_strong_bullish_one_box_v5_volume12'
    assert sha(bundle['events'])==bundle['events_sha256']
    cols=['event_id','code','name','signal_date','is_leader','year']+EVENT_FEATURES
    events=pd.read_parquet(bundle['events'],filters=[('is_leader','==',True),('signal_date','<=',BOUNDARY)],columns=cols)
    manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
    lookup={(r['code'],r['mode']):r for r in manifest['files']}
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(bundle['calendar']).date))
    dates=dates[dates<=BOUNDARY]
    pd.DataFrame({'date':dates}).to_csv(INPUT/'exchange_sessions.csv',index=False)
    features=[];labels=[];coverage=[];filelist=[]
    for code,group in events.groupby('code',sort=True):
        frames={}
        for mode in ['raw','qfq']:
            rec=lookup[(code,mode)];assert sha(rec['path'])==rec['snapshot_sha256']
            f=pd.read_parquet(rec['path'],filters=[('date','<=',pd.Timestamp(BOUNDARY))])
            assert pd.to_datetime(f.date).max()<=pd.Timestamp(BOUNDARY)
            path=INPUT/mode/f'{code}.parquet';path.parent.mkdir(exist_ok=True)
            f.to_parquet(path,index=False);filelist.append(dict(path=str(path.relative_to(INPUT)),sha256=sha(path)))
            frames[mode]=f.set_index('date').reindex(dates)
        raw=frames['raw'];q=frames['qfq'];c=q.close.to_numpy(float);o=q.open.to_numpy(float)
        h=q.high.to_numpy(float);lo=q.low.to_numpy(float);v=raw.volume.to_numpy(float)
        valid=raw.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(v)&(v>0)
        for x in [o,c,h,lo]:valid &=np.isfinite(x)&(x>0)
        def known_slice(a,start,end):
            return a[start:end] if start>=0 and valid[start:end].all() else None
        for row in group.to_dict('records'):
            t=dates.get_loc(pd.Timestamp(row['signal_date']))
            row.update(box_position_num=(row['signal_close']-row['box_low'])/(row['box_high']-row['box_low']),
                is_st=float(str(raw.isST.iloc[t]) in ['1','1.0']))
            for k in [20,60]:
                x=known_slice(c,t-k,t+1);row[f'return{k}']=float(x[-1]/x[0]-1) if x is not None else None
            x=known_slice(c,t-39,t+1)
            row['ma20_slope20']=float(x[20:].mean()/x[:20].mean()-1) if x is not None else None
            x=known_slice(h,t-59,t+1)
            row['close_high60']=float(c[t]/x.max()-1) if x is not None else None
            x=known_slice(c,t-20,t+1)
            row['volatility20']=float(np.std(np.diff(np.log(x)),ddof=1)) if x is not None else None
            x=known_slice(v,t-24,t+1)
            row['volume5_prior20']=float(x[-5:].mean()/x[:20].mean()) if x is not None else None
            end=t+60
            complete=end<len(dates) and valid[t+1:end+1].all()
            enddate=dates[end].strftime('%Y-%m-%d') if end<len(dates) else None
            coverage.append(dict(event_id=row['event_id'],signal_date=row['signal_date'],complete60=bool(complete),label_end=enddate))
            if not complete:continue
            price=float(h[t+1:end+1].max());ret=price/c[t]-1
            row['label_end']=enddate
            row['split']='train' if row['signal_date']<'2023-01-01' and enddate<='2022-12-31' else 'validation' if row['signal_date'][:4]=='2023' and enddate<='2023-12-31' else 'audit2024' if row['signal_date'][:4]=='2024' else 'purged'
            labels.append(dict(event_id=row['event_id'],split=row['split'],peak_return60=float(ret),bad=bool(ret<.10-1e-12)))
            features.append(row)
    f=pd.DataFrame(features).sort_values(['signal_date','code']);lab=pd.DataFrame(labels)
    f.to_parquet(INPUT/'features.parquet',index=False)
    lab[lab.split.isin(['train','validation'])].to_parquet(INPUT/'labels_trainval.parquet',index=False)
    # Pre-2025, but sealed to keep the final year out of candidate selection.
    lab[lab.split.isin(['audit2024','purged'])].to_parquet(OUT/'sealed_labels.parquet',index=False)
    pd.DataFrame(coverage).to_parquet(INPUT/'coverage.parquet',index=False)
    for name in ['features.parquet','labels_trainval.parquet','coverage.parquet','exchange_sessions.csv']:
        filelist.append(dict(path=name,sha256=sha(INPUT/name)))
    dump(INPUT/'manifest.json',dict(instruction_boundary_version='public-pre2025-v2',cutoff=BOUNDARY,files=filelist,
        features=list(GRID),feature_definitions=dict(return20='C[t]/C[t-20]-1',return60='C[t]/C[t-60]-1',
        ma20_slope20='meanC[t-19:t]/meanC[t-39:t-20]-1',close_high60='C[t]/maxH[t-59:t]-1',
        volatility20='sample std of20daily log returns ending t',volume5_prior20='meanV[t-4:t]/meanV[t-24:t-5]',
        box_position_num='(signalclose-boxlow)/(boxhigh-boxlow)'),no_post_boundary_rows=True))
    dump(OUT/'PROVENANCE.json',dict(source_bundle=bundle,source_manifest_sha256=sha(bundle['manifest']),
        source_events_sha256=sha(bundle['events']),prepared_at=datetime.datetime.now().isoformat(),
        no_post2024_labels_loaded=True,search_spec_sha256=sha(HERE/'SEARCH_SPEC.json')))
    print(json.dumps(dict(prepared=True,complete_pre2025=len(f),split_counts=f.split.value_counts().to_dict(),
        incomplete_pre2025=int((~pd.DataFrame(coverage).complete60).sum())),ensure_ascii=False))

def verify_inputs():
    m=json.loads((INPUT/'manifest.json').read_text(encoding='utf-8'))
    assert m['cutoff']==BOUNDARY and m['instruction_boundary_version']=='public-pre2025-v2'
    for r in m['files']:assert sha(INPUT/r['path'])==r['sha256'],r['path']
    assert json.loads((HERE/'SEARCH_SPEC.json').read_text(encoding='utf-8'))==spec()

def reject(f,clauses):
    mask=np.ones(len(f),bool)
    for clause in clauses:
        x=f[clause['feature']].to_numpy(float);k=clause['threshold']
        mask &=np.isfinite(x)&((x<=k) if clause['op']=='<=' else (x>k))
    return mask

def score(f,bad,mask):
    bad=np.asarray(bad,bool)
    return dict(total=len(f),bad_total=int(bad.sum()),good_total=int((~bad).sum()),
        bad_removed=int((mask&bad).sum()),good_removed=int((mask&~bad).sum()),
        bad_kept=int((~mask&bad).sum()),good_kept=int((~mask&~bad).sum()),
        removed_years=int(f.loc[mask,'year'].nunique()))

def search():
    verify_inputs();assert not (OUT/'FROZEN_CANDIDATE.json').exists(),'Candidate already frozen; do not tune from audit.'
    all_features=pd.read_parquet(INPUT/'features.parquet')
    labels=pd.read_parquet(INPUT/'labels_trainval.parquet')
    f=all_features[all_features.split.isin(['train','validation'])].merge(labels.drop(columns='split'),on='event_id',validate='one_to_one')
    train=f[f.split.eq('train')].reset_index(drop=True);val=f[f.split.eq('validation')].reset_index(drop=True)
    bad=train.bad.to_numpy(bool);primitives=[];tested=0;eligible=[]
    for feature,thresholds in GRID.items():
        for k in thresholds:
            for op in ['<=','>']:
                clause=dict(feature=feature,op=op,threshold=k)
                primitives.append((clause,reject(train,[clause])))
    def consider(clauses,mask):
        nonlocal tested
        tested+=1;s=score(train,bad,mask)
        if s['good_removed'] or s['bad_removed']<2 or s['removed_years']<2:return
        key=json.dumps(clauses,sort_keys=True)
        eligible.append(dict(clauses=clauses,train=s,mask_key=''.join('1' if b else '0' for b in mask),
            rank=(-s['bad_removed'],len(clauses),-s['removed_years'],key)))
    for clause,mask in primitives:consider([clause],mask)
    for (a,ma),(b,mb) in itertools.combinations(primitives,2):
        if a['feature']!=b['feature']:consider([a,b],ma&mb)
    eligible.sort(key=lambda r:r['rank']);shortlist=[];seen=set()
    for r in eligible:
        if r['mask_key'] in seen:continue
        seen.add(r['mask_key']);shortlist.append(r)
        if len(shortlist)==10:break
    chosen=None
    for rank,r in enumerate(shortlist,1):
        r['training_rank']=rank;r['validation']=score(val,val.bad,reject(val,r['clauses']))
        r['validation_pass']=r['validation']['good_removed']==0 and r['validation']['bad_removed']>=1
        if chosen is None and r['validation_pass']:chosen=r
    accepted=chosen is not None
    if chosen is None and shortlist:chosen=shortlist[0]
    report=dict(hypotheses_tested=tested,eligible_train_zero_good_loss=len(eligible),
        distinct_train_masks_validated=len(shortlist),train_base=score(train,bad,np.zeros(len(train),bool)),
        validation_base=score(val,val.bad,np.zeros(len(val),bool)),shortlist=shortlist,
        selected_passed_validation=accepted,post2024_not_read=True)
    dump(OUT/'TRAINVAL_REPORT.json',report)
    frozen=dict(scope='leader_only',active=False,clauses=chosen['clauses'] if chosen else [],
        status='research_candidate_passed_validation' if accepted else 'diagnostic_only_no_validated_candidate',
        train=chosen['train'] if chosen else None,validation=chosen['validation'] if chosen else None,
        training_rank=chosen['training_rank'] if chosen else None,
        spec_sha256=sha(HERE/'SEARCH_SPEC.json'),inputs_sha256=sha(INPUT/'manifest.json'),
        training_report_sha256=sha(OUT/'TRAINVAL_REPORT.json'),frozen_at=datetime.datetime.now().isoformat(),
        requires_no_production_change=True,no_post2024_data=True)
    dump(OUT/'FROZEN_CANDIDATE.json',frozen)
    frozen_hash=sha(OUT/'FROZEN_CANDIDATE.json');dump(OUT/'FREEZE_RECEIPT.json',dict(sha256=frozen_hash))
    print(json.dumps(dict(hypotheses_tested=tested,train_base=report['train_base'],validation_base=report['validation_base'],
        eligible=len(eligible),shortlist=len(shortlist),candidate=frozen,candidate_sha256=frozen_hash),ensure_ascii=False,indent=2))

def audit():
    verify_inputs();path=OUT/'FROZEN_CANDIDATE.json';frozen=json.loads(path.read_text(encoding='utf-8'))
    assert sha(path)==json.loads((OUT/'FREEZE_RECEIPT.json').read_text(encoding='utf-8'))['sha256']
    assert not (OUT/'FINAL_REPORT.json').exists(),'Audit is one way; do not rerun to tune.'
    f=pd.read_parquet(INPUT/'features.parquet');sealed=pd.read_parquet(OUT/'sealed_labels.parquet')
    trainval=pd.read_parquet(INPUT/'labels_trainval.parquet')
    f=f.merge(pd.concat([trainval,sealed]).drop(columns='split'),on='event_id',validate='one_to_one')
    mask=reject(f,frozen['clauses']) if frozen['clauses'] else np.zeros(len(f),bool)
    f['candidate_reject']=mask
    results={}
    for name in ['train','validation','audit2024','purged']:
        g=f[f.split.eq(name)];results[name]=score(g,g.bad,g.candidate_reject.to_numpy(bool))
    results['all_pre2025']=score(f,f.bad,mask)
    rows=[]
    for year,g in f.groupby('year'):
        rows.append(dict(year=int(year),**score(g,g.bad,g.candidate_reject.to_numpy(bool))))
    f.to_parquet(OUT/'classified_pre2025_events.parquet',index=False)
    report=dict(frozen_candidate_sha256=sha(path),candidate=frozen,periods=results,by_year=rows,
        production_unchanged=True,nonleader_signals_unchanged=True,post2024_labels_not_read=True,
        final_audit_pass=bool(frozen['status']=='research_candidate_passed_validation' and
            results['audit2024']['good_removed']==0 and results['audit2024']['bad_removed']>=1))
    dump(OUT/'FINAL_REPORT.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','search','audit']);args=parser.parse_args()
    dict(prepare=prepare,search=search,audit=audit)[args.mode]()
