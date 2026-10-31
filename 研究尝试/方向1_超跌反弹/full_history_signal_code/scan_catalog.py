"""Frozen-input, interval-configurable direction1 mathematical signal scanner.

Import is side-effect free. No account/path-return, classification, retirement
filter, network access or hardcoded ST regime is implemented. Price and daily
limit-rate inputs, the original feature module, and output path are explicit.

Public pure APIs: infer_down_limits(raw, rate_table), scan_frames(...).
File API: scan_catalog(config_or_path); CLI: python scan_catalog.py --config FILE.
See CONFIG_SCHEMA.json for the two supported rate-table input modes.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,re
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
import numpy as np
import pandas as pd

SIGNAL_COLUMNS=['id','signal_id','code','name','signal_date','entry_date','next_date','next_valid_open','next_raw_open','entry_raw_open','next_state','raw_signal_close','qfq_close_div_ma20','ipo_date','raw_signal_open','raw_signal_high','raw_signal_low','raw_signal_preclose','qfq_signal_open','qfq_signal_high','qfq_signal_low','qfq_signal_close','next_qfq_open','signal_limit_rate','signal_down_limit','limit_evidence_status','ret20','ret5','below_ma20','below_ma60','low_recent','rebound_from_low','body','upper','lower','volume_ratio','last3_volume_ratio','close_over_prev_high']
EVIDENCE_COLUMNS=['code','date','evidence_state','rate','down_price','down_close','pair_state','reject_consecutive2','evidence_id']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()
def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def json_value(x):
    if isinstance(x,dict):return {str(k):json_value(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [json_value(v) for v in x]
    if isinstance(x,(bool,np.bool_)):return bool(x)
    if isinstance(x,np.integer):return int(x)
    if isinstance(x,(float,np.floating)):return float(x) if np.isfinite(x) else None
    if x is pd.NA or x is pd.NaT:return None
    if isinstance(x,pd.Timestamp):return x.strftime('%Y-%m-%d')
    return x
def save_json(path,value):Path(path).write_text(json.dumps(json_value(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def code6(value):
    m=re.search(r'\d{6}',str(value))
    if not m:raise ValueError('Invalid code '+str(value))
    return m.group()
def day(value):
    x=pd.to_datetime(value,errors='coerce')
    if pd.isna(x):raise ValueError('Invalid date '+str(value))
    return x.strftime('%Y-%m-%d')
def days(series):
    x=pd.to_datetime(series,errors='coerce')
    if x.isna().any():raise ValueError('Invalid date column')
    return x.dt.strftime('%Y-%m-%d')
def positive(value):
    try:return pd.notna(value) and np.isfinite(float(value)) and float(value)>0
    except (ValueError,TypeError):return False
def true(value):return value is True or str(value).lower() in ['true','1','1.0']
def normalize_frame(frame,cutoff):
    out=frame.copy();out['date']=days(out.date)
    if out.date.duplicated().any():raise ValueError('Duplicate price dates')
    for c in ['open','high','low','close','preclose','volume','amount','tradestatus']:
        if c in out:out[c]=pd.to_numeric(out[c],errors='coerce')
    return out.loc[out.date<=cutoff].sort_values('date').reset_index(drop=True)

def infer_down_limits(raw,rate_table):
    """Original pair/rolling20 mathematics with explicit daily rate evidence.

    Rate table columns: date, limit_rate; optional limit_exempt/evidence_id.
    Explicit exemption fixes down=False. Unknown rate propagates via three-valued
    AND/ANY; any proven pair rejects, otherwise possible unknown pairs are unknown.
    Original limit-eligible bars require valid status/volume/open/preclose.
    No isST column or time-regime knowledge is used here.
    """
    rate=rate_table.copy()
    if 'date' not in rate or 'limit_rate' not in rate:raise ValueError('Daily rate table needs date/limit_rate')
    rate['date']=days(rate.date)
    if rate.date.duplicated().any():raise ValueError('Duplicate daily limit-rate evidence')
    lookup=rate.set_index('date').to_dict('index')
    good=(pd.to_numeric(raw.tradestatus,errors='coerce')==1)&raw.volume.gt(0)&raw.open.gt(0)&raw.preclose.gt(0)
    bars=raw.loc[good].reset_index(drop=True);records=[];pair_states=[];previous_down=False
    for i,row in enumerate(bars.itertuples()):
        info=lookup.get(row.date);price=None;down=None;value=None;eid=None
        if info is None:status='missing_limit_rate'
        elif true(info.get('exempt',info.get('limit_exempt',False))):
            status='explicit_no_limit_exemption';down=False;eid=info.get('evidence',info.get('evidence_id'))
        else:
            eid=info.get('evidence',info.get('evidence_id'));value=info.get('limit_rate')
            if not positive(value) or float(value)>=1:status='invalid_limit_rate'
            else:
                status='verified_injected_rate';value=float(value)
                price=float((Decimal(str(row.preclose))*(Decimal(1)-Decimal(str(value)))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
                down=bool(row.close<=price+.005) if positive(row.close) else None
                if down is None:status='invalid_limit_close'
        pair=False if i==0 or down is False or previous_down is False else True if down is True and previous_down is True else None
        pair_states.append(pair);window=pair_states[max(0,i-19):i+1]
        reject=True if any(p is True for p in window) else None if any(p is None for p in window) else False
        records.append(dict(date=row.date,evidence_state=status,rate=value,down_price=price,down_close=down,pair_state=pair,reject_consecutive2=reject,evidence_id=eid))
        previous_down=down
    # Object dtype preserves Python bool/None tri-state without NaN coercion.
    out=pd.DataFrame(records,columns=EVIDENCE_COLUMNS[1:],dtype=object)
    return out

def scan_frames(code,name,ipo_date,raw,qfq,calendar,rate_table,structure,signal_start,signal_cutoff):
    """Pure per-code scan. Inputs are supplied objects; no file reads/writes."""
    code=code6(code);start=day(signal_start);cutoff=day(signal_cutoff);ipo=day(ipo_date)
    if start>cutoff:raise ValueError('signal_start after signal_cutoff')
    calendar=days(pd.Series(calendar,dtype='object')).tolist()
    if calendar!=sorted(set(calendar)):raise ValueError('Calendar must be ordered and unique')
    ordinal={d:i for i,d in enumerate(calendar)}
    r=normalize_frame(raw,cutoff);q=normalize_frame(qfq,cutoff)
    if not r.date.equals(q.date):raise ValueError('Raw/qfq date mismatch '+code)
    r=r.loc[r.date>=ipo].reset_index(drop=True);q=q.loc[q.date>=ipo].reset_index(drop=True)
    f,qv,rv=structure.scan(q,r);kept=structure.independent(f.candidate)
    limits=infer_down_limits(r,rate_table);limit_lookup=limits.set_index('date').to_dict('index')
    ratio=qv.close/qv.close.rolling(20).mean();rlookup=r.set_index('date');qlookup=q.set_index('date')
    outputs=[];unresolved=[];evidence=[]
    for row in limits.to_dict('records'):
        if row['evidence_state'] not in ['verified_injected_rate','explicit_no_limit_exemption'] and start<=row['date']<=cutoff:evidence.append(dict(code=code,**row))
    # A valid feature bar without a valid limit price reference is explicit evidence loss.
    for bar in rv.itertuples():
        if start<=bar.date<=cutoff and bar.date not in limit_lookup:evidence.append(dict(code=code,date=bar.date,evidence_state='missing_or_invalid_preclose_reference',rate=None,down_price=None,down_close=None,pair_state=None,reject_consecutive2=None,evidence_id=None))
    for i in kept:
        date=f.iloc[i].date
        if not start<=date<=cutoff:continue
        info=limit_lookup.get(date)
        # Pipeline: cooldown first, then limit exclusion, then price/MA gates.
        if info is not None and info['reject_consecutive2'] is True:continue
        if not (float(rv.iloc[i].close)<8 and float(ratio.iloc[i])<=.92):continue
        if info is None or info['reject_consecutive2'] is None:
            unresolved.append(dict(code=code,name=name,signal_date=date,reason='missing_limit_price_reference' if info is None else 'unresolved_consecutive_pair_window',raw_signal_close=float(rv.iloc[i].close),qfq_close_div_ma20=float(ratio.iloc[i])))
            continue
        if date not in ordinal:raise ValueError('Signal date absent from formal calendar '+code+' '+date)
        pos=ordinal[date]+1;entry=calendar[pos] if pos<len(calendar) else None;opening=None;qo=None;valid=False
        if entry is None:state='pending_calendar_next_session_unavailable'
        elif entry>cutoff:state='pending_after_price_cutoff'
        elif entry not in rlookup.index:state='missing_next_session_row'
        else:
            bar=rlookup.loc[entry];opening=float(bar.open) if pd.notna(bar.open) else None
            qo=float(qlookup.loc[entry,'open']) if pd.notna(qlookup.loc[entry,'open']) else None
            if bar.tradestatus==0 or (pd.notna(bar.volume) and bar.volume==0):state='suspended_next_session'
            elif bar.tradestatus==1 and positive(bar.volume) and positive(bar.open):state='next_open_available';valid=True
            else:state='nontradable_or_invalid_next_row'
        sr=rv.iloc[i];sq=qv.iloc[i]
        diagnostics={key:float(value) if pd.notna(value) else None for key,value in f.iloc[i].items() if key not in ['date','candidate','q_position']}
        outputs.append(dict(id=code+'_'+date,signal_id=code+'_'+date,code=code,name=str(name),signal_date=date,entry_date=entry,next_date=entry,next_valid_open=bool(valid),next_raw_open=opening,entry_raw_open=opening if valid else None,next_state=state,raw_signal_close=float(sr.close),qfq_close_div_ma20=float(ratio.iloc[i]),ipo_date=ipo,raw_signal_open=float(sr.open),raw_signal_high=float(sr.high),raw_signal_low=float(sr.low),raw_signal_preclose=float(sr.preclose),qfq_signal_open=float(sq.open),qfq_signal_high=float(sq.high),qfq_signal_low=float(sq.low),qfq_signal_close=float(sq.close),next_qfq_open=qo,signal_limit_rate=info['rate'],signal_down_limit=info['down_price'],limit_evidence_status=info['evidence_state'],**diagnostics))
    coverage=dict(code=code,ipo_date=ipo,raw_bars=len(r),valid_warmup_and_period_bars=len(f),valid_period_bars=int(f.date.between(start,cutoff).sum()),base_candidates=int((f.candidate&f.date.between(start,cutoff)).sum()),signals=len(outputs),unresolved_candidates=len(unresolved),no_evidence_days=len(evidence))
    return dict(signals=outputs,unresolved_candidates=unresolved,no_evidence=evidence,coverage=coverage)

class FrozenFiles:
    def __init__(self,root,manifest_hash,access,manifest_name='MANIFEST.json'):
        self.root=Path(root).resolve();self.access=access;path=self.root/manifest_name
        if sha(path)!=manifest_hash:raise ValueError('Manifest hash mismatch '+str(path))
        self.manifest=read_json(path);self.entries={x['path'].replace('\\','/'):x['sha256'] for x in self.manifest['files']}
        self.access.append(dict(path=str(path),sha256=manifest_hash))
    def path(self,relative):
        rel=str(relative).replace('\\','/');path=(self.root/rel).resolve()
        if not path.is_relative_to(self.root) or rel not in self.entries:raise ValueError('Outside frozen whitelist '+rel)
        if sha(path)!=self.entries[rel]:raise ValueError('File hash mismatch '+rel)
        self.access.append(dict(path=str(path),sha256=self.entries[rel]));return path
    def read(self,relative,columns=None):
        path=self.path(relative)
        if path.suffix=='.parquet':return pd.read_parquet(path,columns=columns)
        if path.suffix=='.csv':return pd.read_csv(path,usecols=columns,dtype={'code':str})
        return read_json(path)

class DailyRates:
    def __init__(self,config,access):
        self.config=config;self.access=access;self.table=None;self.reader=None
        if config['kind']=='single_table':
            path=Path(config['path']).resolve()
            if sha(path)!=config['sha256']:raise ValueError('Limit-rate table hash mismatch')
            self.access.append(dict(path=str(path),sha256=config['sha256']))
            table=pd.read_parquet(path) if path.suffix=='.parquet' else pd.read_csv(path,dtype={'code':str})
            table['code']=table.code.map(code6);table['date']=days(table.date)
            if table.duplicated(['code','date']).any():raise ValueError('Duplicate code/day limit rates')
            self.table=table.set_index('code').sort_index()
        elif config['kind']=='per_code_manifest':
            self.reader=FrozenFiles(config['root'],config['manifest_sha256'],access,config.get('manifest_name','MANIFEST.json'))
            entries=self.reader.manifest['files'];self.bycode={code6(x['code']):x['path'] for x in entries}
            if len(self.bycode)!=len(entries):raise ValueError('Duplicate per-code rate files')
        else:raise ValueError('Unsupported explicit limit-rate input kind')
    def for_code(self,code):
        if self.table is not None:
            if code not in self.table.index:return pd.DataFrame(columns=['date','limit_rate'])
            return self.table.loc[[code]].reset_index(drop=True)
        if code not in self.bycode:return pd.DataFrame(columns=['date','limit_rate'])
        value=self.reader.read(self.bycode[code])
        if 'code' in value and set(value.code.map(code6))!={code}:raise ValueError('Rate file code mismatch '+code)
        return value

def load_structure(config,access=None):
    path=Path(config['path']).resolve()
    if sha(path)!=config['sha256']:raise ValueError('Original algorithm module hash mismatch')
    if access is not None:access.append(dict(path=str(path),sha256=config['sha256']))
    spec=importlib.util.spec_from_file_location('explicit_frozen_direction1_structure',path);module=importlib.util.module_from_spec(spec)
    # Execute approved source without generating a pyc in its source directory.
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    if not callable(getattr(module,'scan',None)) or not callable(getattr(module,'independent',None)):raise ValueError('Feature module interface invalid')
    return module

def scan_catalog(config_or_path):
    cfg=read_json(config_or_path) if isinstance(config_or_path,(str,Path)) else config_or_path
    start=day(cfg['signal_start']);cutoff=day(cfg['signal_cutoff']);access=[]
    prices=FrozenFiles(cfg['prices']['root'],cfg['prices']['manifest_sha256'],access,cfg['prices'].get('manifest_name','MANIFEST.json'))
    input_cutoff=day(prices.manifest['cutoff'])
    if start>cutoff or cutoff>input_cutoff:raise ValueError('Requested signal interval outside frozen price cutoff')
    out=Path(cfg['output_dir']).resolve()
    if out==prices.root or out.is_relative_to(prices.root):raise ValueError('Output must not modify price input root')
    targets=['FULL_SIGNALS.csv','UNRESOLVED_CANDIDATES.csv','NO_EVIDENCE.csv','SCAN_COVERAGE.csv','SCAN_AUDIT.json','RUN_FREEZE.json']
    if not cfg.get('overwrite',False) and any((out/name).exists() for name in targets):raise FileExistsError('Existing output; choose a new output_dir or explicitly authorize overwrite')
    out.mkdir(parents=True,exist_ok=True)
    save_json(out/'RUN_FREEZE.json',dict(config=cfg,scanner_sha256=sha(Path(__file__)),before_scan=True))
    structure=load_structure(cfg['structure'],access)
    limits_cfg=cfg.get('limits')
    if limits_cfg is None:
        relative=prices.manifest.get('daily_limit_rates')
        if not relative:raise ValueError('Explicit limit-rate input required in config.limits or frozen manifest.daily_limit_rates')
        limits_cfg=dict(kind='single_table',path=str(prices.path(relative)),sha256=prices.entries[relative])
    rates=DailyRates(limits_cfg,access)
    columns=cfg.get('universe_columns',dict(code='code',name='name',ipo_date='ipo_date'))
    meta=prices.read(prices.manifest['universe'],list(columns.values())).rename(columns={value:key for key,value in columns.items()})
    meta['code']=meta.code.map(code6)
    if meta.code.duplicated().any():raise ValueError('Duplicate universe code')
    calendar=prices.read(prices.manifest['calendar'],['date']);calendar=days(calendar.date).tolist()
    if calendar!=sorted(set(calendar)):raise ValueError('Invalid formal calendar')
    qm=prices.read(prices.manifest['quote_manifest']);lookup={(code6(x['code']),x['mode']):x for x in qm['files']}
    if len(lookup)!=len(qm['files']):raise ValueError('Duplicate quote manifest code/mode')
    for item in qm['files']:
        if prices.entries.get(item['path'])!=item['sha256']:raise ValueError('Quote metadata not bound to frozen inputs')
    signals=[];unresolved=[];evidence=[];coverage=[]
    for number,row in enumerate(meta.sort_values('code').itertuples(index=False),1):
        code=row.code
        if pd.isna(pd.to_datetime(row.ipo_date,errors='coerce')):
            evidence.append(dict(code=code,date=None,evidence_state='unknown_ipo_date'));coverage.append(dict(code=code,unresolved_scope='unknown_ipo_date'));continue
        frames=[]
        for mode in ['raw','qfq']:
            if (code,mode) not in lookup:raise ValueError('Missing frozen quote file '+code+' '+mode)
            z=prices.read(lookup[code,mode]['path'])
            if len(z) and days(z.date).max()>input_cutoff:raise ValueError('Price file exceeds input manifest cutoff')
            frames.append(z)
        raw,qfq=frames
        result=scan_frames(code,row.name,row.ipo_date,raw,qfq,calendar,rates.for_code(code),structure,start,cutoff)
        signals.extend(result['signals']);unresolved.extend(result['unresolved_candidates']);evidence.extend(result['no_evidence']);coverage.append(result['coverage'])
        if number%300==0:print(json.dumps(dict(scanned_codes=number,total=len(meta),signals=len(signals),unresolved_candidates=len(unresolved))),flush=True)
    result=pd.DataFrame(signals,columns=SIGNAL_COLUMNS).sort_values(['signal_date','code'])
    if result.duplicated(['code','signal_date']).any():raise RuntimeError('Duplicate code/day signal')
    result['next_valid_open']=result.next_valid_open.astype(bool)
    result.to_csv(out/'FULL_SIGNALS.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(unresolved,columns=['code','name','signal_date','reason','raw_signal_close','qfq_close_div_ma20']).to_csv(out/'UNRESOLVED_CANDIDATES.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(evidence,columns=EVIDENCE_COLUMNS).to_csv(out/'NO_EVIDENCE.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(coverage).to_csv(out/'SCAN_COVERAGE.csv',index=False,encoding='utf-8-sig')
    audit=dict(signal_start=start,signal_cutoff=cutoff,input_price_cutoff=input_cutoff,universe_codes=len(meta),signals=len(result),unresolved_candidates=len(unresolved),no_evidence_code_days=len(evidence),next_states=result.next_state.value_counts().to_dict(),source_access=access,structure_sha256=cfg['structure']['sha256'],scanner_sha256=sha(Path(__file__)),limit_rule_input=limits_cfg,no_retirement_or_current_status_filter=True,no_hardcoded_ST_rate=True,no_account_or_return_labels=True,missing_evidence_never_assumed_false=True)
    save_json(out/'SCAN_AUDIT.json',audit)
    return dict(output_dir=str(out),signal_count=len(result),unresolved_count=len(unresolved),no_evidence_count=len(evidence))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);args=parser.parse_args()
    print(json.dumps(scan_catalog(args.config),ensure_ascii=False))

if __name__=='__main__':main()
