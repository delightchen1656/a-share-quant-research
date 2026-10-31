"""Reusable, side-effect-free-on-import cohort price-path engine.

Only explicit hash-whitelisted inputs may be read by run_cohort. No strategy scans,
classification, orders, accounts or future-window cohort filtering are implemented.
"""
from __future__ import annotations
import csv, hashlib, json, math
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import numpy as np
import pandas as pd

DAY_FIELDS=['date','raw_open','raw_high','raw_close','qfq_open','qfq_high','qfq_close','raw_volume','tradestatus','isST','raw_high_unadjusted_return','raw_close_unadjusted_return','observed_qfq_high_return','observed_qfq_close_return','high_return','cumulative_high_return','close_return','no_anchor','suspended','unknown_high','unknown_close','right_censored','action_blocked','unexplained_adjustment','close_at_lower_limit','close_limit_unknown','prefix_has_suspension','cumulative_prefix_all_sessions_traded','cross_entry_action_count','observation_status','close_sale_assumption']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def clean(x):
    if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    if isinstance(x,(bool,np.bool_)):return bool(x)
    if isinstance(x,np.integer):return int(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    if isinstance(x,pd.Timestamp):return x.isoformat()
    return x
def save(path,value):Path(path).write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False,default=str),encoding='utf-8')
def positive(x):return pd.notna(x) and np.isfinite(x) and x>0
def date_value(x):return pd.to_datetime(x,errors='coerce')
def bool_value(x):return x is True or str(x).lower() in ['true','1','1.0']
def normalize_code(x):return str(x).split('.')[0].zfill(6)

class Whitelist:
    def __init__(self,root,manifest_hash,access):
        self.root=Path(root).resolve();self.access=access;mp=self.root/'MANIFEST.json'
        if sha(mp)!=manifest_hash:raise RuntimeError('Manifest hash mismatch '+str(mp))
        self.manifest=json.loads(mp.read_text(encoding='utf-8-sig'))
        self.access.append({'path':str(mp),'sha256':manifest_hash})
        if not self.manifest.get('complete') or self.manifest.get('cutoff')!='2024-12-31':raise RuntimeError('Manifest not complete at approved boundary')
        self.files={x['path'].replace('\\','/'):x['sha256'] for x in self.manifest['files']}
    def read(self,relative):
        rel=relative.replace('\\','/');p=(self.root/rel).resolve()
        if rel not in self.files or not p.is_relative_to(self.root):raise RuntimeError('Unapproved input '+rel)
        digest=sha(p)
        if digest!=self.files[rel]:raise RuntimeError('File hash mismatch '+rel)
        self.access.append({'path':str(p),'sha256':digest})
        if p.suffix=='.parquet':return pd.read_parquet(p)
        if p.suffix=='.csv':return pd.read_csv(p,dtype={'code':str})
        return json.loads(p.read_text(encoding='utf-8-sig'))

class Actions:
    """Explicit successful per-issuer-year responses, including genuine empties."""
    def __init__(self,reader):
        self.reader=reader;self.index={x['key']:x for x in reader.manifest.get('responses',[])};self.cache={};self.coverage=[]
        if not isinstance(reader.manifest.get('responses'),list):raise RuntimeError('Action manifest must explicitly describe response coverage')
    def window(self,code,start,end):
        records=[];issues=[]
        for year in range(start.year,end.year+1):
            key=f'{code}.{"SH" if code.startswith("6") else "SZ"}/{year}'
            if key not in self.cache:
                item=self.index.get(key)
                if item is None:self.cache[key]=(None,['not_covered_by_targeted_snapshot'])
                else:
                    payload=self.reader.read(item['path'])
                    if str(payload.get('error_code'))!='0' or not isinstance(payload.get('records'),list):self.cache[key]=(None,['unsuccessful_or_invalid_response'])
                    else:self.cache[key]=(payload['records'],[])
                self.coverage.append({'key':key,'coverage_level':'successful_response' if not self.cache[key][1] else 'targeted_coverage_gap_or_failed_response','issues':self.cache[key][1],'records':len(self.cache[key][0]) if self.cache[key][0] is not None else None})
            data,errors=self.cache[key]
            if errors:issues.extend([key+':'+e for e in errors]);continue
            for a in data:
                ex=date_value(a.get('dividOperateDate'))
                if pd.notna(ex) and start<=ex<=end:records.append(a)
        return records,issues

