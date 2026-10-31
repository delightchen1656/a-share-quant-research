"""Frozen Hushen2 signals: strict next-session open, adjusted D0..D20 paths."""
from pathlib import Path
from datetime import datetime
import importlib.util,json,hashlib,argparse,pickle
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
PRICE=ROOT/'研究尝试/方向1_超跌反弹/inputs_pre2025/full_mainboard'
ACTION=ROOT/'研究尝试/方向1_超跌反弹/inputs_pre2025/full_mainboard_path_actions'
CASES=ROOT/'沪深2研究/K线练习/frozen_inputs/cases'
BASE=ROOT/'沪深2研究'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--resolve-actions',action='store_true');parser.add_argument('--frozen-actions',action='store_true');args=parser.parse_args()
    out=args.output or ROOT/'archive/reports/holdout_restricted/hushen2_signal_paths'/datetime.now().strftime('pre2025_%Y%m%d_%H%M%S');out=out.resolve();out.mkdir(parents=True,exist_ok=bool(args.output))
    engine_source=ROOT/'研究尝试/方向1_超跌反弹/scope_full_mainboard/path_D0_D20/path_engine.py'
    engine=out/'path_engine.py';engine.write_bytes(engine_source.read_bytes())
    spec=importlib.util.spec_from_file_location('hushen2_path_engine',engine);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    action_root=ACTION
    if args.resolve_actions:
        # Target only issuer-years whose observed adjustment lacks a receipt.
        wide=pd.read_csv(out/'all_event_paths.csv',dtype={'code':str});keys=set()
        for h in range(21):
            for row in wide.loc[wide[f'd{h}_unexplained_adjustment'],['code',f'd{h}_date']].itertuples(index=False,name=None):
                code,day=row;year=pd.Timestamp(day).year;assert year<=2024
                keys.add(f'{code}.{"SH" if code.startswith("6") else "SZ"}/{year}')
        action_root=out/'action_inputs_pre2025';action_root.mkdir(exist_ok=True)
        manifest=json.loads((ACTION/'MANIFEST.json').read_text(encoding='utf-8-sig'))
        for info in manifest['files']:
            src=ACTION/info['path'];assert sha(src)==info['sha256']
            dest=action_root/info['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(src.read_bytes())
        existing={r['key'] for r in manifest['responses']}
        frozen=None
        if args.frozen_actions:
            package=json.loads((ROOT/'沪深2研究/K线练习/PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
            pack_sha=sha(CASES/'INPUT_PACK.pkl')
            assert pack_sha==package['inputs']['frozen_inputs/cases/INPUT_PACK.pkl']
            with (CASES/'INPUT_PACK.pkl').open('rb') as stream:frozen=pickle.load(stream)
        else:
            import socket
            socket.setdefaulttimeout(20)
            import baostock as bs
            assert bs.login().error_code=='0'
        try:
            for i,key in enumerate(sorted(keys-existing),1):
                symbol,year=key.split('/');dest=action_root/'responses'/f'{symbol[:6]}_{year}.json'
                records=[]
                if frozen is not None:
                    assert key in frozen['known']
                    for (ex,s),values in frozen['actions'].items():
                        if s!=symbol or ex.year!=int(year):continue
                        for v in values:
                            assert 'pay' in v and 'release' in v and 'taxable_stock' in v
                            reserve=v['stock']-v['taxable_stock'];assert reserve>=-1e-12
                            records.append(dict(dividOperateDate=str(ex.date()),dividCashPsBeforeTax=v['cash'],
                                dividStocksPs=v['taxable_stock'],dividReserveToStockPs=reserve,
                                dividPayDate=str(v['pay'].date()),dividStockMarketDate=str(v['release'].date()),
                                frozen_original_source=v.get('source')))
                    if not records:
                        print('UNRESOLVED_NO_FROZEN_ACTION_RECORD',key,flush=True)
                        continue # preserve unknown labels, never fabricate an empty response
                    save(dest,dict(key=key,error_code='0',records=records,source='normalized existing verified frozen action records; not a new supplier response',
                        frozen_pack_sha256=pack_sha,scope='Only this issuer/year<=2024; independently verify ex-date reference with raw/qfq'))
                else:
                    r=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate')
                    while r.error_code=='0' and r.next():records.append(dict(zip(r.fields,r.get_row_data())))
                    assert r.error_code=='0'
                    save(dest,dict(key=key,error_code=r.error_code,records=records,fields=r.fields,fetched_at=datetime.now().isoformat(),source='BaoStock query_dividend_data operate'))
                rel=dest.relative_to(action_root).as_posix();digest=sha(dest)
                manifest['responses'].append(dict(key=key,code=symbol[:6],year=int(year),path=rel,sha256=digest,status='success'))
                manifest['files'].append(dict(path=rel,sha256=digest))
                if i%20==0:print('ACTION_RECEIPTS',i,'/',len(keys-existing),flush=True)
        finally:
            if frozen is None:bs.logout()
        save(action_root/'MANIFEST.json',manifest)
        save(out/'ACTION_RESOLUTION.json',dict(keys=sorted(keys),new_supplier_queries=0 if frozen is not None else len(keys-existing),
            source_mode='existing_verified_frozen_action_normalization' if frozen is not None else 'supplier_query',
            cutoff='2024-12-31',source_manifest_sha256=sha(ACTION/'MANIFEST.json'),combined_manifest_sha256=sha(action_root/'MANIFEST.json')))
    selection=json.loads((BASE/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['signal_filter']['minimum_atr']==.025 and not selection['selection']['signal_filter']['refill']
    package=json.loads((ROOT/'沪深2研究/K线练习/PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    signals_path=CASES/'INPUT_SIGNALS.parquet'
    assert sha(signals_path)==package['inputs']['frozen_inputs/cases/INPUT_SIGNALS.parquet']
    signals=pd.read_parquet(signals_path);signals=signals.loc[signals.date.between('2020-01-01','2024-12-31')].copy()
    assert signals.atr_pct.ge(.025).all() and not signals.duplicated(['date','symbol']).any()
    access=[];price=m.Whitelist(PRICE,sha(PRICE/'MANIFEST.json'),access)
    cal=price.read(price.manifest['calendar']);dates=pd.DatetimeIndex(pd.to_datetime(cal.date.astype(str))).sort_values()
    qm=price.read(price.manifest['quote_manifest']);qi={(str(x['code']).zfill(6),x['mode']):x for x in qm['files']}
    events=[]
    for symbol,group in signals.groupby('symbol',sort=True):
        code=symbol[:6];raw=m.read_quote(price,qi[code,'raw'],dates);qfq=m.read_quote(price,qi[code,'qfq'],dates)
        for row in group.itertuples():
            index=dates.get_loc(row.date)+1;day=dates[index] if index<len(dates) else pd.NaT
            if pd.notna(day):
                a=raw.loc[day];b=qfq.loc[day]
                valid=a.tradestatus==1 and m.positive(a.volume) and m.positive(a.open) and m.positive(b.open)
                op=float(a.open) if pd.notna(a.open) else None
            else:valid=False;op=None
            events.append(dict(signal_id=f'{row.date:%Y-%m-%d}_{symbol}',code=code,symbol=symbol,
                signal_date=f'{row.date:%Y-%m-%d}',entry_date=str(day.date()) if pd.notna(day) else None,
                next_raw_open=op,next_valid_open=bool(valid),next_state='active' if valid else 'unavailable',
                atr_pct=row.atr_pct,score=row.score))
    cohort=out/'COHORT.csv';pd.DataFrame(events).sort_values(['signal_date','symbol']).to_csv(cohort,index=False,encoding='utf-8-sig')
    config=dict(prices=dict(root=str(PRICE),manifest_sha256=sha(PRICE/'MANIFEST.json')),
        actions=dict(root=str(action_root),manifest_sha256=sha(action_root/'MANIFEST.json')),
        cohort=dict(path=str(cohort),sha256=sha(cohort),expected_rows=len(events),columns=dict(id='signal_id',code='code',
            signal_date='signal_date',entry_date='entry_date',entry_raw_open='next_raw_open',next_valid_open='next_valid_open',next_state='next_state')),
        output_dir=str(out),horizon=20,event_filename='all_event_paths.csv',analysis_type='frozen_hushen2_signals_qfq_path_not_account')
    save(out/'CONFIG.json',config)
    protected={str(p):sha(p) for p in [BASE/'CURRENT_SELECTION.json',ROOT/'沪深实盘工作台/CURRENT_SELECTION.json',signals_path]}
    save(out/'PROTOCOL.json',dict(signals_source=str(signals_path),signals_source_sha256=sha(signals_path),
        selection_sha256=sha(BASE/'CURRENT_SELECTION.json'),signal_count=len(signals),
        per_year=signals.groupby(signals.date.dt.year).size().to_dict(),
        anchor='strict next official trading session open; no delayed entry if suspended',
        metrics='qfq_high/qfq_entry_open-1; cummax per signal first then mean; qfq_close/qfq_entry_open-1; close>0 win',
        calendar_offset='formal trading sessions; suspended observations not compressed',
        cutoff='2024-12-31; late paths right censored, not filled from2025',
        denominator='available valid observations separately per horizon and metric; no complete-path cohort selection',
        excludes='no account,slots,entry trigger,fees,stoploss,takeprofit or retraining',
        method_source_sha256=sha(engine_source),protected_before=protected))
    m.freeze_config(out/'CONFIG.json');print('OUTPUT',out,'SIGNALS',len(events),flush=True)
    result=m.run_cohort(out/'CONFIG.json')
    wide=pd.read_csv(out/'all_event_paths.csv',dtype={'code':str});summary=pd.DataFrame(result['summary'])
    # Independent recomputation from saved row-level normalized price fields.
    failures=[];max_delta=0.;denominators=[]
    for h in range(21):
        k=f'd{h}_';s=summary.loc[summary.h.eq(h)].iloc[0]
        for metric,key,nkey in [('high_return','average_daily_high','valid_n_high'),('cumulative_high_return','average_cumulative_high','valid_n_cumulative'),('close_return','average_close_return','valid_n_close')]:
            values=pd.to_numeric(wide[k+metric],errors='coerce').dropna()
            assert len(values)==int(s[nkey])
            if len(values):max_delta=max(max_delta,abs(values.mean()-float(s[key])))
            denominators.append(dict(h=h,metric=metric,valid_n=len(values),total_signals=len(events)))
        close=pd.to_numeric(wide[k+'close_return'],errors='coerce').dropna()
        assert abs(close.gt(0).mean()-s.close_win_rate)<1e-12
        # Direct qfq ratio check; cumulative path check uses valid high prefixes.
        anchor=pd.to_numeric(wide.entry_qfq_open,errors='coerce')
        for field,quote in [('high_return','qfq_high'),('close_return','qfq_close')]:
            v=pd.to_numeric(wide[k+field],errors='coerce');expected=pd.to_numeric(wide[k+quote],errors='coerce')/anchor-1
            assert (v-expected).abs().max()<1e-12
    assert max_delta<1e-12
    assert all(sha(Path(p))==v for p,v in protected.items())
    pd.DataFrame(denominators).to_csv(out/'DENOMINATORS.csv',index=False,encoding='utf-8-sig')
    save(out/'PREPARATION_ACCESS.json',access)
    audit=json.loads((out/'company_action_audit.json').read_text(encoding='utf-8'))
    save(out/'VERIFICATION.json',dict(status='passed_with_disclosed_missing_labels',signals=len(events),
        anchor_valid=int(wide.anchor_valid.sum()),max_summary_error=max_delta,protected_unchanged=True,
        qfq_price_observation_only=True,action_response_gaps=sum(bool(x['issues']) for x in audit['coverage']),
        unresolved_action_records=sum(not x['verified'] for x in audit['records'])))
    print(summary[['label','total_events','valid_n_high','valid_n_cumulative','valid_n_close',
        'average_daily_high','average_cumulative_high','average_close_return','close_win_rate']].to_string(index=False),flush=True)


if __name__=='__main__':main()
