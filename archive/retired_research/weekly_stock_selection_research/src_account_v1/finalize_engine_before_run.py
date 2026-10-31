"""Engineering amendments before any account performance is compared."""
from pathlib import Path
import datetime
from common import BASE,AUDIT,sha,dump


def main():
    portfolio=Path(__file__).with_name('portfolio.py')
    source=portfolio.read_text(encoding='utf-8')
    source=source.replace("        previous_marks={s:p['mark'] for s,p in positions.items()}","        cash_due_today=0.\n        previous_marks={s:p['mark'] for s,p in positions.items()}")
    source=source.replace("                cash+=claim['gross_cash']","                cash_due_today+=claim['gross_cash']")
    source=source.replace("        inventory=sum((p['qty']", "        cash+=cash_due_today\n        inventory=sum((p['qty']")
    portfolio.write_text(source,encoding='utf-8')
    independent=Path(__file__).with_name('account_validation.py')
    source=independent.read_text(encoding='utf-8')
    source=source.replace("        day=row.date", "        cash_due_today=0.\n        day=row.date")
    source=source.replace("                cash+=c['cash']", "                cash_due_today+=c['cash']")
    source=source.replace("        symbols={k[0]", "        cash+=cash_due_today\n        symbols={k[0]")
    independent.write_text(source,encoding='utf-8')
    company=Path(__file__).with_name('company_data.py')
    source=company.read_text(encoding='utf-8')
    source=source.replace('def initialize():\n    global UPDATER','def initialize(store_path=None):\n    global UPDATER,STORE\n    if store_path is not None:\n        STORE=Path(store_path)')
    source=source.replace('def normalize(records):\n    quotes=Quotes()', 'def normalize(records,quotes=None,store=None):\n    quotes=quotes or Quotes()\n    source_store=Path(store) if store is not None else STORE')
    source=source.replace('pd.read_parquet(STORE/f"{record[', 'pd.read_parquet(source_store/f"{record[')
    company.write_text(source,encoding='utf-8')
    dump(AUDIT/'pre_run_engine_clarifications.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_account_performance=True,
        dividend_cash_timing='Only payment date known, no intraday credit timestamp. Conservatively make payment cash spendable at payment-day close, not that Monday opening.',
        prior_company_cache_reuse='Read same-project raw provider records by verified hashes; collect missing held stockyears only, separate company proof from strategy signals.',
        auditor_IO='Provider cache directory and quote object may be passed by audit role; does not change economic rules or model.',
        code=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(Path(__file__).parent.glob('*.py'))]))
    print('Conservative payment-time and reusable evidence IO clarified before NAV outcomes.',flush=True)


if __name__=='__main__':
    main()
