"""Small synthetic checks and one fixed pre2025 set replay, no future inputs.

The legacy ST fixture below is deliberately NOT production rate policy. It is
used only for the exactly frozen <=2024 parity check against old limit_flags.
"""
import argparse,importlib.util,json
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('isolated_scan_catalog',HERE/'scan_catalog.py');scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)

def synthetic(structure):
    ds=pd.bdate_range('2024-01-02',periods=30).strftime('%Y-%m-%d').tolist()
    raw=pd.DataFrame(dict(date=ds,open=10.,high=10.,low=9.,close=10.,preclose=10.,volume=100.,amount=1000.,tradestatus=1,isST=0))
    raw.loc[0,['preclose','close']]=[10.05,9.05];raw.loc[1,['preclose','close']]=[9.05,8.15]
    rate=pd.DataFrame(dict(date=ds,limit_rate=.10,evidence_id='synthetic'))
    flags=scanner.infer_down_limits(raw,rate)
    assert flags.iloc[0].down_price==9.05 and flags.iloc[1].down_price==8.15
    assert flags.iloc[1].reject_consecutive2 is True and flags.iloc[20].reject_consecutive2 is True and flags.iloc[21].reject_consecutive2 is False
    legacy=structure.limit_flags(raw)
    assert flags.reject_consecutive2.tolist()==legacy.reject_consecutive2.tolist()
    # Explicit rate supersedes any status field: no ST policy is in production.
    alternative=raw.copy();alternative['isST']=1;alternative['preclose']=10.;alternative['close']=8.2
    injected=pd.DataFrame(dict(date=ds,limit_rate=.20))
    actual=scanner.infer_down_limits(alternative,injected)
    assert actual.iloc[0].down_price==8. and actual.down_close.eq(False).all()
    exemption=pd.DataFrame(dict(date=ds,limit_rate=np.nan,exempt=True,evidence='synthetic_explicit_exemption'))
    assert scanner.infer_down_limits(alternative,exemption).down_close.eq(False).all()
    missing=rate.loc[rate.date!=ds[1]]
    unknown=scanner.infer_down_limits(raw,missing)
    assert unknown.iloc[1].evidence_state=='missing_limit_rate' and unknown.iloc[1].reject_consecutive2 is None
    assert unknown.iloc[20].reject_consecutive2 is None and unknown.iloc[21].reject_consecutive2 is False
    # Real feature function + controlled synthetic candidate dates checks order.
    class Fixture:
        independent=staticmethod(structure.independent)
        def __init__(self,candidates):self.candidates=candidates
        def scan(self,q,r):
            f,qv,rv=structure.scan(q,r);f['candidate']=f.date.isin(self.candidates);return f,qv,rv
    bars=pd.DataFrame(dict(date=ds,open=10.,high=11.,low=9.,close=10.,preclose=10.,volume=100.,amount=1000.,tradestatus=1,isST=0))
    adjusted=bars.copy();bars.loc[21,'close']=9.;bars.loc[27,'close']=5.;adjusted.loc[[21,27],'close']=5.
    result=scanner.scan_frames('000001','synthetic',ds[0],bars,adjusted,ds,rate,Fixture([ds[21],ds[27]]),ds[0],ds[-1])
    assert len(result['signals'])==0  # earlier base blocks later, even though earlier price fails
    pending_raw=bars.iloc[:23].copy();pending_q=pending_raw.copy()
    pending_raw.loc[21,'close']=5.;pending_q.loc[21,'close']=5.
    pending_raw.loc[22,['open','high','close']]=[99.,99.,99.];pending_q.loc[22,['open','high','close']]=[99.,99.,99.]
    fixture=Fixture([ds[21]])
    result=scanner.scan_frames('000001','synthetic',ds[0],pending_raw,pending_q,ds[:23],rate,fixture,ds[0],ds[21])
    event=result['signals'][0]
    assert event['entry_date']==ds[22] and event['next_state']=='pending_after_price_cutoff' and event['next_raw_open'] is None and event['next_valid_open'] is False
    result=scanner.scan_frames('000001','synthetic',ds[0],pending_raw,pending_q,ds[:22],rate,fixture,ds[0],ds[21])
    assert result['signals'][0]['entry_date'] is None and result['signals'][0]['next_state']=='pending_calendar_next_session_unavailable'
    suspended=pending_raw.copy();suspended.loc[22,['tradestatus','volume']]=[0,0]
    result=scanner.scan_frames('000001','synthetic',ds[0],suspended,pending_q,ds[:23],rate,fixture,ds[0],ds[22])
    assert result['signals'][0]['next_state']=='suspended_next_session' and result['signals'][0]['next_valid_open'] is False
    # Unknown code/day price-limit evidence is not silently a confirmed signal.
    unresolved_rates=rate.loc[~rate.date.isin([ds[20],ds[21]])]
    deep=pending_raw.copy();deep.loc[[20,21],['preclose','close']]=[10.,5.]
    result=scanner.scan_frames('000001','synthetic',ds[0],deep,pending_q,ds[:23],unresolved_rates,Fixture([ds[21]]),ds[0],ds[21])
    assert not result['signals'] and len(result['unresolved_candidates'])==1 and result['no_evidence']
    return dict(passed=True,checks=['HALF_UP cent rounding','close<=down+.005 and pair rolling20 parity','injected rate overrides status with no production ST policy','explicit exemption','unknown evidence three-valued propagation and expiration','base cooldown before price gate','future calendar pending without future price use','calendar-tail pending','suspension retained as no-entry state','unresolved candidate separated'])

