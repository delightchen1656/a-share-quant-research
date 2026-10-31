"""Register confirmed account scope, without choosing or evaluating a model mode."""
from pathlib import Path
import datetime
import json
import hashlib
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent
OUT=BASE/'audits/holdout_restricted/january_multistart_100k_v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'REQUEST.json').exists(),'Preserve registered requests'
    calendar_path=ROOT/'sh_sz_market_research/data_pipeline/data/metadata/trade_calendar_20261026.csv'
    calendar=pd.read_csv(calendar_path)
    days=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date']))
    # Calendar only: no new price, label, account result or current-stock status read.
    candidates=[]
    for year in range(2018,2027):
        starts=days[(days.year==year)&(days.month==1)&(days.weekday==0)]
        for n,day in enumerate(starts,1):
            candidates.append(dict(year=year,start_number=n,start_date=str(day.date()),
                requested_end_date=f'{year}-12-31',initial_cash=100000,
                calendar_candidate=True,requires_mature_signal_before_Monday=True,
                requires_valid_Tuesday_before_entry=True))
    pd.DataFrame(candidates).to_parquet(OUT/'january_monday_candidates.parquet',index=False)
    pd.DataFrame(candidates).to_csv(OUT/'january_monday_candidates.csv',index=False,encoding='utf-8-sig')
    spec=dict(id='january_multistart_100k_v1',registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        user_confirmed_end_policy='Each January Monday starts a separate account; ends that same calendar year. No cross-year compounding.',
        start_policy='ALL actual open Mondays in January. Holidays are skipped, not replaced with Tuesday or selected using returns. Hence some years have fewer than4starts.',
        year_range=[2018,2026],current_year='YTD to latest fully committed and validated usable market cutoff; not full-year performance.',
        initial_cash=100000,commission_rate_each_side=.0003,minimum_commission_CNY_per_filled_stock_order_each_side=5,
        tax_policy='Retain existing date-specific stamp and transfer fees, personal dividend withholding beforetax, zero slippage. No commission-only switch inferred.',
        selection='Only existing 11factor_plus_momentum120 candidate, ordered12features, top10; no variant search, start-date selection or optimization.',
        normal_entry='Monday opening; signal from previous actual close; preauction quantity, fixed budget buckets and failures leave cash.',
        normal_exit='Tuesdayclose; inherit user-confirmed daily_touch_reopen_floor_v3 exception.',
        daily_exit_rules_path='audits/holdout_restricted/monday_trading_rules_daily_v3/RULES.json',
        daily_exit_rules_sha256=sha(BASE/'audits/holdout_restricted/monday_trading_rules_daily_v3/RULES.json'),
        model_training_mode='PENDING user clarification: annual past-only refit with frozen factors/hyperparameters versus fixed end2023weights for retrospective replay.',
        pending_choices_not_silently_frozen=True,
        known_history='Current local approved price snapshot begins2018. Earliest saved annual forward scores2019. No valid2018out-of-sample result can be asserted without earlier training/warmup data.',
        calendar_sha256=sha(calendar_path),calendar_is_not_price_or_performance_data=True,
        data_firewall='Optimizer reads approved pre2025white-list inputs only. Later prices/results remain in existing one-way auditor role after package freeze. No posterior feedback.',
        metrics='For EVERY year/start: actual start/end, account return,endNAV,closeMDD,fees,trade/failure count,terminallisted/unlisted/receivable inventory,ambiguity/outsideOHLC counts and evidence exceptions. No forcedDec31sale at unavailable prices.',
        completed_backtest=False,no_new_model_fits=True,no_new_prices_or_posterior_results_read=True)
    (OUT/'REQUEST.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Confirmed account scope registered; model training mode pending.')
    print(pd.DataFrame(candidates).groupby('year').size().to_string())

if __name__=='__main__':main()
