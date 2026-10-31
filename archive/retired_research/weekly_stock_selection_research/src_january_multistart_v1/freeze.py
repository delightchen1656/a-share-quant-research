from pathlib import Path
import json
import shutil
import datetime
from common import BASE,AUDIT,sha,dump

def main():
    for name in ['minimum_checks.json','training_and_100k_validation.json']:
        assert json.loads((AUDIT/name).read_text(encoding='utf-8'))['passed']
    dest=AUDIT/'frozen_engine_v1';assert not dest.exists();dest.mkdir()
    names=['common.py','execution.py','portfolio.py','daily_exit.py','account_validation.py','company_data.py',
           'annual_training.py','panel_builder.py','multistart.py','runtime.py','factor_functions.py']
    for name in names:
        source=Path(__file__).with_name(name).read_text(encoding='utf-8')
        if name=='common.py':
            source=source.replace('BASE=Path(__file__).resolve().parent.parent',f'BASE=Path({str(BASE)!r})')
            source=source.replace("SPEC=json.loads((AUDIT/'spec.json').read_text(encoding='utf-8'))","SPEC=json.loads((Path(__file__).parent/'spec.json').read_text(encoding='utf-8'))")
        (dest/name).write_text(source,encoding='utf-8')
    shutil.copy2(AUDIT/'spec.json',dest/'spec.json')
    shutil.copy2(BASE/'audits/holdout_restricted/monday_trading_rules_daily_v3/RULES.json',dest/'RULES.json')
    dump(dest/'AUDIT_PROTOCOL.json',dict(
        authorization='Existing independent auditor reused for user-requested2019+annual January starts. Parent computes2019-2023; auditor2024-2026. No new factor search.',
        role='One-way execution/annual-refit auditor, not isolated development. Inspect auto-context boundary; do not claim clean blind development.',
        years=[2024,2025,2026],start_policy='ALL actual open January Mondays, separate100000CNY each, end same year. Some years only3starts; never choose beststart.',
        fees='commission BOTH SIDES0.0003 minimum5CNY per filled stock order plus unchanged historical transfer/stamp, zero slippage, personal dividend withholding beforetax.',
        model='Only combine__long_momentum candidate.2019-2023unchanged saved annual forward scores.2024EXACT original end2023candidate.joblib.2025/2026use annual_training.fit_year on all strictly prior matured labels, fixed12features and SPECfixed_HGB. Annualpack fixed within year, store hashes/audits before account evaluation.',
        original_candidate='audits/holdout_restricted/monday_factor_v5/frozen_exploratory_requested_v1/candidate.joblib',
        candidate_sha256='a70bcbd76b761afcab0f5dacb29d9fd99ca65a9a2271546185f2aa10ab022b56',
        parameter_freeze='Only annual deterministic fitting is authorized; no change to factors, hyperparameters, label mask, model choice, count, lot, budget, fees, dates or exit proxy after outcomes.',
        label='Original ordinary gross quote excess, not net account PnL. Frozen panel_builder uses prior-close features and training reference mismatch exclusion. No naive post-bonus per-share economic label.',
        source='Read only committed source from unified tools/daily_market_update.py metadata/audit. Check updater processes/locks first. Reuse20261026 committed market if still latest; do NOT start an updater or extend to partial mixed snapshot. User authorizes latest available complete cutoff for this audit; previous audits stay intact.',
        raw='New audit-only snapshots in own output. Immutable2018-2023local input whitelist plus2024-cutoff committed raw (SH/SZ board subdirectories); no current active/delist/industry filter. Keep raw/calendar/index source hashes. No write in inputs_pre2025 for postperiod.',
        features='Frozen panel_builder.symbol_panel and make_schedule reproduce earlier3symbol features/labels; annual2019fit reproduces existing top10/scores. Use complete eligible signal-date pool for cross-sectional ranks BEFORE traininglabel filtering. Monday/Tue actual trading calendar, previous actual close signal. Fit medians/scaler and date weights ONLY on training mask.',
        terminal='CalendarTuesday may lie beyond quote cutoff: include eligible lastMonday entry and mark still-open shares to last valid cutoff quote. Year-end accounts stop without synthetic liquidation. List listed/unlisted/receivable balances. Current year isYTD.',
        engine='Use frozen portfolio.simulate(initial_cash=100000,start=JanuaryMonday,end=min(yearend,cutoff)), independent_account and multistart.validate_account/evaluate. Pass own Quotes, events, plan. Do not run parent development mains or guard installer.',
        exit='Unchanged dailyV3: Tuesdaytouch + same-dayhigh>floor => full listed share floor-price fill even if event order unknown; one-price lock persists and retries EVERY actualday. Reopening later at currentdayfloor even below daylow is intentionally conservative proxy, count outsideOHLC fills. No sell volume cap; buy rules unchanged.',
        corporate='Before valid account results, audit ALL held stockyears, ordinary shareholder economic distributions separately from virtual reference coefficients, actual record/ex/pay/listing. Use existing primary-evidence overrides when independently applicable; preserve evidence hashes. Provider returns blacklist10001011 in parent, no fabricated empty events; existing project auditcache can be reused only with correct year/evidence and hashes. Obtain missing primary evidence or clearly block. Actual calendar/reference contradictions stay exceptions.',
        validation='Independent full cash/listed/unlisted/receivable replay for every start; preauction budgets/qty/rank/slots independent, no same-Monday exit-funded entry;100k/minfee checks. If generic engineering repair needed preserve original and log, no outcome-guided tuning.',
        output='New restricted_audit_2024_2026_january_v1 under current directory. All rows:year,start,end,return,closeMDD,endNAV,fees,firstentry,trade counts,terminalrights,ambiguity/outsideOHLC counts. Full tables/TXT and PNG readable by user. Include year2026YTD labels; per-year min/median/max purely descriptive, no selected start.',
        firewall='Return parent ONLY status plus paths. NEVER performance,ranking,factor advice,problem securities/dates/economic ratios. Parent will embed PNG without viewing it. Engineering blocker abstract status allowed. Do not send new messages to other threads.',
        freeze_before_postperiod=True,no_deployment=True))
    dump(dest/'FREEZE_MANIFEST.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_any_new_account_results=True,files=[dict(path=p.name,sha256=sha(p)) for p in sorted(dest.iterdir()) if p.is_file()]))
    print('FROZEN_ENGINE',dest,flush=True)
    print('MANIFEST_SHA256',sha(dest/'FREEZE_MANIFEST.json'),flush=True)

if __name__=='__main__':main()
