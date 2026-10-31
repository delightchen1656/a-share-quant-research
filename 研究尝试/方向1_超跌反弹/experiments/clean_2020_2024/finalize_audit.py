"""Audit only already-authorized experiment outputs. Does not select or retune."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
P=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
selection=read(P/'SELECTION_FROZEN.json');stability=read(P/'STABILITY.json')
assert sha(P/'SELECTION_FROZEN.json')==stability['selection_sha256']
audits=[]
for stage in ['selection_runs','stability_runs']:
    for folder in sorted((P/stage).iterdir()):
        result=read(folder/'RESULT.json');output=next(folder.glob('*/daily_nav.parquet')).parent
        nav=pd.read_parquet(output/'daily_nav.parquet');trades=pd.read_parquet(output/'trades.parquet');ledger=pd.read_parquet(output/'ledger.parquet')
        daily_identity=float((nav.equity-nav.cash-nav.stock_value-nav.receivable).abs().max())
        last=nav.iloc[-1];unrealized=0
        for h in result['open_positions']:
            qty=h['available']+sum(v['qty'] for v in h['locked'])
            unrealized+=h['sale_net']+h['div_net']+qty*h['last_price']-h['cost']
        terminal_identity=float(last.equity-100000-trades.pnl.sum()-unrealized)
        t1_violations=int((trades.sell_date<=trades.buy_date).sum())
        minimum_cash=float(min(nav.cash.min(),ledger.cash.min()))
        timing_errors=[];cash_errors=[];cash=100000.
        for day,rows in ledger.groupby('date',sort=False):
            seen_buy=False
            for row in rows.itertuples():
                if row.kind=='buy':seen_buy=True;cash-=row.gross+row.fee
                elif row.kind=='sell':
                    if seen_buy and row.reason in ['take_profit_open','stop_loss_open','forced_delayed_open']:timing_errors.append(day)
                    cash+=row.gross-row.fee
                elif row.kind=='dividend_payment':cash+=row.net
                if abs(cash-row.cash)>.01:cash_errors.append(day)
            if abs(float(nav.loc[nav.date==day,'cash'].iloc[0])-cash)>.01:cash_errors.append(day)
        # No corporate event may bypass cash reconciliation: inspect outputs as evidence.
        if result['summary']['corporate_events']:raise ValueError('Extend ledger reconstruction for direct ex-day cash events')
        assert daily_identity<1e-7 and abs(terminal_identity)<.01 and minimum_cash>=-1e-6
        assert not t1_violations and not timing_errors and not cash_errors
        audits.append(dict(stage=stage,candidate=folder.name,daily_nav_identity_max_abs=daily_identity,terminal_pnl_identity_residual=terminal_identity,minimum_cash=minimum_cash,t1_violations=t1_violations,opening_cash_timing_errors=len(timing_errors),ledger_cash_errors=len(cash_errors),closed_trade_pnl=float(trades.pnl.sum()),open_marked_pnl=float(unrealized),terminal_cash=float(last.cash),terminal_stock_value=float(last.stock_value),terminal_receivable=float(last.receivable),terminal_equity=float(last.equity),open_positions=len(result['open_positions']),corporate_events=result['summary']['corporate_events']))
save(P/'ACCOUNT_AUDIT.json',dict(passed=True,checks=audits,selection_hash_verified=stability['selection_sha256']))
protocol=read(P/'PROTOCOL.json');winner=selection['winner']
config={**protocol['baseline'],**next(c for c in protocol['candidates'] if c['id']==winner)}
save(P/'CANDIDATE_FROZEN.json',dict(research_only=True,selected_before_2024_account_runs=True,configuration=config,capital=100000,signal_rule='Rescanned current structure and RULE, see PROTOCOL.json',protocol_sha256=sha(P/'PROTOCOL.json'),selection_sha256=sha(P/'SELECTION_FROZEN.json'),account_sha256=sha(P/'account.py'),runner_sha256=sha(P/'run_research.py'),input_manifest='inputs_pre2025/RESEARCH_2020_2024_MANIFEST.json',input_manifest_sha256='986c45c71eb28bc42410316201ea5e370bc090ebb261e37439fb25f967e3c51f',production_registration_changed=False))
rows=[]
for cid,result in stability['results'].items():
    rows.extend(dict(candidate=cid,**r) for r in result['yearly'])
pd.DataFrame(rows).to_csv(P/'stability_annual_comparison.csv',index=False,encoding='utf-8-sig')
inputs=read(P/'INPUT_AUDIT.json');issues=[r for r in inputs['actions'] if r['unresolved_fields']]
save(P/'DATA_LIMITATIONS.json',dict(universe=947,retrospective_universe=True,signal_count=inputs['signals'],supplier_response_pairs=inputs['supplier_response_pairs'],action_records_audited=len(inputs['actions']),unresolved_action_reference_records=len(issues),unresolved_actions=issues,held_unresolved_actions=0,entry_availability=read(P/'ENTRY_AVAILABILITY.json'),future_tail_label_required=False,cutoff_marking='Open stock at last raw close, no invented exit; contingent exit costs not deducted until execution',review_2024_is_new_blind_test=False))
print(json.dumps(dict(account_runs_audited=len(audits),passed=True,winner=winner,unresolved_reference_records=len(issues)),ensure_ascii=False))
