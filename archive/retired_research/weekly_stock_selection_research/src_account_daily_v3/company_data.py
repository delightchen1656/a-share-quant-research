from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys
import json
import datetime
import numpy as np
import pandas as pd
from common import BASE,ROOT,AUDIT,sha,dump
from portfolio import Quotes

STORE=BASE/'inputs_pre2025/corporate_provider_v1'
UPDATER=None


def initialize(store_path=None):
    global UPDATER,STORE
    if store_path is not None:
        STORE=Path(store_path)
    sys.path.insert(0,str(ROOT))
    from tools import daily_market_update
    UPDATER=daily_market_update
    UPDATER.safe_login()


def query(task):
    symbol,year=task
    target=STORE/f'{symbol}_{year}.parquet'
    audit=STORE/f'{symbol}_{year}.json'
    if target.exists() and audit.exists():
        old=json.loads(audit.read_text(encoding='utf-8'))
        if old.get('ok') and old.get('sha256')==sha(target):
            return old
    code=symbol[-2:].lower()+'.'+symbol[:6]
    error=None
    for attempt in range(2):
        try:
            result=UPDATER.bs.query_dividend_data(code,year=str(year),yearType='operate')
            frame=UPDATER.result_frame(result,context=f'new_weekly_dividend_{symbol}_{year}')
            frame.to_parquet(target,index=False)
            payload=dict(symbol=symbol,year=int(year),ok=True,rows=len(frame),fields=list(frame.columns),
                         sha256=sha(target),year_type='operate',source='BaoStock query_dividend_data independent new collection',
                         query_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),zero_rows_not_proof_of_complete_company_action_history=True)
            dump(audit,payload)
            return payload
        except Exception as exc:
            error=repr(exc)
            try:
                UPDATER.bs.logout()
                UPDATER.safe_login()
            except Exception:
                pass
    payload=dict(symbol=symbol,year=int(year),ok=False,error=error)
    dump(audit,payload)
    return payload


def date_value(value):
    parsed=pd.to_datetime(value,errors='coerce')
    return str(parsed.date()) if pd.notna(parsed) else None


def number(row,name):
    value=pd.to_numeric(row.get(name,''),errors='coerce')
    return float(value) if pd.notna(value) else 0.


