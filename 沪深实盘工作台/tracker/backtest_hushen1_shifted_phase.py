"""Shift only the 20-session phase for a standalone, non-production replay."""
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import market
from hushen1 import Desk,ROOT,read,save


def main():
    desk=Desk();h=market.health(desk.folder);end=h['market_date'];anchor='2026-10-29'
    calendar=[d for d in h['sessions'] if d>='2018-01-01']
    anchor_index=calendar.index(anchor);start=calendar[anchor_index-20];signal_date=calendar[anchor_index-21]
    assert end=='2026-10-28','Replay snapshot ends on 2026-10-28; no current-day fills may be invented'
    offset=(anchor_index-1)%20
    out=desk.folder/'shifted_phase_20260923_to_20261029';out.mkdir(exist_ok=True)
    home=ROOT/'沪深1研究'
    work=home/'results/holdout_restricted/range_20200101_to_20261028_unified_cash_cost/runtime_inputs'
    before=market.input_inventory();ledger_before=digest(desk.path)
    sys.path.insert(0,str(home/'backtest'));import engine as e
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=end)
    code=(home/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(home/'backtest/engine.py'),'exec'),e.__dict__)
    print('LOAD_HASHED_INPUTS',start,end,'anchor',anchor,'offset',offset,flush=True)
    m=e.Market();ranks=read(work/'rankings_original.json')
    m.actions.own=out/'additional_actions.json';m.actions.extra=read(m.actions.own) if m.actions.own.exists() else {}
    m.actions.cache.update(m.actions.extra)
    a=e.Account(pd.Timestamp(start),m,'unified_cash_cost',10000);a.settle_sale_next_session=False
    rebalances=[]
    try:
        for day in m.dates[(m.dates>=start)&(m.dates<=end)]:
            i=m.dates.get_loc(day)
            assert str(m.dates[i].date())==calendar[i]
            due=a.m.g.alpha_first or (i-offset-1)%20==0
            for s in list(a.holdings):
                action=m.actions.ensure(s,day)
                if action:a.actions[s,day]=action
            a.step(day,i-offset,m.dates[i-1],ranks)
            a.curve[-1]['holdings']=len(a.holdings)
            if due:rebalances.append(dict(day=str(day.date()),signal_day=str(m.dates[i-1].date()),targets=dict(a.m.g.alpha_targets)))
    finally:m.actions.close()
    result=e.metrics(a,start)
    assert len(rebalances)==1 and rebalances[0]['day']==start,rebalances
    sig=desk.signal();assert sig['asof']==end and sig['valid_for']==anchor
    simulated=dict(cash=a.cash,positions=[dict(symbol=s,quantity=p['qty'],cost=0,
        lots=[dict(q=l['q'],date=str(l['buy'].date()),available_on=str(l['release'].date())) for l in p['lots']]) for s,p in a.holdings.items()])
    with patch.object(desk,'events',return_value=[]):indicative=desk.plan(simulated,sig)
    # This projection is due to the shifted phase, not a second first-entry.
    indicative.update(first=False,due=True,meaning='2026-10-28 close-based projection for shifted 2026-10-29 rebalance; actual opening prices and fills unavailable')
    names=pd.read_csv(market.DATA/'metadata/historical_mainboard_universe.csv').set_index('symbol').code_name.to_dict()
    holdings=[dict(symbol=s,name=names.get(s,s),quantity=p['qty'],close=p['last'],market_value=p['qty']*p['last']) for s,p in a.holdings.items()]
    assert before==market.input_inventory() and not market._updater_running()
    assert digest(desk.path)==ledger_before,'Manual ledger changed concurrently; do not overwrite'
    audit=dict(anchor_rebalance=anchor,previous_entry=start,initial_signal_day=signal_date,initial_cash=10000,
        completed_market_end=end,phase_offset_sessions=offset,rebalances=rebalances,summary=result,holdings=holdings,
        next_rebalance_close_projection=indicative,actual_current_day_fill_simulated=False,
        unresolved_actions=a.issues,reference_differences=a.reference_diffs,
        scenario='same-day sale cash;0.2% one-side slippage;commission0.03% min5;sellstamp0.1%;no separate transfer;original stock selection and caps',
        source_sha256=digest(home/'supermind_hushen_1.py'),rank_sha256=digest(work/'rankings_original.json'),manual_ledger_unchanged=True)
    save(out/'AUDIT.json',audit)
    pd.DataFrame(a.curve).to_csv(out/'daily_nav.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(a.trades).to_csv(out/'trades.csv',index=False,encoding='utf-8-sig')
    print('RESULT',audit,flush=True)
    print('COMPLETE',out,flush=True)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
if __name__=='__main__':main()
