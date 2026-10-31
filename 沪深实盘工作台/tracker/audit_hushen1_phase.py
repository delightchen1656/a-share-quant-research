"""Read-only account phase comparison using the registered local daily engine."""
import hashlib
import json
import sys
from pathlib import Path
import pandas as pd
import market
from hushen1 import Desk,ROOT,read,save


def main():
    desk=Desk();health=market.health(desk.folder);end=health['market_date']
    sessions=market.calendar_extended(desk.folder)
    calendar=[d for d in sessions if d>='2018-01-01']
    today='2026-10-29'
    scheduled=[d for i,d in enumerate(calendar) if (i-1)%20==0]
    previous=max(d for d in scheduled if d<=today);following=min(d for d in scheduled if d>today)
    out=desk.folder/'phase_audit_20261029';out.mkdir(exist_ok=True)
    home=ROOT/'沪深1研究'
    work=home/'results/holdout_restricted/range_20200101_to_20261028_unified_cash_cost/runtime_inputs'
    assert end=='2026-10-28', 'Expected audited snapshot end; do not silently change comparison'
    before=market.input_inventory()
    sys.path.insert(0,str(home/'backtest'))
    import engine as e
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=end)
    code=(home/'backtest/engine.py').read_text(encoding='utf-8').replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(code,str(home/'backtest/engine.py'),'exec'),e.__dict__)
    print('VERIFY_AND_LOAD_HASHED_SNAPSHOT',flush=True)
    m=e.Market()
    m.actions.own=out/'additional_actions.json'
    m.actions.extra={};ranks=read(work/'rankings_original.json')
    results=[]
    try:
        for start in ['2026-01-02',previous]:
            dates=m.dates[(m.dates>=start)&(m.dates<=end)]
            a=e.Account(dates[0],m,'unified_cash_cost',10000)
            # Current manual desk cash/cost convention: same-day sale cash,
            # 0.2% reference slippage, 0.03% min5, sell0.1%, no transfer.
            a.settle_sale_next_session=False
            rebalances=[]
            for day in dates:
                i=m.dates.get_loc(day);due=a.m.g.alpha_first or (i-1)%20==0
                for s in list(a.holdings):
                    action=m.actions.ensure(s,day)
                    if action:a.actions[s,day]=action
                a.step(day,i,m.dates[i-1],ranks)
                a.curve[-1]['holdings']=len(a.holdings)
                if due:rebalances.append(dict(day=str(day.date()),signal_day=str(m.dates[i-1].date()),targets=dict(a.m.g.alpha_targets)))
            result=e.metrics(a,start)
            assert not a.issues and not a.reference_diffs,(a.issues,a.reference_diffs)
            result.update(rebalances=rebalances,holdings=[dict(symbol=s,quantity=p['qty'],close=p['last'],market_value=p['qty']*p['last']) for s,p in a.holdings.items()],targets=dict(a.m.g.alpha_targets))
            results.append(result)
            prefix=start.replace('-','')
            pd.DataFrame(a.curve).to_csv(out/(prefix+'_daily_nav.csv'),index=False,encoding='utf-8-sig')
            pd.DataFrame(a.trades).to_csv(out/(prefix+'_trades.csv'),index=False,encoding='utf-8-sig')
            print('REPLAY',start,'last_rebalance',rebalances[-1],'holdings',result['holdings'],flush=True)
    finally:m.actions.close()
    assert before==market.input_inventory() and not market._updater_running()
    snapshot=desk.snapshot()
    audit=dict(today=today,market_asof=end,last_regular_rebalance=previous,next_regular_rebalance=following,
        prior_sessions_since_2018=calendar.index(today),phase_remainder=(calendar.index(today)-1)%20,
        desk_first_entry=snapshot['plan']['first'],desk_plan=snapshot['plan'],replays=results,
        entry_sha256=hashlib.sha256((home/'supermind_hushen_1.py').read_bytes()).hexdigest(),
        snapshot_rank_sha256=hashlib.sha256((work/'rankings_original.json').read_bytes()).hexdigest(),
        actual_ledger_modified=False,limits='Daily fill approximation; no current-day opening market data. First-entry exception is distinct from regular rebalance.')
    save(out/'AUDIT.json',audit)
    print('COMPLETE',out,flush=True)


if __name__=='__main__':main()
