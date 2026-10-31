"""One frozen 2024 audit. Refuses rerun; all outcomes stay holdout_restricted."""
from pathlib import Path
import json
import hashlib
import datetime
import platform
import sys
import numpy as np
import pandas as pd
from engine import simulate

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
OUT=HERE/'audits/holdout_restricted/validation_2024_v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,value):
    # Pandas conversion also normalizes NumPy scalars, timestamps and NaN.
    normalized=json.loads(pd.Series([value]).to_json(orient='values',force_ascii=False,date_format='iso'))[0]
    Path(path).write_text(json.dumps(normalized,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def prepare():
    reg=json.loads((HERE/'rule_registration.json').read_text(encoding='utf-8'))
    for item in reg['files']:
        assert sha(item['path'])==item['sha256'],item['path']
    tests=json.loads((HERE/'execution_tests.json').read_text(encoding='utf-8'))
    assert tests['passed'] and tests['engine_sha256']==sha(HERE/'engine.py')
    candidates=pd.read_parquet(HERE.parent/'results/primary_candidates.parquet')
    candidates=candidates.loc[candidates.year.eq(2023)].copy().sort_values('symbol')
    assert len(candidates)==20 and not candidates.symbol.duplicated().any()
    candidates['contracted_lower']=candidates.lower+.05*(candidates.upper-candidates.lower)
    candidates['contracted_upper']=candidates.upper-.05*(candidates.upper-candidates.lower)
    candidates[['symbol','historical_name','lower','upper','contracted_lower','contracted_upper']].to_parquet(HERE/'frozen_levels.parquet',index=False)
    calendar_path=ROOT/'inputs_pre2025/trading_calendar_v1/calendar.parquet'
    calendar=pd.read_parquet(calendar_path)
    provider=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1)&calendar.calendar_date.between('2024-01-01','2024-12-31'),'calendar_date'])
    expected=pd.date_range('2024-01-01','2024-12-31',freq='B')
    holidays=[('2024-01-01','2024-01-01'),('2024-02-09','2024-02-17'),('2024-04-04','2024-04-06'),
              ('2024-05-01','2024-05-05'),('2024-06-10','2024-06-10'),('2024-09-15','2024-09-17'),('2024-10-01','2024-10-07')]
    for start,end in holidays:
        expected=expected[~expected.to_series(index=expected).between(start,end).to_numpy()]
    assert provider.equals(expected),'Provider2024calendar does not match exchange holiday calendar'
    dump(HERE/'calendar_verification.json',dict(matches_exchange_calendar=True,trading_sessions=len(provider),
         provider_sha256=sha(calendar_path),holiday_intervals=holidays,
         sources=['https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml',
                  'https://www.szse.cn/disclosure/notice/t20231226_605108.html']))
    return candidates,pd.DatetimeIndex([pd.Timestamp('2023-12-29')]).append(provider)


def event_admission(symbols,days):
    ledger_path=ROOT/'datasets/corporate_actions_reconciled_v3/dividend_event_ledger_provisional.parquet'
    ledger=pd.read_parquet(ledger_path,filters=[('ex_date','>=',pd.Timestamp('2024-01-01')),('ex_date','<=',pd.Timestamp('2024-12-31'))])
    ledger=ledger.loc[ledger.symbol.isin(symbols)].copy()
    events={s:[] for s in symbols}
    records=[]
    dayset=set(str(d.date()) for d in days)
    for row in ledger.itertuples():
        reasons=[]
        if row.bonus_per_share!=0 or row.transfer_per_share!=0:
            reasons.append('noncash_share_event_not_implemented')
        if not row.provider_amounts_agree:
            reasons.append('provider_amount_disagreement')
        if not row.event_fields_complete:
            reasons.append('incomplete_fields')
        if row.quote_reference_special:
            reasons.append('special_quote_reference')
        try:
            if json.loads(row.issues):
                reasons.append('ledger_issues')
        except (TypeError,ValueError):
            reasons.append('unparsed_issues')
        if not all(pd.notna(x) for x in [row.register_date,row.ex_date,row.cash_payment_date]):
            reasons.append('missing_record_ex_payment_date')
        elif not row.register_date<row.ex_date<=row.cash_payment_date:
            reasons.append('date_order_invalid')
        ex=str(pd.Timestamp(row.ex_date).date())
        if ex not in dayset:
            reasons.append('exdate_not_market_session')
        if not np.isfinite(row.cash_per_share) or row.cash_per_share<=0:
            reasons.append('nonpositive_cash')
        event=dict(symbol=row.symbol,ex_date=ex,
                   register_date=str(pd.Timestamp(row.register_date).date()) if pd.notna(row.register_date) else None,
                   cash_payment_date=str(pd.Timestamp(row.cash_payment_date).date()) if pd.notna(row.cash_payment_date) else None,
                   cash_per_share=float(row.cash_per_share),bonus_per_share=float(row.bonus_per_share),
                   transfer_per_share=float(row.transfer_per_share),supported=not reasons,reason=';'.join(reasons),
                   original_approved_for_economic_labels=bool(row.approved_for_economic_labels),
                   interpretation='conditional_local_cash_only_scenario_not_global_economic_approval')
        events[row.symbol].append(event)
        records.append(event)
    rights_path=ROOT/'datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet'
    rights=pd.read_parquet(rights_path)
    rights=rights.loc[rights.SECUCODE.isin(symbols)&pd.to_datetime(rights.ex_date).between('2024-01-01','2024-12-31')]
    for row in rights.itertuples():
        event=dict(symbol=row.SECUCODE,ex_date=str(pd.Timestamp(row.ex_date).date()),supported=False,reason='rights_subscription_not_implemented')
        events[row.SECUCODE].append(event)
        records.append(event)
    return events,records,[dict(path=str(ledger_path.relative_to(ROOT)),sha256=sha(ledger_path)),dict(path=str(rights_path.relative_to(ROOT)),sha256=sha(rights_path))]


