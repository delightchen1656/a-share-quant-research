"""Explicit alternate-source event semantics; missing dates never fabricated."""
import json
from pathlib import Path
from common import BASE,sha

STORE=BASE/'inputs_pre2025/corporate_eastmoney_january_v1'

def events_from_sources(records,overrides=None):
    overrides=overrides or {}
    events=[]
    date=lambda s:str(s)[:10] if s else None
    for r in records:
        if not r.get('ok'):continue
        p=STORE/r['file'];assert sha(p)==r['sha256']
        payload=json.loads(p.read_text(encoding='utf-8'))
        for row in payload['data']:
            ex=date(row['EX_DIVIDEND_DATE']);reg=date(row['EQUITY_RECORD_DATE'])
            assert ex.startswith(str(r['year'])) and r['year']<=2023
            cash=float(row.get('PRETAX_BONUS_RMB') or 0)/10
            bonus=float(row.get('BONUS_RATIO') or 0)/10
            transfer=float(row.get('IT_RATIO') or 0)/10
            key=r['symbol']+'_'+ex
            e=dict(event_id=key,symbol=r['symbol'],ex_date=ex,register_date=reg,
                cash_ps=cash,bonus_ps=bonus,transfer_ps=transfer,
                economic_cash_per_share=cash,economic_bonus_shares_per_share=bonus,economic_transfer_shares_per_share=transfer,
                quote_reference_cash_per_share=cash,quote_reference_share_multiplier=1+bonus+transfer,
                pay_date=None if cash else ex,listing_date=None if bonus or transfer else ex,
                source_sha256=r['sha256'],scope='conditional_ordinary_event_provider_not_certified_complete_ledger',
                source='Eastmoney_bounded_dividend_event_table',entitlement_class='ordinary_eligible_A_share_holder')
            o=overrides.get(key)
            if o:
                proof=Path(o['evidence_path']);assert sha(proof)==o['evidence_sha256']
                assert o['verification_status']=='verified_from_primary_issuer_announcement'
                for field in ['economic_cash_per_share','economic_bonus_shares_per_share','economic_transfer_shares_per_share',
                              'quote_reference_cash_per_share','quote_reference_share_multiplier','pay_date','listing_date']:
                    e[field]=o[field]
                e.update(cash_ps=e['economic_cash_per_share'],bonus_ps=e['economic_bonus_shares_per_share'],transfer_ps=e['economic_transfer_shares_per_share'],authority_evidence=o)
            reasons=[]
            if reg is None or not reg<ex:reasons.append('missing_or_invalid_record_date')
            if e['pay_date'] is None or e['pay_date']<ex:reasons.append('cash_payment_date_not_verified')
            if e['listing_date'] is None or e['listing_date']<ex:reasons.append('share_listing_date_not_verified')
            e.update(supported=not reasons,reason=';'.join(reasons))
            events.append(e)
    assert len({e['event_id'] for e in events})==len(events),'Ambiguous duplicate alternate events require review'
    return events
