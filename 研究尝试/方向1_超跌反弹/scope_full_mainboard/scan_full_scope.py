"""Unchanged structural scan only; explicit frozen whitelist required.

No account, future outcome, current classification or economic-return code.
Universe is projected to code/name/IPO date columns, never outDate/status.
"""
import argparse,hashlib,importlib.util,json,re,sys
from pathlib import Path
import numpy as np
import pandas as pd

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def code6(x):
    m=re.search(r'\d{6}',str(x))
    if not m:raise ValueError('Invalid code '+str(x))
    return m.group()
def dates(s):return pd.to_datetime(s,errors='coerce').dt.strftime('%Y-%m-%d')
def projected(path,columns):
    if path.suffix=='.parquet':return pd.read_parquet(path,columns=columns)
    return pd.read_csv(path,usecols=columns,dtype=str)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-root',required=True);parser.add_argument('--manifest',required=True);parser.add_argument('--expected-hash',required=True)
    parser.add_argument('--calendar',required=True);parser.add_argument('--universe',required=True)
    parser.add_argument('--code-column',default='code');parser.add_argument('--name-column',default='code_name');parser.add_argument('--ipo-column',default='ipoDate')
    args=parser.parse_args();area=Path(args.input_root).resolve()
    def local(relative):
        p=(area/relative).resolve()
        if area not in p.parents or 'holdout_restricted' in p.parts:raise ValueError('Outside frozen input root')
        return p
    def guard(event,values):
        if event=='open' and not isinstance(values[0],int) and 'holdout_restricted' in Path(values[0]).parts:raise PermissionError('Restricted access blocked')
    sys.addaudithook(guard)
    manifest_path=local(args.manifest)
    if sha(manifest_path)!=args.expected_hash.lower():raise ValueError('Manifest hash mismatch')
    manifest=read(manifest_path)
    if manifest.get('cutoff','2024-12-31')>'2024-12-31':raise ValueError('Boundary exceeded')
    listing={x['path']:x for x in manifest['files']}
    for path,info in listing.items():
        if sha(local(path))!=info['sha256']:raise ValueError('Input hash mismatch '+path)
    for required in [args.calendar,args.universe]:
        if required not in listing:raise ValueError('Not whitelisted '+required)
    meta=projected(local(args.universe),[args.code_column,args.name_column,args.ipo_column])
    meta=meta.rename(columns={args.code_column:'code',args.name_column:'name',args.ipo_column:'ipo_date'})
    meta['code']=meta.code.map(code6);meta['ipo_date']=dates(meta.ipo_date)
    if meta.code.duplicated().any() or meta.ipo_date.isna().any():raise ValueError('Ambiguous universe/IPO dates')
    info_by_code=meta.set_index('code').to_dict('index')
    quote_manifest=read(local(manifest['quote_manifest']))
    if quote_manifest['cutoff']>'2024-12-31':raise ValueError('Quote manifest boundary exceeded')
    lookup={(code6(x['code']),x['mode']):x for x in quote_manifest['files']}
    for info in quote_manifest['files']:
        if info['path'] not in listing or listing[info['path']]['sha256']!=info['sha256']:raise ValueError('Quote file not in frozen whitelist')
    codes=sorted(info_by_code)
    if set(codes)!={c for c,m in lookup if m=='raw'}:raise ValueError('Universe/price coverage mismatch')
    if any((c,'qfq') not in lookup for c in codes):raise ValueError('Missing qfq')
    calendar=projected(local(args.calendar),['date'])
    sessions=dates(calendar.date).tolist()
    if sessions!=sorted(set(sessions)) or sessions[-1]>'2024-12-31':raise ValueError('Invalid calendar')
    ordinal={d:i for i,d in enumerate(sessions)}
    spec=importlib.util.spec_from_file_location('fullscope_structure',ROOT/'structure.py');structure=importlib.util.module_from_spec(spec);spec.loader.exec_module(structure)
    # Original membership and legacy rows only; outcome and account columns never loaded.
    old_pool=projected(local(manifest['old_pool']),['code'])
    old947={code6(x) for x in old_pool.code}
    old=projected(ROOT/'inputs_pre2025/signals.parquet',['code','date','entry_date'])
    old['code']=old.code.map(code6);old['date']=dates(old.date);old['entry_date']=dates(old.entry_date)
    old['entry_date']=old.entry_date.map(lambda x:None if pd.isna(x) else x)
    if old.date.max()>'2024-12-31':raise ValueError('Legacy outside boundary')
    old=old.drop_duplicates(['code','date']);oldkeys=set(zip(old.code,old.date))
    outputs=[];stage_audit=[];legacy_diagnostics=[]
    for code_number,code in enumerate(codes,1):
        frames=[]
        for mode in ['raw','qfq']:
            z=pd.read_parquet(local(lookup[(code,mode)]['path']));z['date']=dates(z.date)
            if z.date.isna().any() or z.date.duplicated().any() or (len(z) and z.date.max()>'2024-12-31'):raise ValueError('Invalid price dates '+code)
            z=z.sort_values('date').reset_index(drop=True);frames.append(z)
        raw,qfq=frames
        if not raw.date.equals(qfq.date):raise ValueError('Raw/qfq misalignment '+code)
        ipo=info_by_code[code]['ipo_date'];raw=raw.loc[raw.date>=ipo].reset_index(drop=True);qfq=qfq.loc[qfq.date>=ipo].reset_index(drop=True)
        f,qv,rv=structure.scan(qfq,raw);independent=set(structure.independent(f.candidate));limits=structure.limit_flags(raw).set_index('date')
        ratio=qv.close/qv.close.rolling(20).mean();raw_lookup=raw.set_index('date');valid_pos={d:i for i,d in enumerate(f.date)}
        accepted=set();missing_limit=[]
        for i in sorted(independent):
            day=f.iloc[i].date
            if not '2020-01-01'<=day<='2024-12-31':continue
            if day not in limits.index:missing_limit.append(day);continue
            if bool(limits.loc[day,'reject_consecutive2']):continue
            if not (float(rv.iloc[i].close)<8 and float(ratio.iloc[i])<=.92):continue
            if day not in ordinal:raise ValueError('Signal missing from official calendar '+code+' '+day)
            pos=ordinal[day]+1;next_day=sessions[pos] if pos<len(sessions) else None;next_open=None
            if next_day is None:state='beyond_snapshot_calendar'
            elif next_day not in raw_lookup.index:state='missing_next_session_row'
            else:
                bar=raw_lookup.loc[next_day];status=pd.to_numeric(bar.tradestatus,errors='coerce')
                next_open=float(bar.open) if pd.notna(bar.open) else None
                if status==0:state='suspended_next_session'
                elif status==1 and pd.notna(bar.volume) and bar.volume>0 and pd.notna(bar.open) and bar.open>0:state='next_open_available';next_open=float(bar.open)
                else:state='nontradable_or_invalid_next_row'
            diagnostics={k:float(v) if pd.notna(v) else None for k,v in f.iloc[i].items() if k not in ['date','candidate','q_position']}
            outputs.append(dict(code=code,name=str(info_by_code[code]['name']),signal_date=day,entry_date=next_day,next_date=next_day,next_valid_open=bool(state=='next_open_available'),next_raw_open=next_open,next_state=state,raw_signal_close=float(rv.iloc[i].close),qfq_close_div_ma20=float(ratio.iloc[i]),ipo_date=ipo,**diagnostics))
            accepted.add(day)
        if missing_limit:raise ValueError('Unresolved historical limit evidence '+code+' '+str(missing_limit))
        window=f.date.between('2020-01-01','2024-12-31')
        stage_audit.append(dict(code=code,ipo_date=ipo,raw_bars=len(raw),raw_period_bars=int(raw.date.between('2020-01-01','2024-12-31').sum()),first_raw_date=raw.date.iloc[0] if len(raw) else None,last_raw_date=raw.date.iloc[-1] if len(raw) else None,valid_bars=len(f),valid_period_bars=int(window.sum()),base_candidates=int((f.candidate&window).sum()),independent_candidates=sum('2020-01-01'<=f.iloc[i].date<='2024-12-31' for i in independent),accepted=len(accepted)))
        for day in old.loc[old.code==code,'date']:
            if day in accepted:reason='retained'
            elif not '2020-01-01'<=day<='2024-12-31':reason='outside_scan_window'
            elif day<ipo:reason='before_ipo'
            elif day not in valid_pos:reason='missing_or_nonvalid_historical_bar'
            else:
                i=valid_pos[day]
                reason='base_structure_not_met' if not bool(f.iloc[i].candidate) else 'base_cooldown_rejected' if i not in independent else 'consecutive_down_limit_rejected' if day in limits.index and bool(limits.loc[day,'reject_consecutive2']) else 'raw_close_not_below_8' if not float(rv.iloc[i].close)<8 else 'qfq_close_ma20_not_at_most_092' if not float(ratio.iloc[i])<=.92 else 'unresolved_scan_stage'
            i=valid_pos.get(day)
            legacy_diagnostics.append(dict(code=code,signal_date=day,status=reason,current_base=bool(f.iloc[i].candidate) if i is not None else None,current_independent=i in independent if i is not None else None,current_raw_close=float(rv.iloc[i].close) if i is not None else None,current_qfq_close_div_ma20=float(ratio.iloc[i]) if i is not None and pd.notna(ratio.iloc[i]) else None))
        if code_number%300==0:print(json.dumps(dict(scanned_stocks=code_number,total=len(codes),structures_so_far=len(outputs))),flush=True)
    for code,day in sorted(oldkeys):
        if code not in codes:legacy_diagnostics.append(dict(code=code,signal_date=day,status='legacy_code_not_in_frozen_historical_mainboard'))
    result=pd.DataFrame(outputs).sort_values(['signal_date','code'])
    newkeys=set(zip(result.code,result.signal_date));kept=oldkeys&newkeys;added=newkeys-oldkeys;missing=oldkeys-newkeys
    legacy_dates={(r.code,r.date):r.entry_date for r in old.itertuples()}
    new_dates={(r.code,r.signal_date):r.entry_date for r in result.itertuples()}
    entry_diffs=[dict(code=c,signal_date=d,old_entry_date=legacy_dates[(c,d)],new_entry_date=new_dates[(c,d)]) for c,d in sorted(kept) if str(legacy_dates[(c,d)])!=str(new_dates[(c,d)])]
    result.to_csv(OUT/'FULL_SIGNALS.csv',index=False,encoding='utf-8-sig');result.to_parquet(OUT/'FULL_SIGNALS.parquet',index=False)
    pd.DataFrame(stage_audit).to_csv(OUT/'SCAN_STAGES.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(legacy_diagnostics).to_csv(OUT/'LEGACY_DIAGNOSTICS.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([dict(code=c,signal_date=d,comparison='retained' if (c,d) in kept else 'new_within_old947' if c in old947 else 'new_outside_old947') for c,d in sorted(newkeys)]+[dict(code=c,signal_date=d,comparison='missing_legacy') for c,d in sorted(missing)]).to_csv(OUT/'LEGACY_SET_COMPARISON.csv',index=False,encoding='utf-8-sig')
    save(OUT/'SUMMARY.json',dict(scope_stocks=len(codes),reference_scope_count=3336,stocks_with_period_raw=sum(r['raw_period_bars']>0 for r in stage_audit),stocks_with_period_valid=sum(r['valid_period_bars']>0 for r in stage_audit),no_period_raw_codes=[r['code'] for r in stage_audit if not r['raw_period_bars']],no_period_valid_codes=[r['code'] for r in stage_audit if not r['valid_period_bars']],signal_count=len(result),years={str(y):len(g) for y,g in result.groupby(result.signal_date.str[:4])},next_states=result.next_state.value_counts().to_dict(),legacy_unique_keys=len(oldkeys),legacy_reference_count=820,old947_scope_coverage=len(old947&set(codes)),old947_not_in_new_scope=sorted(old947-set(codes)),legacy_retained=len(kept),added_inside_old947=sum(c in old947 for c,d in added),added_outside_old947=sum(c not in old947 for c,d in added),legacy_missing=len(missing),legacy_missing_codes_outside_scope=sorted({c for c,d in missing if c not in codes}),entry_date_differences=entry_diffs,source_manifest_sha256=sha(manifest_path),structure_sha256=sha(ROOT/'structure.py'),protocol_sha256=sha(OUT/'PROTOCOL.json'),price_scale=manifest['price_scale'],rule_special_event_exclusions_applied=False,accounts_run=False,economic_returns_computed=False,classifications_read=False,company_actions_available=False))
    save(OUT/'INPUT_ACCESS_AUDIT.json',dict(boundary_version='public-pre2025-v2',input_root=str(area),manifest=str(manifest_path),manifest_sha256=sha(manifest_path),hash_checked_files=len(listing),universe_projection=[args.code_column,args.name_column,args.ipo_column],future_outDate_parsed=False,legacy_projection=['code','date','entry_date'],old947_source=manifest['old_pool']+' code membership only',post2024_prices_read=False,restricted_read=False,direction2_results_read=False,current_classification_read=False,accounts_read=False,writes_root=str(OUT),isolation='Logical path/hash guards and declared source inventory, not OS access isolation'))
    print(json.dumps(read(OUT/'SUMMARY.json'),ensure_ascii=False))

if __name__=='__main__':main()
