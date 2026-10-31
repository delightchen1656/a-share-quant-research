"""Separate shareholder economics from exchange quote-reference adjustments. No strategy tuning."""
from pathlib import Path
import json
import datetime
import shutil
import hashlib

BASE=Path(__file__).resolve().parent.parent
SRC=BASE/'src_account_v1'
DEST=BASE/'src_account_v1_1'
OLD=BASE/'audits/holdout_restricted/monday_account_backtest_v1'
OUT=BASE/'audits/holdout_restricted/monday_account_backtest_v1_1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'repair_registration.json').exists()
    for name in ['common.py','execution.py','portfolio.py','account_validation.py','company_data.py','checks.py','run.py','report_and_freeze.py']:
        text=(SRC/name).read_text(encoding='utf-8')
        if name=='common.py':
            text=text.replace('audits/holdout_restricted/monday_account_backtest_v1\'', 'audits/holdout_restricted/monday_account_backtest_v1_1\'')
        if name=='report_and_freeze.py':
            text=text.replace("'frozen_engine_v1'","'frozen_engine_v1_1'")
            text=text.replace('周一选股买卖规则V1：开发账户回测','周一选股买卖规则V1：账簿V1.1开发回归回测')
            text=text.replace("'sources']", "'sources']")
        (DEST/name).write_text(text,encoding='utf-8')
    spec=json.loads((OLD/'spec.json').read_text(encoding='utf-8'))
    spec.update(bookkeeping_version='V1.1_separate_economic_and_quote_reference',
        reason='Generic accounting semantic defect: actual shareholder cash/share distributions may differ from virtual ex-price reference coefficients. No posterior performance was returned to optimizer.',
        strategy_model_factors_parameters_and_signal_artifacts_unchanged=True,
        failedV1_preserved=True,correction='Separate economic_*fromquote_reference_*; use actual economics for claims/shares/cash, reference coefficients only for preclose checks and suspended reference marks.',
        authority_overrides='Auditor supplies independently verified primary issuer/exchange evidence for economic and reference terms with separate hashes and applicability; never infer holder economics from quote fit.')
    (OUT/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ['scores.parquet','weekly_schedule.parquet','company_collection_audit.json','company_query_requests.json']:
        shutil.copy2(OLD/name,OUT/name)
    execution=DEST/'execution.py'
    source=execution.read_text(encoding='utf-8')
    source+='''\n\ndef economic_terms(event):
    return (float(event.get('economic_cash_per_share',event['cash_ps'])),
            float(event.get('economic_bonus_shares_per_share',event['bonus_ps'])),
            float(event.get('economic_transfer_shares_per_share',event['transfer_ps'])))


def reference_terms(event):
    cash,bonus,transfer=economic_terms(event)
    return (float(event.get('quote_reference_cash_per_share',cash)),
            float(event.get('quote_reference_share_multiplier',1+bonus+transfer)))


def reference_adjust(mark,event):
    cash,multiplier=reference_terms(event)
    if not np.isfinite(cash) or not np.isfinite(multiplier) or cash<0 or multiplier<=0:
        raise ValueError('unverified_quote_reference_terms')
    return (float(mark)-cash)/multiplier
'''
    execution.write_text(source,encoding='utf-8')
    portfolio=DEST/'portfolio.py'
    source=portfolio.read_text(encoding='utf-8')
    source=source.replace('entitlement,price_band,band_contradiction','entitlement,price_band,band_contradiction,economic_terms,reference_terms,reference_adjust')
    source=source.replace("p['mark']=(p['mark']-event['cash_ps'])/(1+event['bonus_ps']+event['transfer_ps'])","p['mark']=reference_adjust(p['mark'],event)")
    source=source.replace("cash_ps=sum(e['cash_ps'] for e in today)","cash_ps=sum(reference_terms(e)[0] for e in today)")
    source=source.replace("np.prod([1+e['bonus_ps']+e['transfer_ps'] for e in today])","np.prod([reference_terms(e)[1] for e in today])")
    source=source.replace("amounts=entitlement(p['qty'],event['cash_ps'],event['bonus_ps'],event['transfer_ps'])","amounts=entitlement(p['qty'],*economic_terms(event))")
    portfolio.write_text(source,encoding='utf-8')
    independent=DEST/'account_validation.py'
    source=independent.read_text(encoding='utf-8')
    source='from execution import economic_terms,reference_adjust\n'+source
    source=source.replace("marks[s]=(marks[s]-e['cash_ps'])/(1+e['bonus_ps']+e['transfer_ps'])","marks[s]=reference_adjust(marks[s],e)")
    source=source.replace("extra=qty*(e['bonus_ps']+e['transfer_ps'])","economic_cash,economic_bonus,economic_transfer=economic_terms(e)\n                    extra=qty*(economic_bonus+economic_transfer)")
    source=source.replace("cash=qty*e['cash_ps']","cash=qty*economic_cash")
    independent.write_text(source,encoding='utf-8')
    company=DEST/'company_data.py'
    source=company.read_text(encoding='utf-8')
    source=source.replace('def normalize(records,quotes=None,store=None):','def normalize(records,quotes=None,store=None,overrides=None):')
    source=source.replace('    quotes=quotes or Quotes()','    quotes=quotes or Quotes()\n    overrides=overrides or {}')
    old="""            bonus=stocks
            transfer=reserve
            semantic='separate_bonus_and_reserve_components'"""
    new="""            bonus=stocks
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
                cash=float(override['economic_cash_per_share'])
                bonus=float(override['economic_bonus_shares_per_share'])
                transfer=float(override['economic_transfer_shares_per_share'])
                reference_cash=float(override['quote_reference_cash_per_share'])
                reference_multiplier=float(override['quote_reference_share_multiplier'])
                assert np.isfinite([cash,bonus,transfer,reference_cash,reference_multiplier]).all()
                assert min(cash,bonus,transfer,reference_cash)>=0 and reference_multiplier>0
                semantic='authoritatively_separate_shareholder_economics_and_quote_reference'"""
    assert old in source
    source=source.replace(old,new)
    source=source.replace("expected=(before['close']-cash)/(1+stocks+reserve)","expected=(before['close']-reference_cash)/reference_multiplier")
    source=source.replace("if reserve>0 and stocks>=reserve and abs(alternative-after['preclose'])<=.015:","if override is None and reserve>0 and stocks>=reserve and abs(alternative-after['preclose'])<=.015:")
    source=source.replace("bonus=stocks-reserve\n                            semantic=", "bonus=stocks-reserve\n                            reference_multiplier=1+stocks\n                            semantic=")
    source=source.replace("share_field_semantics=semantic,source_sha256=record['sha256'],", "share_field_semantics=semantic,source_sha256=record['sha256'],\n                 economic_cash_per_share=cash,economic_bonus_shares_per_share=bonus,economic_transfer_shares_per_share=transfer,\n                 quote_reference_cash_per_share=reference_cash,quote_reference_share_multiplier=reference_multiplier,\n                 entitlement_class='ordinary_eligible_A_share_holder',authority_evidence=authority,")
    source=source.replace("fields=['cash_ps','bonus_ps','transfer_ps','register_date','pay_date','listing_date']", "fields=['cash_ps','bonus_ps','transfer_ps','register_date','pay_date','listing_date','quote_reference_cash_per_share','quote_reference_share_multiplier']")
    company.write_text(source,encoding='utf-8')
    registration=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_repaired_posterior_evaluation=True,
        original_failed_engine_sha256='ca256c7c86f370147578415db07df04a56cd88c06603a9b84c8b64db685ece01',
        no_return_ranking_or_event_values_from_posterior_to_optimizer=True,
        only_abstract_accounting_defect_type_returned=True,trading_rules_unchanged_sha256=spec['rules_sha256'],
        code=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(DEST.glob('*.py'))])
    (OUT/'repair_registration.json').write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
    print('V1.1bookkeeping repair registered;V1and its failure records preserved.',flush=True)


if __name__=='__main__':
    main()
