"""Register an account replay of the already fixed trading rules; preserve all previous files."""
from pathlib import Path
import json
import datetime
import hashlib

BASE=Path(__file__).resolve().parent.parent
SRC=BASE/'src'
DEST=BASE/'src_account_v1'
OUT=BASE/'audits/holdout_restricted/monday_account_backtest_v1'
OLD=BASE/'audits/holdout_restricted/research_v1'
RULES=BASE/'audits/holdout_restricted/monday_trading_rules_v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'registration.json').exists()
    rules=json.loads((RULES/'RULES.json').read_text(encoding='utf-8'))
    spec=dict(factors=rules['model']['features'],methods=[{'id':'long120'},{'id':'anchor11'}],
        authorization='User asks to backtest registered buy/sell rules. Development account replay first; later identical frozen-code posterior account audit by original subagent, no feedback.',
        rules_sha256=sha(RULES/'RULES.json'),initial_cash=1000000,execution_start='2021-01-01',execution_end='2023-12-31',
        development_signal_mode='Use saved v5annual forward top10scores, each year trained only before that year. Never apply final2023fitted model to earlier years. Factor choice already observed these development years, so not independent validation.',
        posterior_signal_mode='After code/account checks freeze, original auditor uses fixed end2023models and same prior2025-2026snapshots/cutoff. Posterior results returned only as paths/images to user, never tuning.',
        fixed_parameters=True,top10_no_fallback=True,preauction_quantity_before_open=True,
        budget_reservation='Allocate all candidate budget buckets before any opening fill; a failed bucket and price savings are not redistributed that auction.',
        historical_bands='Ordinary mainboard10%;ST5%through2026-07-05,10%from2026-07-06. Rebuild using actual date/ST/preclose plus0.01tick. IPO/relisting/no-limit exceptions are unsupported and must be detected/reconciled, not silently treated as normal.',
        band_semantics='Conditional rule reconstruction, not certified daily exchange band feed. Check held/traded daily extremes for contradictions; record unknown cases instead of deleting trades.',
        auction_semantics='OHLC conditional quote proxy only, no auction depth/queue/cancellation proof; account completeness conditional on price and action assumptions.',
        company_actions='Only same-project independently sourced provider raw cache reused; validate held stock-year evidence, record/ex/payment/listing dates and share totals. Missing evidence remains unknown.',
        dividend_tax='Trading taxes deducted; personal dividend withholding not deducted, gross dividend treatment disclosed.',
        no_optimization='Do not change model, timing, count, limits, capacity, stop/target or fee assumptions after viewing account outcomes.',
        no_posterior_reads=True)
    (OUT/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    common=(SRC/'common.py').read_text(encoding='utf-8').replace("audits/holdout_restricted/research_v1","audits/holdout_restricted/monday_account_backtest_v1")
    common += '''\n\ndef install_development_guard():
    import sys
    def audit(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,Path)):
            path=str(args[0]).replace('\\\\','/').lower()
            if 'restricted_audit_2025_2026' in path or 'posterior_review' in path:
                raise PermissionError('Account development cannot open posterior results')
    sys.addaudithook(audit)
'''
    (DEST/'common.py').write_text(common,encoding='utf-8')
    # This study's own company-source collection, not another strategy ledger.
    (DEST/'company_data.py').write_text((SRC/'company_data.py').read_text(encoding='utf-8'),encoding='utf-8')
    from_source=(SRC/'run_comparison.py').read_text(encoding='utf-8')
    head=from_source[from_source.index('def aggregate'):from_source.index('def market_reference')]
    independent=from_source[from_source.index('def independent_account'):from_source.index('\ndef main():')]
    (DEST/'account_validation.py').write_text('import math\nimport numpy as np\nimport pandas as pd\n\n'+head+'\n'+independent,encoding='utf-8')
    portfolio=(SRC/'portfolio.py').read_text(encoding='utf-8')
    portfolio=portfolio.replace('from execution import buy_order,sell_order,entitlement','from execution import plan_buy,fill_buy,sell_order,entitlement,price_band,band_contradiction')
    portfolio=portfolio.replace('def simulate(method,scores,quotes,events):','def simulate(method,scores,quotes,events,plan=None,start=None,end=None):')
    portfolio=portfolio.replace("    plan=pd.read_parquet(AUDIT/'weekly_schedule.parquet')", "    if plan is None:\n        plan=pd.read_parquet(AUDIT/'weekly_schedule.parquet')\n    start=pd.Timestamp(start or SPEC['execution_start'])\n    end=pd.Timestamp(end or SPEC['execution_end'])")
    portfolio=portfolio.replace("plan.loc[plan.year.isin([2021,2022,2023])].itertuples()","plan.loc[pd.to_datetime(plan.monday).between(start,end)].itertuples()")
    portfolio=portfolio.replace("    transactions=[]", "    transactions=[]\n    planned_orders=[]")
    portfolio=portfolio.replace("        if date.year<2021:","        if date<start or date>end:")
    old="""            target=allocations.get(date,cash/10)
            for s in orders:
                bar=quotes.bar(s,i)
                previous=quotes.bar(s,i-1)
                fill,reason=buy_order(bar,target,cash,previous['volume'] if previous['active'] else 0,date)
                if fill is None:
                    log(date,'buy_cancelled',symbol=s,reason=reason)
                    continue
                cash-=fill['notional']+fill['fee']"""
    new="""            target=allocations.get(date,cash/10)
            available=cash
            plans=[]
            # Budget buckets are reserved before final auction price/fill is read.
            for s in orders:
                budget=min(target,available)
                available-=budget
                bar=quotes.bar(s,i)
                previous=quotes.bar(s,i-1)
                order,reason=plan_buy(bar,budget,previous['volume'] if previous['active'] else 0,date)
                planned_orders.append(dict(method=method,date=key,symbol=s,budget=budget,
                    qty=order['qty'] if order else 0,limit_price=order['limit_price'] if order else None,
                    preclose=bar.get('preclose'),prior_volume=previous.get('volume'),status='planned' if order else 'cancelled_preopen',reason=reason))
                if order is None:
                    log(date,'buy_cancelled',symbol=s,reason=reason)
                else:
                    plans.append((s,order))
            for s,order in plans:
                bar=quotes.bar(s,i)
                fill,reason=fill_buy(order,bar,date)
                if fill is None:
                    log(date,'buy_cancelled',symbol=s,reason=reason)
                    continue
                cash-=fill['notional']+fill['fee']"""
    assert old in portfolio
    portfolio=portfolio.replace(old,new)
    portfolio=portfolio.replace("            bar=quotes.bar(s,i)\n            if bar['active']:","            bar=quotes.bar(s,i)\n            band_bad=band_contradiction(bar,date)\n            if band_bad:\n                unknown=True\n                bad.append(dict(symbol=s,date=key,reason=band_bad))\n            if bar['active']:")
    portfolio=portfolio.replace("                positions[s]=dict(qty=fill['qty']", "                band_bad=band_contradiction(bar,date)\n                if band_bad:\n                    unknown=True\n                    bad.append(dict(symbol=s,date=key,reason=band_bad))\n                positions[s]=dict(qty=fill['qty']")
    portfolio=portfolio.replace("requested=sorted(requested),bad=bad,complete=not unknown)","requested=sorted(requested),bad=bad,complete=not unknown,plans=pd.DataFrame(planned_orders))")
    (DEST/'portfolio.py').write_text(portfolio,encoding='utf-8')
    registration=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_account_performance=True,
        spec_sha256=sha(OUT/'spec.json'),rules_sha256=sha(RULES/'RULES.json'),
        files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(DEST.glob('*.py'))])
    (OUT/'registration.json').write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Account replay registered; original files unchanged, two fixed signal variants.',flush=True)


if __name__=='__main__':
    main()