def verify_actions(records,code,start,dates,raw,qfq):
    out=[]
    for a in records:
        ex=date_value(a.get('dividOperateDate'))
        def num(k):
            x=a.get(k,'')
            if x is None or str(x).strip()=='':return 0.
            try:return float(x)
            except (TypeError,ValueError):return np.nan
        cash=num('dividCashPsBeforeTax');stock=num('dividStocksPs');reserve=num('dividReserveToStockPs');bonus=stock+reserve
        if cash==0 and bonus==0:continue
        errors=[];expected=np.nan;implied=np.nan
        if not all(np.isfinite(x) for x in [cash,stock,reserve]):errors.append('invalid_action_units')
        if ex not in dates:errors.append('ex_date_not_in_calendar')
        else:
            i=dates.get_loc(ex)
            if i==0:errors.append('missing_previous_reference')
            else:
                p=raw.close.iloc[i-1];c=raw.close.iloc[i];qp=qfq.close.iloc[i-1];qc=qfq.close.iloc[i]
                if all(positive(x) for x in [p,c,qp,qc]) and 1+bonus>0:
                    expected=(p-cash)/(1+bonus);implied=c*qp/qc
                    if abs(implied-expected)>max(.035,.002*expected):errors.append('ex_reference_mismatch')
                else:errors.append('unavailable_reference_quote')
        pay=date_value(a.get('dividPayDate'));listing=date_value(a.get('dividStockMarketDate'))
        if cash and pd.isna(pay):errors.append('missing_cash_pay_date')
        if bonus and pd.isna(listing):errors.append('missing_bonus_listing_date')
        out.append(dict(code=code,ex_date=ex,cash_per_share=cash,stock_dividend_per_share=stock,reserve_transfer_per_share=reserve,pay_date=pay,stock_listing_date=listing,expected_reference=expected,qfq_implied_reference=implied,issues=errors,verified=not errors,entry_day_action=ex==start,cross_entry=ex>start))
    return out

