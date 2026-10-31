"""Fixed Hushen2 June-2020 full-session start replay. No tuning or live account writes."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
import argparse
import gc
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
ARCHIVE=ROOT/'archive/hushen_2/pre_registration_research_20261020'
sys.path.insert(0,str(BASE/'tracker'))
import market

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj;spec.loader.exec_module(obj);return obj

def action_inputs(end,start='2020-06-01'):
    paths=[ROOT/'strategies/hushen/backtest/data/actions_merged.json']
    paths+=sorted((ARCHIVE/'results').rglob('supplemental_actions*.json'))
    paths+=sorted((ARCHIVE/'results').rglob('eastmoney_actions.json'))
    local=BASE/'results/holdout_restricted/june2020_all_starts'
    if local.exists():paths+=sorted(local.glob('supplemental_actions*.json'))
    known=set();events=defaultdict(list);economic={};sources={};resolutions=[];conflicts=[]
    for path in paths:
        data=json.loads(path.read_text(encoding='utf-8'))
        records=data.get('records',{}) if path.name!='actions_merged.json' else data
        if not isinstance(records,dict):raise ValueError(f'Bad action records: {path}')
        for key,rows in records.items():
            known.add(key);symbol=key.split('/')[0]
            for row in rows:
                if not row.get('dividOperateDate'):continue
                date=pd.Timestamp(row['dividOperateDate']).normalize()
                if not pd.Timestamp(start)<=date<=end:continue
                number=lambda k:float(str(row.get(k,0)).strip() or 0)
                cash=number('dividCashPsBeforeTax');taxable=number('dividStocksPs')
                stock=taxable+number('dividReserveToStockPs')
                pay=pd.Timestamp(row.get('dividPayDate') or row['dividOperateDate']).normalize()
                release=pd.Timestamp(row.get('dividStockMarketDate') or row['dividOperateDate']).normalize()
                signature=(cash,stock,taxable,pay,release)
                event_key=(date,symbol)
                if event_key in economic:
                    if economic[event_key]==signature:continue
                    previous=economic[event_key]
                    # Retained audits corrected BaoStock zero/empty economic fields using verified provider receipts.
                    # Never replace a populated economic event by an empty placeholder, or choose between conflicting populated values.
                    old_empty=all(x==0 for x in previous[:3]);new_empty=all(x==0 for x in signature[:3])
                    if old_empty and not new_empty:
                        resolutions.append({'key':key,'date':str(date.date()),'correction_source':str(path.relative_to(ROOT)),
                                            'old':list(map(str,previous)),'corrected':list(map(str,signature))})
                        events[event_key]=[]
                    elif new_empty and not old_empty:continue
                    else:
                        # Unrelated cached-stock conflicts must not be silently fixed or block all research.
                        # Retain first event provisionally, then fail publication if any account actually holds across this date.
                        conflicts.append({'key':key,'symbol':symbol,'date':str(date.date()),'incoming_source':str(path.relative_to(ROOT)),
                                          'first':list(map(str,previous)),'incoming':list(map(str,signature))})
                        continue
                economic[event_key]=signature
                events[event_key].append(dict(cash=cash,stock=stock,taxable_stock=taxable,pay=pay,release=release,source=row.get('source','baostock_cache')))
        sources[str(path.relative_to(ROOT))]=market.digest(path)
    return dict(events),known,sources,resolutions,conflicts

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--software-live',action='store_true');parser.add_argument('--mixed-atr',action='store_true')
    parser.add_argument('--broker-ioc',action='store_true')
    parser.add_argument('--start-group',choices=['june2020','q1_2020','q1_2025','q1_2026'],default='june2020')
    args=parser.parse_args()
    if args.broker_ioc and not args.software_live:parser.error('--broker-ioc requires --software-live')
    if args.mixed_atr and not args.software_live:parser.error('--mixed-atr requires --software-live')
    bounds={'june2020':('2020-06-01','2020-06-30',20),'q1_2020':('2020-01-01','2020-03-31',58),
            'q1_2025':('2025-01-01','2025-03-31',57),'q1_2026':('2026-01-01','2026-03-31',56)}
    start_from,start_until,expected_starts=bounds[args.start_group]
    folder=BASE/'tracker/data';h=market.health(folder);end=pd.Timestamp(h['market_date'])
    identity,inputs=market.pipeline_identity(h)
    verified=json.loads((folder/'pipeline_verification.json').read_text(encoding='utf-8'))
    assert verified['status']=='ok' and verified['pipeline_id']==identity,'Validated signal inputs changed; rerun pipeline verification first'
    panel_path=ROOT/verified['reference_panel'] if verified.get('reference_panel') else folder/f'pipeline_reference_{end.date()}.parquet'
    panel=pd.read_parquet(panel_path)
    assert len(panel)==verified['reference_rows'] and panel.date.max()==end
    signals=market.build_signals(panel);del panel;gc.collect()
    atr_sources={}
    if args.mixed_atr:
        legacy_path=folder/f'pipeline_reference_{end.date()}.parquet'
        legacy_audit=json.loads((folder/'pipeline_verification_d6ed75330031e2e7640b012db41480739a08bd741eba52168f57fee0f2c01dfb.json').read_text(encoding='utf-8'))
        assert legacy_audit['status']=='ok' and legacy_audit['component_max_abs_errors']['atr_pct']==0
        legacy=pd.read_parquet(legacy_path,columns=['date','symbol','atr_pct']).rename(columns={'atr_pct':'legacy_atr'})
        signals=signals.merge(legacy,on=['date','symbol'],how='left',validate='one_to_one')
        pre=signals.date.lt(pd.Timestamp('2025-01-01'))
        assert signals.loc[pre,'legacy_atr'].notna().all()
        signals.loc[pre,'atr_pct']=signals.loc[pre,'legacy_atr']
        signals=signals.drop(columns='legacy_atr')
        atr_sources[str(legacy_path.relative_to(ROOT))]=market.digest(legacy_path)
    # Match original registered all-start account reports: reserve full 7+30 calendar-day maturity tail.
    last=end if args.software_live else end-pd.Timedelta(days=37)
    signals=signals[signals.date.between(start_from,last)].copy()
    index_paths=[ARCHIVE/'results/batch_006_pre2025_active_objectives/inputs/sh000001_eastmoney_pre2025.parquet',
                 ARCHIVE/'results/holdout_restricted/batch_006_defense_post2024_audit/sh000001_holdout_index.parquet']
    # The retained extended benchmark already covers 2019 through the latest cutoff.
    # Use its single continuous series, rather than duplicating the overlapping pre2025 series.
    index=pd.read_parquet(index_paths[1])
    index['date']=pd.to_datetime(index.date).dt.normalize();index['close']=pd.to_numeric(index.close)
    index=index[index.date.le(end)].sort_values('date')
    assert not index.date.duplicated().any() and index.date.max()==end
    index_close=index.set_index('date').close
    calendar=index.date.tolist()
    if args.software_live:
        calendar=sorted(set(calendar)|{pd.Timestamp(d) for d in h['sessions']})
        assert max(calendar)>=end+pd.Timedelta(days=31),'Future expiry calendar insufficient'
    starts=index.loc[index.date.between(start_from,start_until),'date'].tolist()
    assert len(starts)==expected_starts,(len(starts),starts)
    population='june2020_software_live' if args.software_live else 'june2020_all_starts'
    if args.mixed_atr:population='june2020_software_mixed_atr'
    if args.start_group!='june2020':population=f'{population}_{args.start_group}'
    if args.broker_ioc:population=f'broker_ioc_{args.start_group}'
    output=BASE/'results/holdout_restricted'/population/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    output.mkdir(parents=True,exist_ok=False)
    protocol={'strategy':'C04_NEW','execution_mode':'current_tracker_continuous_daily_approximation' if args.software_live else 'legacy_mature_tail',
              'start_population':f'Every SSE session from {start_from} to {start_until}','starts':[str(d.date()) for d in starts],
              'end':str(end.date()),'initial_cash':100000,'slots':5,'last_signal_cutoff_calendar':str(last.date()),
              'last_available_signal':str(signals.date.max().date()),'holding_calendar_days':30,'entry_lifetime_calendar_days':7,
              'take_atr':4.,'stop_atr':1.5,'same_day_double_touch':'stop_first','pipeline_id':identity,
              'execution_atr_policy':'original_mixed_pre2025_relative_tr_post2024_price_tr' if args.mixed_atr else verified.get('execution_atr_policy','original_model_panel_atr'),
              'atr_override_sources':atr_sources,
              'annualization':'(ending_equity/100000)^(365/(end-start).days)-1',
              'annualized_excess':'account annualized return minus SSE Composite annualized price return over identical dates',
              'sharpe':'sqrt(252)*daily_account_return_mean/population_std; zero risk-free rate',
              'exit_counts':'Completed trades only: take, stop, expiry; unfilled expired buy orders excluded',
              'inputs':inputs,'component_panel_sha256':market.digest(panel_path),
              'human_action_assumption':'Review completed nightly; auto-accept affordable nonduplicate top-three in rank order; broker fills approximated, not actual.',
              'fee_fill_assumptions':'Inherited frozen daily engine: commission 0.0003 min5; sell stamp0.001; slippage0.002; daily capacity0.02. Not claimed actual broker charges or five-level fills.',
              'index_sources':{str(p.relative_to(ROOT)):market.digest(p) for p in index_paths}}
    (output/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Output',output,flush=True)
    symbols=set(signals.symbol.astype(str));raw_rows=[]
    columns=['date','open','high','low','close','preclose','volume','amount','tradestatus','symbol']
    for symbol in sorted(symbols):
        b=pd.read_parquet(market.DATA/'raw'/symbol[-2:]/f'{symbol}.parquet',columns=columns)
        b['date']=pd.to_datetime(b.date)
        b=b[b.date.between(min(starts),end)].copy()
        assert not b.date.duplicated().any()
        for col in ['open','high','low','close','preclose','volume','amount']:b[col]=pd.to_numeric(b[col],errors='coerce')
        assert set(b.date)<=set(calendar)
        raw_rows.append(b)
    raw=pd.concat(raw_rows,ignore_index=True)
    bars={symbol:g.set_index('date').sort_index() for symbol,g in raw.groupby('symbol',sort=False)}
    signals=signals.drop(columns='close').merge(raw[['date','symbol','close']],on=['date','symbol'],how='left',validate='one_to_one')
    assert signals.close.notna().all()
    signals=signals.sort_values(['date','score','symbol'],ascending=[True,False,True],kind='stable')
    signals.to_parquet(output/'FROZEN_SIGNALS.parquet',index=False)
    del raw,raw_rows;gc.collect()
    actions,known,action_sources,resolutions,conflicts=action_inputs(end,start_from)
    (output/'ACTION_SOURCES.json').write_text(json.dumps(action_sources,indent=2),encoding='utf-8')
    (output/'ACTION_SOURCE_RESOLUTIONS.json').write_text(json.dumps(resolutions,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'CACHED_ACTION_CONFLICTS.json').write_text(json.dumps(conflicts,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata=pd.read_csv(market.DATA/'metadata/historical_mainboard_universe.csv',dtype=str)
    metadata['outDate']=pd.to_datetime(metadata.outDate,errors='coerce')
    delist=metadata[metadata.outDate.between(min(starts),end)]
    delist=dict(zip(delist.symbol,delist.outDate))
    engine_path=ARCHIVE/'research/run_batch.py';core=module('hushen2_frozen_replay',engine_path)
    assert market.digest(engine_path)=='2474856294d95f52868f82a256b7f557c9d01d00a80a935f5dc24f88f51c843d'
    if args.software_live:
        if args.broker_ioc:
            from broker_execution import broker_engine,POLICY_PATH
            core=broker_engine(core)
            protocol['execution_mode']='broker_fixed_quantity_ioc_daily_approximation'
            protocol['broker_policy']=core.broker_policy
            protocol['exit_counts']='Sell execution legs, including partial exits; not necessarily fully liquidated positions'
        else:
            from software_execution import adapted_engine
            core=adapted_engine(core)
        (output/'SOFTWARE_SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
        protocol['software_quote_expressions']=core.quote_expressions
        protocol['execution_code_hashes']={str(p.relative_to(ROOT)):market.digest(p) for p in [BASE/'tracker/store.py',BASE/'tracker/service.py',Path(__file__).parent/'software_execution.py']}
        if args.broker_ioc:
            for p in [Path(__file__).parent/'broker_execution.py',POLICY_PATH]:protocol['execution_code_hashes'][str(p.relative_to(ROOT))]=market.digest(p)
        (output/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[];all_curves=[];all_trades=[];all_gaps=set();terminal=[];ioc_attempts=[]
    for number,start in enumerate(starts,1):
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(2020,end.year+1))
        gaps=set();curve=[]
        result,trades=core.simulate(signals[signals.date.ge(start)],bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
                                    keep_trades=True,actions=actions,known_action_keys=known,coverage_sink=gaps,
                                    delist_dates=delist,slots=5,equity_curve_sink=curve)
        all_gaps.update(gaps)
        for attempt in result.get('ioc_attempts',[]):ioc_attempts.append(dict(attempt,start_date=str(start.date())))
        c=pd.DataFrame(curve);c['start_date']=start;c['start_ordinal']=number
        assert not c.date.duplicated().any() and c.date.iloc[0]==start and c.date.iloc[-1]==end
        equity=c.equity.astype(float);assert np.isfinite(equity).all() and (equity>0).all()
        daily=equity.pct_change().fillna(equity.iloc[0]/100000-1)
        cumulative=float(equity.iloc[-1]/100000-1);days=(end-start).days
        annual=(1+cumulative)**(365/days)-1
        benchmark=(float(index_close.loc[end]/index_close.loc[start]))**(365/days)-1
        counts=trades.reason.value_counts().to_dict() if not trades.empty else {}
        assert set(counts)<={'take','stop','expiry'} and sum(counts.values())==result['completed_trades']
        row=dict(start_date=str(start.date()),end_date=str(end.date()),cumulative_return=cumulative,
                 annualized_return=annual,annualized_excess=annual-benchmark,beat_sse=annual>benchmark,
                 maximum_drawdown=float((equity/equity.cummax()-1).min()),
                 sharpe=float(np.sqrt(252)*daily.mean()/daily.std(ddof=0)),
                 take_count=counts.get('take',0),stop_count=counts.get('stop',0),expiry_count=counts.get('expiry',0),
                 completed_trades=result['completed_trades'],open_positions=result['open_positions_at_end'],pending_orders=result['pending_orders_at_end'],
                 action_gap_count=len(gaps),delisting_freezes=result['delisting_freezes'],unpaid_receivables=result['unpaid_receivables'])
        rows.append(row);all_curves.append(c)
        terminal.append({'start_date':str(start.date()),'positions':result.get('terminal_positions',[]),'orders':result.get('terminal_orders',[])})
        if not trades.empty:trades['start_date']=start;all_trades.append(trades)
        pd.DataFrame(rows).to_csv(output/'START_METRICS.csv',index=False,encoding='utf-8-sig')
        print(number,len(starts),row['start_date'],f"cumulative={cumulative:.4%}",f'gaps={len(gaps)}',flush=True)
    (output/'ACTION_GAPS.json').write_text(json.dumps(sorted(all_gaps),indent=2),encoding='utf-8')
    (output/'TERMINAL_STATES.json').write_text(json.dumps(terminal,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.broker_ioc:pd.DataFrame(ioc_attempts).to_parquet(output/'IOC_ATTEMPTS.parquet',index=False)
    pd.concat(all_curves,ignore_index=True).to_parquet(output/'EQUITY_CURVES.parquet',index=False)
    trade_frame=pd.concat(all_trades,ignore_index=True)
    trade_frame.to_parquet(output/'TRADES.parquet',index=False)
    runs=pd.DataFrame(rows)
    used_conflicts=[]
    for conflict in conflicts:
        date=pd.Timestamp(conflict['date'])
        affected=trade_frame[trade_frame.symbol.eq(conflict['symbol']) & trade_frame.entry_date.lt(date) & trade_frame.exit_date.ge(date)]
        terminal_affected=sum(1 for account in terminal for pos in account['positions'] if pos['symbol']==conflict['symbol'] and pd.Timestamp(pos['entry_date'])<date<=end)
        if len(affected) or terminal_affected:used_conflicts.append(dict(conflict,affected_trades=len(affected),affected_terminal_positions=terminal_affected))
    if not args.software_live and runs.open_positions.gt(0).any() and conflicts:
        used_conflicts.append({'terminal_open_positions_require_additional_conflict_audit':True})
    (output/'HELD_ACTION_CONFLICTS.json').write_text(json.dumps(used_conflicts,ensure_ascii=False,indent=2),encoding='utf-8')
    summary={'status':'complete' if not all_gaps and not used_conflicts else 'incomplete_action_audit','start_count':len(rows),
             'start_range':[str(min(starts).date()),str(max(starts).date())],'end':str(end.date()),
             'cumulative_return_mean':float(runs.cumulative_return.mean()),'cumulative_return_median':float(runs.cumulative_return.median()),
             'annualized_return_mean':float(runs.annualized_return.mean()),'annualized_excess_mean':float(runs.annualized_excess.mean()),
             'beat_sse_fraction':float(runs.beat_sse.mean()),'maximum_drawdown_mean':float(runs.maximum_drawdown.mean()),
             'sharpe_mean':float(runs.sharpe.mean()),'take_count_mean':float(runs.take_count.mean()),
             'stop_count_mean':float(runs.stop_count.mean()),'expiry_count_mean':float(runs.expiry_count.mean()),
             'corporate_action_gaps':sorted(all_gaps),'held_action_conflicts':used_conflicts,'terminal_open_positions_max':int(runs.open_positions.max()),
             'terminal_pending_orders_max':int(runs.pending_orders.max()),'production_account_changed':False}
    assert market.pipeline_identity(market.health(folder))[0]==identity,'Inputs changed during replay'
    for p,expected in protocol.get('execution_code_hashes',{}).items():assert market.digest(ROOT/p)==expected
    (output/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    if all_gaps or used_conflicts:raise RuntimeError('Held action coverage gaps/conflicts retained; do not publish these metrics as final')

if __name__=='__main__':main()