def legacy_rates_fixture(raw):
    """Old-period-only fixture. NEVER import into or use as production policy."""
    st=pd.to_numeric(raw.isST,errors='coerce')
    return pd.DataFrame(dict(date=raw.date,limit_rate=st.map({0:.10,1:.05}),evidence_id='old_pre2025_ST_fixture_only'))

def parity(root,manifest_hash,structure,legacy_cohort,legacy_hash):
    if manifest_hash!='8d1c78aa55e7667462a95fa3a8e87fd4b14af4075a1b3e2d14ca713503d9f7c3':raise ValueError('This isolated parity harness only authorizes the existing pre2025 snapshot')
    access=[];reader=scanner.FrozenFiles(root,manifest_hash,access)
    if reader.manifest['cutoff']!='2024-12-31':raise ValueError('No new full-history inputs in this test')
    if scanner.sha(legacy_cohort)!=legacy_hash or legacy_hash!='70ea8125a426c3d7a54aa39fcbe01e5bc1f71c6190e17fbd346bdf76b41843f7':raise ValueError('Original cohort hash mismatch')
    meta=reader.read(reader.manifest['universe'],['code','name','ipoDate']);meta['code']=meta.code.map(scanner.code6)
    cal=reader.read(reader.manifest['calendar'],['date']);calendar=scanner.days(cal.date).tolist()
    qm=reader.read(reader.manifest['quote_manifest']);lookup={(x['code'],x['mode']):x for x in qm['files']}
    outputs=[];unresolved=[];coverage=[];flags_checked=0
    for n,row in enumerate(meta.sort_values('code').itertuples(index=False),1):
        raw=reader.read(lookup[row.code,'raw']['path']);qfq=reader.read(lookup[row.code,'qfq']['path'])
        for frame in [raw,qfq]:
            if len(frame) and scanner.days(frame.date).max()>'2024-12-31':raise ValueError('Unexpected later price data')
        rates=legacy_rates_fixture(raw)
        # Small deterministic direct-flag check; full 3336-code event-set check below.
        if n<=3:
            normalized=scanner.normalize_frame(raw,'2024-12-31');normalized=normalized.loc[normalized.date>=scanner.day(row.ipoDate)].reset_index(drop=True)
            explicit=scanner.infer_down_limits(normalized,rates);old=structure.limit_flags(normalized)
            assert explicit.date.tolist()==old.date.tolist()
            assert explicit.down_close.tolist()==old.inferred_down_close.tolist()
            assert explicit.reject_consecutive2.tolist()==old.reject_consecutive2.tolist();flags_checked+=len(explicit)
        result=scanner.scan_frames(row.code,row.name,row.ipoDate,raw,qfq,calendar,rates,structure,'2020-01-01','2024-12-31')
        outputs.extend(result['signals']);unresolved.extend(result['unresolved_candidates']);coverage.append(result['coverage'])
        if n%300==0:print(json.dumps(dict(pre2025_codes=n,signals=len(outputs))),flush=True)
    result=pd.DataFrame(outputs).sort_values(['signal_date','code']).reset_index(drop=True)
    old=pd.read_csv(legacy_cohort,usecols=['code','signal_date','entry_date','next_valid_open','next_raw_open','next_state'],dtype={'code':str}).sort_values(['signal_date','code']).reset_index(drop=True)
    keys=lambda x:set(zip(x.code,x.signal_date))
    assert keys(result)==keys(old) and len(result)==len(old)==3805 and not unresolved
    merged=result.merge(old,on=['code','signal_date'],suffixes=('_new','_old'),validate='one_to_one')
    for field in ['entry_date','next_valid_open','next_state']:assert merged[field+'_new'].fillna('').equals(merged[field+'_old'].fillna(''))
    assert np.allclose(merged.next_raw_open_new,merged.next_raw_open_old,equal_nan=True,atol=1e-12,rtol=0)
    assert scanner.sha(legacy_cohort)==legacy_hash
    out=HERE/'pre2025_self_check';out.mkdir(exist_ok=True)
    result.to_csv(out/'FULL_SIGNALS.csv',index=False,encoding='utf-8-sig');pd.DataFrame(coverage).to_csv(out/'SCAN_COVERAGE.csv',index=False,encoding='utf-8-sig')
    scanner.save_json(out/'ACCESS_AUDIT.json',dict(input_root=str(Path(root).resolve()),manifest_sha256=manifest_hash,source_access=access,read_columns_legacy=['code','signal_date','entry_date','next_valid_open','next_raw_open','next_state'],only_pre2025=True,new_full_history_inputs=False,restricted_inputs=False,classification_or_software_or_other_results=False,rate_fixture_scope='Only old frozen <=2024 isST mapping for parity; NOT in production scanner',original_cohort_unchanged=True))
    return dict(passed=True,scope_codes=len(meta),signals=len(result),exact_code_date_set_equal=True,entry_dates_states_and_bool_equal=True,entry_raw_prices_equal=True,unresolved_candidates=0,legacy_limit_bars_checked=flags_checked,original_3805_source_unchanged=True,price_manifest_sha256=manifest_hash,legacy_source_sha256=legacy_hash)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--structure-module',required=True);parser.add_argument('--structure-hash',required=True);parser.add_argument('--pre2025-parity',action='store_true');parser.add_argument('--input-root');parser.add_argument('--manifest-hash');parser.add_argument('--legacy-cohort');parser.add_argument('--legacy-hash');args=parser.parse_args()
    structure=scanner.load_structure(dict(path=args.structure_module,sha256=args.structure_hash))
    result={'synthetic':synthetic(structure)}
    scanner.save_json(HERE/'SYNTHETIC_CHECKS.json',result['synthetic']);print(json.dumps(result['synthetic']),flush=True)
    if args.pre2025_parity:result['pre2025_parity']=parity(args.input_root,args.manifest_hash,structure,args.legacy_cohort,args.legacy_hash)
    scanner.save_json(HERE/'TEST_RESULTS.json',result);print(json.dumps(result),flush=True)

if __name__=='__main__':main()