def lower_limit(row):
    st=row.get('isST',np.nan);ref=row.get('preclose',np.nan)
    if st not in [0,1] or not positive(ref):return None
    rate=Decimal('.95') if st==1 else Decimal('.90')
    return float((Decimal(str(ref))*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def make_event_path(event,dates,raw,qfq,actions,columns,horizon=20):
    """Return unchanged event + D0..horizon observations, action audit, checks.

    columns maps id/code/signal_date/entry_date/entry_raw_open/next_valid_open/
    next_state/upper_limit to cohort column names. No reselecting or delayed anchor.
    """
    code=normalize_code(event[columns['code']]);eid=str(event[columns['id']]);signal=date_value(event[columns['signal_date']])
    if signal not in dates:raise RuntimeError('Signal outside formal approved calendar '+eid)
    i=dates.get_loc(signal)+1;entry_date=dates[i] if i<len(dates) else pd.NaT
    stated=date_value(event.get(columns.get('entry_date','entry_date')))
    if pd.notna(stated) and (pd.isna(entry_date) or stated!=entry_date):raise RuntimeError('Not strict next formal anchor '+eid)
    row={**event,'event_id':eid,'code':code,'signal_date':signal,'entry_date':entry_date}
    check={'event_id':eid,'anchor_date_verified':True,'anchor_price_verified':False,'no_action_comparisons':0,'no_action_tolerance_failures':0,'max_no_action_difference':0.,'prefix_monotonicity_failures':0,'normalization_failures':0}
    declared=bool_value(event.get(columns.get('next_valid_open','next_valid_open'),False))
    rp=np.nan;qp=np.nan;anchor=False;astatus='pending_boundary';coverage_errors=[];ae=[]
    if i<len(dates):
        r0=raw.iloc[i];q0=qfq.iloc[i];observed=r0.open
        supplied=event.get(columns.get('entry_raw_open','next_raw_open'),np.nan)
        if pd.notna(supplied) and pd.notna(observed) and abs(float(supplied)-float(observed))>1e-7:raise RuntimeError('Cohort/raw anchor quote mismatch '+eid)
        check['anchor_price_verified']=bool(pd.notna(supplied) and pd.notna(observed))
        active=r0.get('tradestatus',np.nan)==1 and positive(r0.get('volume',np.nan)) and positive(observed) and positive(q0.open)
        if declared and active:anchor=True;rp=float(observed);qp=float(q0.open);astatus='active_open_observation'
        elif r0.get('tradestatus',np.nan)==0 or (pd.notna(r0.get('volume')) and r0.get('volume')==0):astatus='confirmed_suspended_no_anchor'
        else:astatus='unknown_or_declared_unavailable_no_anchor'
        records,coverage_errors=actions.window(code,entry_date,dates[min(i+horizon,len(dates)-1)])
        ae=verify_actions(records,code,entry_date,dates,raw,qfq)
    row.update(anchor_status=astatus,anchor_valid=anchor,entry_raw_open=rp,entry_qfq_open=qp,entry_upper_limit_fill_unconfirmed=bool_value(event.get(columns.get('upper_limit','next_open_upper_limit'),False)),action_coverage_issues=json.dumps(coverage_errors,ensure_ascii=False),action_coverage_level='targeted_response_gaps_or_failures_price_path_only' if coverage_errors else 'successful_responses_for_window_years_not_official_exhaustive',window_action_records=len(ae),window_cross_entry_actions=sum(a['cross_entry'] for a in ae))
    if anchor and (rp/rp!=1 or qp/qp!=1):raise RuntimeError('Anchor normalization invalid '+eid)
    highs=[];unknown_prefix=False;prefix_suspended=False;prior_cum=None
    for h in range(horizon+1):
        k=i+h;prefix=f'd{h}_';f={name:np.nan for name in DAY_FIELDS}
        for name in ['no_anchor','suspended','unknown_high','unknown_close','right_censored','action_blocked','unexplained_adjustment','close_at_lower_limit','close_limit_unknown','prefix_has_suspension','cumulative_prefix_all_sessions_traded']:f[name]=False
        f.update(no_anchor=not anchor,cross_entry_action_count=0,observation_status='',close_sale_assumption='T_plus_1_prohibited' if h==0 else 'observed_close_only_no_fill_guarantee')
        if k>=len(dates):
            f.update(date=None,right_censored=True,observation_status='right_censored_boundary');row.update({prefix+x:y for x,y in f.items()});continue
        d=dates[k];r=raw.iloc[k];q=qfq.iloc[k]
        f.update(date=d,raw_open=r.open,raw_high=r.high,raw_close=r.close,qfq_open=q.open,qfq_high=q.high,qfq_close=q.close,raw_volume=r.get('volume',np.nan),tradestatus=r.get('tradestatus',np.nan),isST=r.get('isST',np.nan))
        suspended=r.get('tradestatus',np.nan)==0 or (pd.notna(r.get('volume')) and r.get('volume')==0)
        active=r.get('tradestatus',np.nan)==1 and positive(r.get('volume',np.nan));goodhigh=active and positive(r.high) and positive(q.high);goodclose=active and positive(r.close) and positive(q.close)
        f.update(suspended=bool(suspended),unknown_high=bool(not suspended and not goodhigh),unknown_close=bool(not suspended and not goodclose))
        unknown_prefix |= f['unknown_high'];prefix_suspended |= bool(suspended)
        relevant=[a for a in ae if a['cross_entry'] and a['ex_date']<=d]
        # Targeted response coverage is partial. Gaps/failed queries are evidence
        # limitations, never fictional empty tables and never blanket blockers.
        # Only a declared CROSS-entry unresolved action or the fixed raw/qfq
        # no-action tolerance below can invalidate a primary price-path label.
        blocked=any(not a['verified'] for a in relevant)
        f.update(action_blocked=blocked,cross_entry_action_count=len(relevant))
        unexplained=False
        if anchor:
            for kind in ['high','close']:
                rv=r.get(kind,np.nan);qv=q.get(kind,np.nan)
                if positive(rv):f[f'raw_{kind}_unadjusted_return']=rv/rp-1
                if positive(qv):f[f'observed_qfq_{kind}_return']=qv/qp-1
                if not relevant and positive(rv) and positive(qv):
                    delta=abs(rv/rp-qv/qp);tol=max(.0002,.00011/qp*(1+abs(rv/rp)))
                    check['no_action_comparisons']+=1;check['max_no_action_difference']=max(check['max_no_action_difference'],delta)
                    if delta>tol:unexplained=True;check['no_action_tolerance_failures']+=1
            if unexplained:unknown_prefix=True
            if goodhigh and not blocked and not unexplained:f['high_return']=q.high/qp-1;highs.append(float(q.high))
            if goodclose and not blocked and not unexplained:f['close_return']=q.close/qp-1
            if highs and not blocked and not unknown_prefix:
                f['cumulative_high_return']=max(highs)/qp-1
                if prior_cum is not None and f['cumulative_high_return']<prior_cum-1e-12:raise RuntimeError('Prefix maximum decreased '+eid)
                prior_cum=f['cumulative_high_return']
        f.update(unexplained_adjustment=unexplained,prefix_has_suspension=prefix_suspended,cumulative_prefix_all_sessions_traded=anchor and not prefix_suspended and not unknown_prefix)
        limit=lower_limit(r);f['close_limit_unknown']=limit is None;f['close_at_lower_limit']=bool(limit is not None and positive(r.close) and r.close<=limit+1e-6)
        if h>0 and suspended:f['close_sale_assumption']='suspended_no_trade'
        elif h>0 and f['close_at_lower_limit']:f['close_sale_assumption']='lower_limit_sale_unconfirmed'
        f['observation_status']='no_entry_anchor' if not anchor else 'suspended_provider_quote_only' if suspended else 'unknown_quote_blocked' if f['unknown_high'] or f['unknown_close'] else 'action_or_adjustment_blocked' if blocked or unexplained else 'active_quote_observation'
        row.update({prefix+x:y for x,y in f.items()})
    return row,[dict(event_id=eid,**a) for a in ae],check

class Summary:
    def __init__(self,horizon):
        self.horizon=horizon;self.rows=[{'h':h,'label':'D0' if h==0 else f'D+{h}','total_events':0,'high':[],'cum':[],'close':[],'no_anchor':0,'targeted_coverage_gap_events':0,'confirmed_suspended':0,'unknown_high':0,'unknown_close':0,'right_censored':0,'action_blocked':0,'unexplained_adjustment':0,'close_at_lower_limit':0,'prefix_with_suspension':0} for h in range(horizon+1)]
    def add(self,event):
        for h,r in enumerate(self.rows):
            r['total_events']+=1;r['targeted_coverage_gap_events']+=int(event['action_coverage_level']=='targeted_response_gaps_or_failures_price_path_only');p=f'd{h}_'
            for short,key in [('high','high_return'),('cum','cumulative_high_return'),('close','close_return')]:
                v=event[p+key]
                if pd.notna(v) and np.isfinite(v):r[short].append(float(v))
            for key,source in [('no_anchor','no_anchor'),('confirmed_suspended','suspended'),('unknown_high','unknown_high'),('unknown_close','unknown_close'),('right_censored','right_censored'),('action_blocked','action_blocked'),('unexplained_adjustment','unexplained_adjustment'),('close_at_lower_limit','close_at_lower_limit'),('prefix_with_suspension','prefix_has_suspension')]:r[key]+=int(bool(event[p+source]))
    def finish(self):
        result=[]
        for x in self.rows:
            high=np.asarray(x['high']);cum=np.asarray(x['cum']);close=np.asarray(x['close'])
            r={k:v for k,v in x.items() if k not in ['high','cum','close']}
            r.update(valid_n_high=len(high),valid_n_cumulative=len(cum),valid_n_close=len(close),average_daily_high=float(high.mean()) if len(high) else None,average_cumulative_high=float(cum.mean()) if len(cum) else None,average_close_return=float(close.mean()) if len(close) else None,close_win_rate=float((close>0).mean()) if len(close) else None,close_wins=int((close>0).sum()),close_ties=int((close==0).sum()),close_losses=int((close<0).sum()));result.append(r)
        return result

def read_quote(reader,item,dates):
    q=reader.read(item['path'])
    if 'date' not in q:raise RuntimeError('Quote lacks date column')
    q['date']=pd.to_datetime(q.date.astype(str))
    if q.date.duplicated().any() or (not q.empty and q.date.max()>pd.Timestamp('2024-12-31')):raise RuntimeError('Quote duplicate/boundary')
    q=q.set_index('date').reindex(dates)
    for c in ['open','high','low','close','preclose','volume','amount','tradestatus','isST']:q[c]=pd.to_numeric(q[c],errors='coerce') if c in q else np.nan
    return q

def freeze_config(config_path):
    """Bind explicit action authorization and freeze before any labels are computed."""
    p=Path(config_path);cfg=json.loads(p.read_text(encoding='utf-8'))
    for source in ['prices','actions']:
        x=cfg.get(source)
        if not x or not isinstance(x.get('manifest_sha256'),str) or len(x['manifest_sha256'])!=64:raise RuntimeError('Missing approved '+source+' manifest hash')
    out=Path(cfg['output_dir']);out.mkdir(parents=True,exist_ok=True)
    save(out/'RUN_FREEZE.json',{'config_sha256':sha(p),'engine_sha256':sha(Path(__file__)),'cohort_sha256':cfg['cohort']['sha256'],'price_manifest_sha256':cfg['prices']['manifest_sha256'],'action_manifest_sha256':cfg['actions']['manifest_sha256'],'before_labels':True})

def run_cohort(config_path):
    p=Path(config_path);cfg=json.loads(p.read_text(encoding='utf-8'));out=Path(cfg['output_dir']);f=json.loads((out/'RUN_FREEZE.json').read_text(encoding='utf-8'))
    if sha(p)!=f['config_sha256'] or sha(Path(__file__))!=f['engine_sha256']:raise RuntimeError('Frozen config/engine changed')
    if not cfg.get('actions') or not cfg['actions'].get('manifest_sha256'):raise RuntimeError('Action whitelist authorization required before labels')
    access=[];price=Whitelist(cfg['prices']['root'],cfg['prices']['manifest_sha256'],access);actreader=Whitelist(cfg['actions']['root'],cfg['actions']['manifest_sha256'],access);actions=Actions(actreader)
    cohort=Path(cfg['cohort']['path'])
    if sha(cohort)!=cfg['cohort']['sha256']:raise RuntimeError('Cohort hash mismatch')
    events=pd.read_csv(cohort,dtype={cfg['cohort']['columns']['code']:str},encoding='utf-8-sig');access.append({'path':str(cohort),'sha256':sha(cohort)})
    cols=cfg['cohort']['columns'];events[cols['code']]=events[cols['code']].map(normalize_code)
    if len(events)!=cfg['cohort']['expected_rows'] or events[cols['id']].duplicated().any():raise RuntimeError('Fixed cohort row count/ID changed')
    cal=price.read(price.manifest['calendar']);dates=pd.DatetimeIndex(pd.to_datetime(cal.date.astype(str))).sort_values()
    if dates.duplicated().any() or dates.max()>pd.Timestamp('2024-12-31'):raise RuntimeError('Calendar boundary/duplicate')
    qm=price.read(price.manifest['quote_manifest']);qi={(normalize_code(x['code']),x['mode']):x for x in qm['files']}
    horizon=cfg.get('horizon',20);summary=Summary(horizon);auditrows=[];actionaudit=[];coveragelevels={};writer=None;file=out/cfg.get('event_filename','all_event_paths.csv')
    with file.open('w',encoding='utf-8-sig',newline='') as stream:
        for n,(code,group) in enumerate(events.groupby(cols['code'],sort=True),1):
            if (code,'raw') not in qi or (code,'qfq') not in qi:raise RuntimeError('Cohort quote missing '+code)
            raw=read_quote(price,qi[code,'raw'],dates);qfq=read_quote(price,qi[code,'qfq'],dates)
            for e in group.to_dict('records'):
                row,aa,check=make_event_path(e,dates,raw,qfq,actions,cols,horizon)
                if writer is None:writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader()
                writer.writerow({k:(v.isoformat() if isinstance(v,pd.Timestamp) else v) for k,v in row.items()});summary.add(row);auditrows.append(check);actionaudit.extend(aa);coveragelevels[row['action_coverage_level']]=coveragelevels.get(row['action_coverage_level'],0)+1
            if n%250==0:print(json.dumps({'codes_processed':n,'events_processed':len(auditrows)}),flush=True)
    final=summary.finish();pd.DataFrame(final).to_csv(out/'summary_D0_D20.csv',index=False,encoding='utf-8-sig');save(out/'summary_D0_D20.json',final)
    save(out/'company_action_audit.json',{'coverage':actions.coverage,'event_coverage_levels':coveragelevels,'records':actionaudit,'note':'Targeted partial responses, not all issuer-years. Missing/failed responses are disclosed, not assumed empty or blanket-blocking. Only unresolved declared cross-entry actions or fixed-tolerance unexplained raw/qfq changes block primary labels. No official exhaustive or net economic-return claim.'})
    save(out/'validation_audit.json',{'status':'numeric_checks_pass_with_explicit_label_blockers','events':len(events),'cohort_sha256_unchanged':sha(cohort),'source_input_hashes':{'prices':cfg['prices']['manifest_sha256'],'actions':cfg['actions']['manifest_sha256']},'event_checks':auditrows,'labels_include_no_anchor_suspension_censor_and_action_flags':True,'no_accounts_factors_or_groups':True});save(out/'access_audit.json',access)
    return {'summary':final,'event_file':str(file),'events':len(events),'output_dir':str(out)}
