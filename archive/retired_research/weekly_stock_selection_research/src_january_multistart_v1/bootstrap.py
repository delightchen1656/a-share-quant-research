"""Freeze annual past-only fitting and separate 100k January-start accounts."""
from pathlib import Path
import datetime
import json
import hashlib
import shutil

BASE=Path(__file__).resolve().parent.parent
SRC=Path(__file__).resolve().parent
OUT=BASE/'audits/holdout_restricted/january_multistart_100k_v1'
OLD=BASE/'src_account_daily_v3'
MODEL=BASE/'audits/holdout_restricted/monday_factor_v5/frozen_exploratory_requested_v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    assert not (OUT/'spec.json').exists()
    request=json.loads((OUT/'REQUEST.json').read_text(encoding='utf-8'))
    old=json.loads((BASE/'audits/holdout_restricted/monday_account_daily_v3/spec.json').read_text(encoding='utf-8'))
    hyper=json.loads((BASE/'audits/holdout_restricted/monday_factor_v5/spec.json').read_text(encoding='utf-8'))['fixed_HGB']
    spec=dict(**old)
    spec.update(id='january_multistart_100k_v1',execution_start='2019-01-01',execution_end='2023-12-31',
        year_range=[2019,2026],initial_cash=100000,fixed_HGB=hyper,
        training='User: 那就2019开始, accepting annual past-only refits with frozen factors and hyperparameters. Train once at each year boundary on strictly previously matured labels; fixed within year. No outcome-based selection.',
        training_label='Keep original ordinary quote excess target and validity mask; not account net PnL. Cross-share-distribution reference-mismatch labels remain unknown, not naive post-split per-share returns.',
        historical_scores='2019-2023 reuse exact frozen-method combine__long_momentum annual forward scores; existing training audit verifies maturity before January1. No final2023model applied backwards.',
        later_scores='2024 model is exact end2023frozen candidate; 2025 and2026 annual training repeats same procedure on past matured labels only. Auditor computes later period after procedure freeze, no performance feedback.',
        endpoints='Each actual January Monday is an independent100k start; year-end boundary, latest committed cutoff in current year; no carry across accounts/years, no artificial year-end liquidation.',
        schedule='Buy only when calendar has actualMonday and actualTuesday (Tuesday may lie beyond reporting cutoff). January start account remains cash if first week is ineligible. Include last open position marked to cutoff; do not require exit prices to exist before entry.',
        commission='Both sides0.0003,minimum5CNY for EACH filled stock order. Date-specific transfer/stamp retained. No slippage, no interest, personal dividend tax beforetax.',
        report='Every candidate start with account return,closeMDD,endNAV,fees,trades,firstactualentry,terminal shares/receivables and exceptions; aggregate range/median is descriptive, never choose beststart.',
        no_posterior_reads=True,authorization='User requests annual January multistart backtests, initially2018 then revises start to2019; each start ends same year.')
    (OUT/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ['common.py','execution.py','portfolio.py','daily_exit.py','account_validation.py','company_data.py']:
        text=(OLD/name).read_text(encoding='utf-8')
        if name=='common.py':text=text.replace('monday_account_daily_v3','january_multistart_100k_v1')
        if name=='portfolio.py':
            text=text.replace('plan=None,start=None,end=None):','plan=None,start=None,end=None,initial_cash=100000.):')
            text=text.replace('    cash=1e6','    cash=float(initial_cash)')
            text=text.replace("daily[-1]['equity']-1e6","daily[-1]['equity']-initial_cash")
            text=text.replace('return dict(daily=pd.DataFrame(daily)',"return dict(initial_cash=float(initial_cash),terminal_positions=positions,claims=claims,daily=pd.DataFrame(daily)")
        if name=='account_validation.py':
            text=text.replace('    cash=1e6',"    initial_cash=float(result.get('initial_cash',100000.))\n    cash=initial_cash")
            text=text.replace("daily.equity.iloc[-1]-1e6","daily.equity.iloc[-1]-initial_cash")
        (SRC/name).write_text(text,encoding='utf-8')
    tests=(OLD/'checks.py').read_text(encoding='utf-8')
    tests=tests.replace('plan=plan)','plan=plan,initial_cash=1e6)')
    (SRC/'checks.py').write_text(tests,encoding='utf-8')
    for name in ['runtime.py','factor_functions.py']:
        shutil.copy2(MODEL/name,SRC/name)
    (OUT/'SCOPE_CONFIRMATION.json').write_text(json.dumps(dict(
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),original_request_sha256=sha(OUT/'REQUEST.json'),
        user_confirmation='2019开始；每个起点只到当年年底；每年过去数据重训，其余参数冻结',
        raw_market_data_readonly=True,no_new_performance_computed=True),ensure_ascii=False,indent=2),encoding='utf-8')
    print('2019+ annual fitting/100k within-year account scope registered.')

if __name__=='__main__':main()