def main():
    if (OUT/'holdout_opened.json').exists():
        raise RuntimeError('Holdout already opened; do not rerun/reoptimize. Inspect saved audit artifacts.')
    candidates,days=prepare()
    # Bind executable implementation after successful synthetic checks and before
    # any target2024price read. Rule hash and candidate list were registered earlier.
    source_files=['spec.json','rule_registration.json','engine.py','test_execution.py','execution_tests.json','run_once.py','report.py','calendar_verification.json','frozen_levels.parquet']
    code_reg=dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_2024_prices=True,
                  files=[dict(path=p,sha256=sha(HERE/p)) for p in source_files],
                  original_protocol_sha256=sha(ROOT/'research_protocol_v1.json'),original_gates_sha256=sha(ROOT/'research_stage_gates_v2.json'))
    dump(HERE/'execution_registration.json',code_reg)
    OUT.mkdir(parents=True,exist_ok=True)
    dump(OUT/'holdout_opened.json',dict(opened_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         execution_registration_sha256=sha(HERE/'execution_registration.json'),one_way_audit=True,
         explicit_user_authorized=True,development_results_must_not_be_updated=True))
    manifest_path=ROOT/'inputs_pre2025/kline_v1/manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    by_symbol={x['symbol']:x for x in manifest['files']}
    symbols=candidates.symbol.tolist()
    events,event_records,event_sources=event_admission(symbols,days)
    dump(OUT/'corporate_event_admission.json',event_records)
    (OUT/'inputs').mkdir(exist_ok=True)
    summaries=[]
    trades=[]
    daily=[]
    logs=[]
    source_audit=[]
    for row in candidates.itertuples():
        item=by_symbol[row.symbol]
        path=manifest_path.parent/item['snapshot_file']
        assert sha(path)==item['snapshot_sha256'],path
        df=pd.read_parquet(path,filters=[('date','>=',pd.Timestamp('2023-12-29')),('date','<=',pd.Timestamp('2024-12-31'))]).copy()
        df['date']=pd.to_datetime(df.date)
        assert not df.date.duplicated().any()
        assert df.date.isin(days).all()
        for column in ['open','high','low','close','preclose','volume','amount','pctChg']:
            df[column]=pd.to_numeric(df[column],errors='coerce')
        for column in ['tradestatus','isST']:
            df[column]=df[column].astype(str)
        assert df.date.ge('2023-12-29').all() and df.date.le('2024-12-31').all()
        df.to_parquet(OUT/'inputs'/f'{row.symbol}.parquet',index=False)
        aligned=df.set_index('date').reindex(days)
        summary,t,d,l=simulate(row.symbol,row.historical_name,row.lower,row.upper,aligned,events[row.symbol])
        for record in t:
            record['account_unknown_symbol']=summary['account_unknown']
        summaries.append(summary)
        trades.extend(t)
        daily.extend(d)
        logs.extend(l)
        source_audit.append(dict(symbol=row.symbol,source_snapshot_sha256=item['snapshot_sha256'],
                                 rows_read=len(df),missing_market_sessions=int(aligned.code.isna().sum()),
                                 suspended_rows=int(aligned.tradestatus.eq('0').sum()),saved_input_sha256=sha(OUT/'inputs'/f'{row.symbol}.parquet')))
    summary=pd.DataFrame(summaries)
    trade_frame=pd.DataFrame(trades)
    daily_frame=pd.DataFrame(daily)
    log_frame=pd.DataFrame(logs)
    assert len(summary)==20
    assert daily_frame.groupby('date').symbol.nunique().eq(20).all()
    summary.to_parquet(OUT/'per_stock_summary.parquet',index=False)
    trade_frame.to_parquet(OUT/'trades.parquet',index=False)
    daily_frame.to_parquet(OUT/'daily_sleeves.parquet',index=False)
    log_frame.to_parquet(OUT/'execution_log.parquet',index=False)
    nav=daily_frame.groupby('date').agg(equity=('equity','sum'),inventory=('inventory_value','sum'),cash=('cash','sum'),receivable=('net_receivable','sum'),unknown_sleeves=('account_unknown','sum'),stale_held_sleeves=('held_quote_stale','sum'))
    curve=np.r_[1e6,nav.equity.to_numpy()]
    nav['drawdown']=nav.equity.to_numpy()/np.maximum.accumulate(curve)[1:]-1
    nav['exposure']=nav.inventory/nav.equity
    nav.reset_index().to_parquet(OUT/'portfolio_nav.parquet',index=False)
    complete=not summary.account_unknown.any()
    closed=trade_frame.loc[trade_frame.status.eq('closed')]
    stopped=closed.loc[closed.exit_reason.str.contains('stop')]
    metrics=dict(stock_count=20,first_session=nav.index.min(),last_session=nav.index.max(),market_sessions=len(nav),
                 initial_capital=1e6,conditional_equity_end=float(nav.equity.iloc[-1]) if complete else None,
                 conditional_return=float(nav.equity.iloc[-1]/1e6-1) if complete else None,
                 conditional_max_drawdown=float(nav.drawdown.min()) if complete else None,
                 nominal_trace_equity_end=float(nav.equity.iloc[-1]),nominal_trace_return=float(nav.equity.iloc[-1]/1e6-1),
                 unknown_sleeves=int(summary.account_unknown.sum()),conditional_account_complete=complete,
                 signals=int(summary.signals.sum()),buys=int(summary.buy_fills.sum()),cancelled_buys=int(summary.cancelled_buys.sum()),
                 closed_trades=len(closed),open_trades=int(summary.open_trades.sum()),
                 closed_wins=int(closed.pnl_after_fees_and_dividend_reserve.gt(0).sum()),
                 closed_win_rate=float(closed.pnl_after_fees_and_dividend_reserve.gt(0).mean()) if len(closed) else None,
                 stop_exits=len(stopped),stop_price_loss_worse_than10pct=int(stopped.price_return.lt(-.1).sum()),
                 worst_closed_trade_price_return=float(closed.price_return.min()) if len(closed) else None,
                 buy_sell_fees=float(trade_frame.entry_fee.sum()+trade_frame.exit_fee.sum()),
                 gross_dividends_entitled=float(trade_frame.gross_dividend.sum()),dividend_tax_reserve=float(trade_frame.dividend_tax_reserve.sum()),
                 average_exposure=float(nav.exposure.mean()),dual_touch_stop_first=int(summary.dual_touch.sum()),
                 stop_delayed_days=int(summary.stop_blocked.sum()),entry_day_stop_latched=int(summary.tplus1_stop.sum()),
                 event_count=len(event_records),conditionally_supported_cash_events=sum(e.get('supported',False) for e in event_records),
                 unsupported_events=sum(not e.get('supported',False) for e in event_records),
                 interpretation='Daily-bar execution scenario conditional on provisional event ledger, costs and reserve. Not certified historical executable returns. Single frozen holdout, no retuning.')
    dump(OUT/'summary.json',metrics)
    dump(OUT/'input_audit.json',dict(files=source_audit,event_sources=event_sources,
         kline_manifest_sha256=sha(manifest_path),original_protocol_unchanged=sha(ROOT/'research_protocol_v1.json')==code_reg['original_protocol_sha256'],
         original_gates_unchanged=sha(ROOT/'research_stage_gates_v2.json')==code_reg['original_gates_sha256'],
         python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__))
    print(json.dumps(metrics,ensure_ascii=False,indent=2),flush=True)
    print(summary[['symbol','historical_name','buy_fills','closed_trades','open_trades','return_conditional','account_unknown']].to_string(index=False),flush=True)
    from report import create_report
    create_report()


if __name__=='__main__':
    main()