def normalize(records,quotes=None,store=None,overrides=None):
    quotes=quotes or Quotes()
    overrides=overrides or {}
    source_store=Path(store) if store is not None else STORE
    raw_events=[]
    for record in records:
        if not record['ok']:
            continue
        frame=pd.read_parquet(source_store/f"{record['symbol']}_{record['year']}.parquet")
        for _,row in frame.iterrows():
            ex=date_value(row.get('dividOperateDate'))
            if ex is None or not ex.startswith(str(record['year'])):
                continue
            cash=number(row,'dividCashPsBeforeTax')
            stocks=number(row,'dividStocksPs')
            reserve=number(row,'dividReserveToStockPs')
            if cash==stocks==reserve==0:
                continue
            reg=date_value(row.get('dividRegistDate',row.get('dividRegisterDate')))
            pay=date_value(row.get('dividPayDate')) if cash else ex
            listed=date_value(row.get('dividStockMarketDate',row.get('dividStocksMarketDate'))) if stocks or reserve else ex
            reasons=[]
            if reg is None or not reg<ex:
                reasons.append('missing_or_invalid_record_date')
            if pay is None or pay<ex:
                reasons.append('missing_or_invalid_payment_date')
            if listed is None or listed<ex:
                reasons.append('missing_or_invalid_share_listing_date')
            bonus=stocks
            transfer=reserve
            semantic='separate_bonus_and_reserve_components'
            override=overrides.get(record['symbol']+'_'+ex)
            reference_cash=cash
            reference_multiplier=1+stocks+reserve
            authority=None
            if override is not None:
                status=override.get('verification_status')
                assert status=='verified_from_primary_evidence' or (status=='synthetic_fixture' and record['symbol'].startswith('SYNTH'))
                assert override.get('entitlement_class')=='ordinary_eligible_A_share_holder'
                authority=override['evidence']
                assert all(len(authority[role]['sha256'])==64 for role in ['economic','quote_reference'])
                for role in ['economic','quote_reference']:
                    proof=Path(authority[role]['path'])
                    assert proof.is_file() and sha(proof)==authority[role]['sha256'],'Missing or changed primary evidence file'
                cash=float(override['economic_cash_per_share'])
                bonus=float(override['economic_bonus_shares_per_share'])
                transfer=float(override['economic_transfer_shares_per_share'])
                reference_cash=float(override['quote_reference_cash_per_share'])
                reference_multiplier=float(override['quote_reference_share_multiplier'])
                assert np.isfinite([cash,bonus,transfer,reference_cash,reference_multiplier]).all()
                assert min(cash,bonus,transfer,reference_cash)>=0 and reference_multiplier>0
                semantic='authoritatively_separate_shareholder_economics_and_quote_reference'
            if pd.Timestamp(ex) in quotes.days:
                i=int(quotes.days.get_loc(pd.Timestamp(ex)))
                before=quotes.bar(record['symbol'],i-1)
                after=quotes.bar(record['symbol'],i)
                if not np.isfinite(before['close']) or not np.isfinite(after['preclose']):
                    reasons.append('reference_quotes_unavailable')
                else:
                    expected=(before['close']-reference_cash)/reference_multiplier
                    if abs(expected-after['preclose'])>.015:
                        alternative=(before['close']-cash)/(1+stocks)
                        if override is None and reserve>0 and stocks>=reserve and abs(alternative-after['preclose'])<=.015:
                            bonus=stocks-reserve
                            reference_multiplier=1+stocks
                            semantic='provider_stock_field_contains_total_share_distribution_conditional_quote_check'
                        else:
                            reasons.append('generic_entitlement_reference_mismatch')
            else:
                reasons.append('exdate_not_in_development_calendar')
            raw_events.append(dict(symbol=record['symbol'],ex_date=ex,register_date=reg,pay_date=pay,listing_date=listed,
                 cash_ps=cash,bonus_ps=bonus,transfer_ps=transfer,supported=not reasons,reason=';'.join(reasons),
                 share_field_semantics=semantic,source_sha256=record['sha256'],
                 economic_cash_per_share=cash,economic_bonus_shares_per_share=bonus,economic_transfer_shares_per_share=transfer,
                 quote_reference_cash_per_share=reference_cash,quote_reference_share_multiplier=reference_multiplier,
                 entitlement_class='ordinary_eligible_A_share_holder',authority_evidence=authority,
                 scope='conditional_ordinary_provider_event_not_certified_complete_economic_ledger'))
    by={}
    for event in raw_events:
        by.setdefault((event['symbol'],event['ex_date']),[]).append(event)
    events=[]
    for key,group in by.items():
        fields=['cash_ps','bonus_ps','transfer_ps','register_date','pay_date','listing_date','quote_reference_cash_per_share','quote_reference_share_multiplier']
        signatures={tuple(e[k] for k in fields) for e in group}
        event=group[0].copy()
        event['source_rows']=len(group)
        if len(signatures)>1:
            event['supported']=False
            event['reason']+=';ambiguous_multiple_event_rows'
        event['event_id']=key[0]+'_'+key[1]
        events.append(event)
    return events


def main():
    STORE.mkdir(parents=True,exist_ok=True)
    if '--normalize-only' in sys.argv:
        results=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))['sources']
        events=normalize(results)
        dump(AUDIT/'company_events_conditional.json',events)
        print('conditional events',len(events),'unsupported',sum(not e['supported'] for e in events),flush=True)
        print(pd.Series([e['reason'] for e in events if not e['supported']]).value_counts().to_string(),flush=True)
        return
    requests=json.loads((AUDIT/'company_query_requests.json').read_text(encoding='utf-8'))['requests']
    results=[]
    with ProcessPoolExecutor(max_workers=6,initializer=initialize) as pool:
        for i,result in enumerate(pool.map(query,requests,chunksize=8),1):
            results.append(result)
            if i%200==0:
                print(f'company source queries {i}/{len(requests)}',flush=True)
    dump(AUDIT/'company_collection_audit.json',dict(requested=len(requests),successful=sum(r['ok'] for r in results),
         failed=[r for r in results if not r['ok']],no_old_research_ledger_reused=True,
         event_rows=sum(r.get('rows',0) for r in results),sources=results))
    events=normalize(results)
    dump(AUDIT/'company_events_conditional.json',events)
    print('conditional events',len(events),'unsupported',sum(not e['supported'] for e in events),flush=True)
    print('field example',next((r['fields'] for r in results if r.get('rows',0)),[]),flush=True)


if __name__=='__main__':
    main()
