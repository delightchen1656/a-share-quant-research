"""One-way posterior price-path audit, same fixed protocol as pre2025 table."""
from pathlib import Path
from datetime import datetime
import csv,hashlib,importlib.util,json,pickle,sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'沪深实盘工作台';BASE=ROOT/'沪深2研究'
CASES=ROOT/'沪深2研究/K线练习/frozen_inputs/cases'
PRE=ROOT/'archive/reports/holdout_restricted/hushen2_signal_paths/pre2025_20261028_164437'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    sys.path.insert(0,str(APP/'tracker'));market=load('posterior_path_market',APP/'tracker/market.py')
    health=market.health(APP/'tracker/data');end=pd.Timestamp(health['market_date'])
    market.pipeline_identity(health) # verifies selection/runtime/model identities
    out=ROOT/'archive/reports/holdout_restricted/hushen2_signal_paths'/datetime.now().strftime('post2024_%Y%m%d_%H%M%S');out.mkdir(parents=True)
    engine=out/'path_engine.py';engine.write_bytes((PRE/'path_engine.py').read_bytes());m=load('posterior_path_engine',engine)
    protected=[BASE/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',PRE/'summary_D0_D20.csv',PRE/'all_event_paths.csv']
    protected+=list((BASE/'model').glob('*.txt'));before={str(p):sha(p) for p in protected}
    manifest=json.loads((ROOT/'沪深2研究/K线练习/PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    assert sha(CASES/'INPUT_SIGNALS.parquet')==manifest['inputs']['frozen_inputs/cases/INPUT_SIGNALS.parquet']
    pack_sha=sha(CASES/'INPUT_PACK.pkl');assert pack_sha==manifest['inputs']['frozen_inputs/cases/INPUT_PACK.pkl']
    with (CASES/'INPUT_PACK.pkl').open('rb') as stream:pack=pickle.load(stream)
    signals=pd.read_parquet(CASES/'INPUT_SIGNALS.parquet');last_frozen=signals.date.max()
    signals=signals.loc[signals.date.between('2025-01-01',end)].copy();extensions=[]
    for day in [d for d in health['sessions'] if last_frozen<pd.Timestamp(d)<=end]:
        path=market.signal_cache_path(APP/'tracker/data',day)
        if not path.exists():raise RuntimeError('Missing frozen production signal cache '+day)
        payload=json.loads(path.read_text(encoding='utf-8'));items=payload['signals']
        assert payload['market_date']==day and market.signals_digest(items)==payload['signals_sha256']
        market.validate_signals(items,dict(health,market_date=day))
        # Construct only genuine saved signal rows; do not backfill missing ranks.
        extra=pd.DataFrame([dict(date=pd.Timestamp(day),symbol=x['symbol'],atr_pct=x['atr'],score=x['score'],factor='C04_NEW',close=x['trigger']) for x in items])
        signals=pd.concat([signals,extra],ignore_index=True)
        extensions.append(dict(day=day,path=str(path),sha256=sha(path),signals=len(items),pipeline_id=payload['pipeline_id']))
    signals=signals.sort_values(['date','symbol']).reset_index(drop=True)
    assert signals.atr_pct.ge(.025).all() and not signals.duplicated(['date','symbol']).any()
    signals.to_parquet(out/'FROZEN_POSTERIOR_SIGNALS.parquet',index=False)
    dates=pd.DatetimeIndex(pd.to_datetime([d for d in health['sessions'] if '2024-12-01'<=d<=str(end.date())]))
    assert dates.is_unique and dates[-1]==end
    pd.DataFrame(dict(date=dates)).to_parquet(out/'CALENDAR.parquet',index=False)
    quote_root=out/'inputs_post2024';quote_root.mkdir();quote_manifest=[];sources={}
    for symbol in sorted(signals.symbol.unique()):
        for mode in ('raw','qfq'):
            src=market.DATA/mode/symbol[-2:]/f'{symbol}.parquet';digest=sha(src)
            b=pd.read_parquet(src);b.date=pd.to_datetime(b.date)
            b=b.loc[b.date.between(dates[0],end)].sort_values('date')
            assert not b.date.duplicated().any()
            dest=quote_root/f'{symbol}_{mode}.parquet';b.to_parquet(dest,index=False)
            quote_manifest.append(dict(symbol=symbol,mode=mode,path=dest.name,sha256=sha(dest),source=str(src),source_sha256=digest))
            sources[str(src)]=digest
    save(out/'QUOTE_MANIFEST.json',quote_manifest)
    save(out/'PROTOCOL.json',dict(type='one-way posterior descriptive price-path audit; no optimization',
        start='2025-01-01',end=str(end.date()),signal_count=len(signals),frozen_signal_source_sha256=sha(CASES/'INPUT_SIGNALS.parquet'),
        pack_sha256=pack_sha,production_signal_extensions=extensions,calendar_sha256=sha(out/'CALENDAR.parquet'),
        engine_sha256=sha(engine),same_engine_as_pre2025=sha(engine)==sha(PRE/'path_engine.py'),
        quotes_manifest_sha256=sha(out/'QUOTE_MANIFEST.json'),protected_before=before,
        price_measure='same qfq ratios/strict next exchange session open,not an account return',
        denominator='available valid observations per horizon/metric;retain incomplete signals;no future tail',
        posterior_not_blind='Production selection has already been informed by post2024 evidence; no new blind-test claim'))
    action_access=[];normalized=[]
    class FrozenActions:
        def window(self,code,start,stop):
            symbol=code+('.SH' if code.startswith('6') else '.SZ');records=[];issues=[]
            for year in range(start.year,stop.year+1):
                key=f'{symbol}/{year}';rows=[]
                for (day,s),values in pack['actions'].items():
                    if s!=symbol or day.year!=year:continue
                    for v in values:
                        assert 'pay' in v and 'release' in v and 'taxable_stock' in v
                        reserve=v['stock']-v['taxable_stock'];assert reserve>=-1e-12
                        rows.append(dict(dividOperateDate=str(day.date()),dividCashPsBeforeTax=v['cash'],dividStocksPs=v['taxable_stock'],
                            dividReserveToStockPs=reserve,dividPayDate=str(v['pay'].date()),dividStockMarketDate=str(v['release'].date()),source=v.get('source')))
                if key not in pack['known']:issues.append(key+':not_in_verified_frozen_coverage')
                elif not rows:issues.append(key+':frozen_coverage_metadata_only_no_original_empty_response_claim')
                action_access.append(dict(key=key,known_in_frozen_pack=key in pack['known'],normalized_nonempty_records=len(rows)))
                records.extend(r for r in rows if start<=pd.Timestamp(r['dividOperateDate'])<=stop)
            return records,issues
    actions=FrozenActions();summary=m.Summary(20);checks=[];audits=[];writer=None
    qlookup={(r['symbol'],r['mode']):r for r in quote_manifest}
    def quote(symbol,mode):
        info=qlookup[symbol,mode];p=quote_root/info['path'];assert sha(p)==info['sha256']
        q=pd.read_parquet(p).set_index('date').reindex(dates)
        for k in ['open','high','low','close','preclose','volume','amount','tradestatus','isST']:q[k]=pd.to_numeric(q[k],errors='coerce') if k in q else np.nan
        return q
    cols=dict(id='signal_id',code='code',signal_date='signal_date',entry_date='entry_date',entry_raw_open='next_raw_open',next_valid_open='next_valid_open')
    with (out/'all_event_paths.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        for symbol,group in signals.groupby('symbol',sort=True):
            raw=quote(symbol,'raw');qfq=quote(symbol,'qfq')
            for r in group.itertuples():
                i=dates.get_loc(r.date)+1;entry=dates[i] if i<len(dates) else pd.NaT
                active=pd.notna(entry) and raw.iloc[i].tradestatus==1 and m.positive(raw.iloc[i].volume) and m.positive(raw.iloc[i].open) and m.positive(qfq.iloc[i].open)
                event=dict(signal_id=f'{r.date:%Y-%m-%d}_{symbol}',code=symbol[:6],symbol=symbol,signal_date=r.date,
                    entry_date=entry,next_raw_open=float(raw.iloc[i].open) if pd.notna(entry) else None,next_valid_open=bool(active))
                row,aa,check=m.make_event_path(event,dates,raw,qfq,actions,cols,20)
                if writer is None:writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader()
                writer.writerow(row);summary.add(row);checks.append(check);audits.extend(aa)
    result=pd.DataFrame(summary.finish());result.to_csv(out/'summary_D0_D20.csv',index=False,encoding='utf-8-sig')
    save(out/'ACTION_AUDIT.json',dict(source_pack_sha256=pack_sha,normalized_records_not_new_supplier_queries=True,coverage=action_access,ex_reference_checks=audits))
    save(out/'EVENT_CHECKS.json',checks)
    pre=pd.read_csv(PRE/'summary_D0_D20.csv');comp=pre.merge(result,on=['h','label'],suffixes=('_pre','_post'))
    comp.to_csv(out/'COMPARISON.csv',index=False,encoding='utf-8-sig')
    final=market.health(APP/'tracker/data');assert final['audit_sha256']==health['audit_sha256']
    assert all(sha(Path(p))==v for p,v in before.items()) and all(sha(Path(p))==v for p,v in sources.items())
    save(out/'STATUS.json',dict(status='computed_pending_independent_check',asof=str(end.date()),signals=len(signals),
        signal_years=signals.groupby(signals.date.dt.year).size().to_dict(),protected_unchanged=True,
        unresolved_declared_action_records=sum(not r['verified'] for r in audits)))
    print('OUTPUT',out,flush=True)
    print(result[['label','total_events','valid_n_close','average_daily_high','average_cumulative_high','average_close_return','close_win_rate','unexplained_adjustment','action_blocked']].to_string(index=False),flush=True)


if __name__=='__main__':main()
