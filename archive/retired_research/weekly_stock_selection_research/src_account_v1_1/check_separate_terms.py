import json
import math
import pandas as pd
from common import BASE,AUDIT,sha,dump,fee,install_development_guard
from checks import ToyQuotes
from execution import reference_adjust,economic_terms
from portfolio import simulate,Quotes
from company_data import normalize
from account_validation import independent_account


def main():
    install_development_guard()
    fixture=AUDIT/'synthetic_fixtures'
    fixture.mkdir(exist_ok=True)
    evidence=fixture/'SYNTHETIC_ONLY.txt'
    evidence.write_text('Synthetic field-separation fixture only; not issuer or historical market evidence.',encoding='utf-8')
    q=ToyQuotes()
    closes=[10.,10.,7.1,7.1,7.2,7.2]
    pres=[10.,10.,(10-.08)/1.4,7.1,7.1,7.2]
    for bar,c,p in zip(q.bars,closes,pres):
        bar.update(open=c,high=c,low=c,close=c,preclose=p)
    q.bars[1]['open']=10.
    row=dict(dividOperateDate='2021-01-05',dividRegistDate='2021-01-04',dividPayDate='2021-01-11',dividStockMarketDate='2021-01-06',
             dividCashPsBeforeTax='.1',dividStocksPs='.2',dividReserveToStockPs='.3')
    raw=fixture/'SYNTH_A_2021.parquet'
    pd.DataFrame([row]).to_parquet(raw,index=False)
    records=[dict(symbol='SYNTH_A',year=2021,ok=True,sha256=sha(raw))]
    no_override=normalize(records,quotes=q,store=fixture)
    assert not no_override[0]['supported']
    override=dict(verification_status='synthetic_fixture',entitlement_class='ordinary_eligible_A_share_holder',
        economic_cash_per_share=.1,economic_bonus_shares_per_share=.2,economic_transfer_shares_per_share=.3,
        quote_reference_cash_per_share=.08,quote_reference_share_multiplier=1.4,
        evidence={role:dict(path=str(evidence),sha256=sha(evidence)) for role in ['economic','quote_reference']})
    events=normalize(records,quotes=q,store=fixture,overrides={'SYNTH_A_2021-01-05':override})
    event=events[0]
    assert event['supported'] and economic_terms(event)==(.1,.2,.3)
    assert event['quote_reference_share_multiplier']==1.4
    score=pd.DataFrame([dict(method='TEST',symbol='SYNTH_A',monday='2021-01-04',rank=1)])
    plan=pd.DataFrame([dict(signal_date='2020-12-31',monday='2021-01-04',tuesday='2021-01-05',year=2021)])
    result=simulate('TEST',score,q,events,plan=plan)
    t=result['trades'].iloc[0]
    assert result['complete'] and t.gross_dividend==900 and t.entitled_extra_shares==4500 and t.sold_shares==13500
    expected=7200-fee(90000,'buy','2021-01-04')-fee(63900,'sell','2021-01-05')-fee(32400,'sell','2021-01-12')
    assert math.isclose(t.pnl,expected,abs_tol=1e-7)
    independent_account(result,events,q)
    q2=ToyQuotes()
    q2.bars=[b.copy() for b in q.bars]
    q2.bars[2].update(active=False,status='0')
    halted=simulate('TEST',score,q2,events,plan=plan)
    assert halted['complete']
    inventory=halted['daily'].loc[halted['daily'].date.eq('2021-01-05'),'inventory'].iloc[0]
    assert math.isclose(inventory,13500*reference_adjust(10.,event),abs_tol=1e-7)
    independent_account(halted,events,q2)
    # Actual pre2024raw provider records are unchanged; the new explicit fields
    # must reproduce the previous economic terms/status for every old event.
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    actual=normalize(collection['sources'],quotes=Quotes())
    old=json.loads((BASE/'audits/holdout_restricted/monday_account_backtest_v1/company_events_conditional.json').read_text(encoding='utf-8'))
    old_by={e['event_id']:e for e in old}
    assert len(actual)==len(old)
    for event in actual:
        previous=old_by[event['event_id']]
        for key in ['cash_ps','bonus_ps','transfer_ps','register_date','ex_date','pay_date','listing_date','supported']:
            assert event[key]==previous[key],(event['event_id'],key)
    dump(AUDIT/'company_events_conditional.json',actual)
    dump(AUDIT/'separate_terms_validation.json',dict(passed=True,
        synthetic_economic_cash_and_share_rights_separate_from_virtual_reference=True,
        synthetic_suspended_mark_uses_quote_reference_not_holder_economics=True,
        synthetic_independent_full_account_replays=True,
        no_posterior_event_values_or_performance_used=True,all_pre2024provider_events_regression_matched=True))
    print('Separate economic/reference synthetic checks and all pre2024event regressions passed.',flush=True)


if __name__=='__main__':
    main()
