"""Ongoing-account replay from a chosen signal close; no terminal entry blackout."""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import argparse,json,pickle,sys
import numpy as np
import pandas as pd
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--signal-start',default='2026-10-19');args=parser.parse_args()
    start=pd.Timestamp(args.signal_start)
    out=ROOT/'archive/reports/holdout_restricted/hushen2_recent_start'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True)
    print('OUTPUT',out,flush=True)
    sys.path.insert(0,str(APP/'tracker'));sys.path.insert(0,str(APP/'runtime'))
    market=load('recent_start_market',APP/'tracker/market.py');health=market.health(APP/'tracker/data')
    market.pipeline_identity(health);end=pd.Timestamp(health['market_date'])
    # Future EXCHANGE CALENDAR is known; future prices are never read. Do not
    # truncate this calendar at the observation end or30-day deadlines would
    # incorrectly clamp to the final observed session and force an early exit.
    calendar=[pd.Timestamp(d) for d in health['sessions']]
    assert calendar[-1]>=end+pd.Timedelta(days=30),'Need formal calendar covering existing holding deadlines'
    assert start in calendar and start<end
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['slots']==5 and selection['selection']['signal_filter']['minimum_atr']==.025
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',CASES/'INPUT_SIGNALS.parquet']
    protected+=list((STRATEGY/'model').glob('*.txt'))+list((APP/'runtime').glob('*.py'))
    before={str(p):sha(p) for p in protected}
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for relative,digest in manifest[group].items():assert sha(GAME/relative)==digest
    with (CASES/'INPUT_PACK.pkl').open('rb') as stream:p=pickle.load(stream)
    last_frozen=p['signals'].date.max();signals=p['signals'].loc[p['signals'].date.between(start,end)].copy();cache_inputs=[]
    for day in [d for d in health['sessions'] if last_frozen<pd.Timestamp(d)<=end]:
        path=market.signal_cache_path(APP/'tracker/data',day);payload=json.loads(path.read_text(encoding='utf-8'))
        assert payload['market_date']==day and market.signals_digest(payload['signals'])==payload['signals_sha256']
        market.validate_signals(payload['signals'],dict(health,market_date=day))
        extra=pd.DataFrame([dict(date=pd.Timestamp(day),symbol=s['symbol'],close=s['trigger'],atr_pct=s['atr'],score=s['score'],factor='C04_NEW') for s in payload['signals']])
        signals=pd.concat([signals,extra],ignore_index=True);cache_inputs.append(dict(path=str(path),sha256=sha(path)))
    signals=signals.loc[signals.date.between(start,end)].sort_values(['date','score','symbol'],ascending=[True,False,True]).reset_index(drop=True)
    assert not signals.duplicated(['date','symbol']).any() and signals.atr_pct.ge(.025).all()
    bars={};price_inputs={}
    for symbol in signals.symbol.unique():
        path=market.DATA/'raw'/symbol[-2:]/f'{symbol}.parquet';price_inputs[str(path)]=sha(path)
        b=pd.read_parquet(path);b.date=pd.to_datetime(b.date);b=b.loc[b.date.le(end)].sort_values('date')
        assert not b.date.duplicated().any()
        for k in ('open','high','low','close','preclose','volume','amount','tradestatus'):b[k]=pd.to_numeric(b[k],errors='raise')
        bars[symbol]=b.set_index('date')
    adapter=load('recent_fixed_ioc',GAME/'runtime/baseline_fixed_ioc.py');original=load('recent_original_core',GAME/'runtime/run_batch.py')
    core=adapter.fixed_ioc_engine(original,manual_expiry_open=False,filled_slots=False)
    source=core.adapted_source;anchor='result["fixed_order_attempts"] = fixed_order_attempts';assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'\n    result["terminal_positions"]=[asdict(h) for h in holdings]\n    result["terminal_cash"]=cash\n    result["terminal_deferred"]=deferred_cash\n    result["terminal_receivables"]=sum(x[1] for x in receivables)\n    result["terminal_pending"]=[asdict(x) for x in pending]')
    core.asdict=asdict;exec(compile(source,'<recent_start_account_diagnostics>','exec'),core.__dict__)
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=list(range(start.year,end.year+1))
    curve=[];gaps=set()
    r,t=core.simulate(signals,bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,
        actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    if gaps:
        import socket,baostock as bs
        socket.setdefaulttimeout(10)
        print('FETCH_ACTION_COVERAGE',sorted(gaps),flush=True)
        login=bs.login();assert login.error_code=='0'
        folder=out/'action_receipts';folder.mkdir()
        try:
            for key in sorted(gaps):
                symbol,year=key.split('/');response=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');records=[]
                while response.error_code=='0' and response.next():records.append(dict(zip(response.fields,response.get_row_data())))
                assert response.error_code=='0'
                receipt=folder/(key.replace('/','_')+'.json');receipt.write_text(json.dumps(dict(key=key,error_code=response.error_code,records=records,fields=response.fields,fetched_at=datetime.now().isoformat()),ensure_ascii=False,indent=2),encoding='utf-8')
                p['known'].add(key)
                for record in records:
                    if not record.get('dividOperateDate'):continue
                    day=pd.Timestamp(record['dividOperateDate']);num=lambda k:float(str(record.get(k,'')).strip() or 0)
                    p['actions'].setdefault((day,symbol),[]).append(dict(cash=num('dividCashPsBeforeTax'),stock=num('dividStocksPs')+num('dividReserveToStockPs'),
                        taxable_stock=num('dividStocksPs'),pay=pd.Timestamp(record.get('dividPayDate') or day),release=pd.Timestamp(record.get('dividStockMarketDate') or day),source=str(receipt)))
                print('ACTION_RECEIPT',key,'records',len(records),flush=True)
        finally:bs.logout()
        curve=[];gaps=set()
        r,t=core.simulate(signals,bars,calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,
            actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    assert not gaps,'Company action coverage missing: '+str(sorted(gaps))
    c=pd.DataFrame(curve);c['start_ordinal']=1;c['start_date']=start
    risk=load('recent_risk',STRATEGY/'backtest/compute_risk_metrics.py');metrics=risk.recompute_metrics(c).iloc[0].to_dict()
    a=pd.DataFrame(r['fixed_order_attempts']);positions=r['terminal_positions'];pending=r['terminal_pending'];unrealized=0.;position_value=0.
    for h in positions:
        if pd.Timestamp(h['deadline'])>end:assert pd.Timestamp(h['expiry_session'])>end
    if len(t):
        expiry=t.loc[t.reason.eq('expiry')]
        for trade in expiry.itertuples():
            deadline=pd.Timestamp(trade.entry_date)+pd.Timedelta(days=30)
            assert pd.Timestamp(trade.exit_date)==max(d for d in calendar if d<=deadline)
    for h in positions:
        mark=float(bars[h['symbol']].loc[:end,'close'].iloc[-1]);value=h['frozen_value'] if h['frozen'] else h['shares']*mark
        h.update(mark=mark,market_value=value,unrealized_net=value+h['dividends']-h['entry_cost'])
        unrealized+=h['unrealized_net'];position_value+=value
    realized=float(t.pnl.sum()) if len(t) else 0.
    assert abs(float(c.equity.iloc[-1])-100000-realized-unrealized)<1e-6
    assert abs(r['terminal_cash']+r['terminal_deferred']+r['terminal_receivables']+position_value-c.equity.iloc[-1])<1e-6
    filled=int(a.filled_quantity.gt(0).sum()) if len(a) else 0;zero=int(a.filled_quantity.eq(0).sum()) if len(a) else 0
    assert filled==r['filled_orders']==len(t)+len(positions)
    assert r['pending_orders_created']==filled+zero+r['expired_entry_orders']+len(pending)
    assert (pd.to_datetime(a.date)>pd.to_datetime(a.signal_date)).all() and pd.to_datetime(a.date).min()>=min(d for d in calendar if d>start)
    for name,frame in [('EQUITY_CURVE',c),('TRADES',t),('ORDER_ATTEMPTS',a),('SIGNALS',signals)]:frame.to_parquet(out/(name+'.parquet'),index=False)
    c.to_csv(out/'DAILY_EQUITY.csv',index=False,encoding='utf-8-sig');(out/'SIMULATE_SOURCE.txt').write_text(source,encoding='utf-8')
    after=market.health(APP/'tracker/data');assert after['audit_sha256']==health['audit_sha256']
    assert all(sha(Path(path))==digest for path,digest in {**before,**price_inputs}.items())
    report=dict(status='verified',signal_start=str(start.date()),first_buy_eligible=str(min(d for d in calendar if d>start).date()),end=str(end.date()),
        initial_cash=100000,ending_equity=float(c.equity.iloc[-1]),net_pnl=float(c.equity.iloc[-1]-100000),metrics=metrics,
        realized_pnl=realized,unrealized_pnl=unrealized,cash=r['terminal_cash'],deferred_cash=r['terminal_deferred'],receivables=r['terminal_receivables'],
        created=r['pending_orders_created'],filled=filled,failed=zero+r['expired_entry_orders'],cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()),
        expired_untriggered=r['expired_entry_orders'],takes=int(t.reason.eq('take').sum()),stops=int(t.reason.eq('stop').sum()),expiries=int(t.reason.eq('expiry').sum()),
        positions=positions,pending=pending,signal_cache_inputs=cache_inputs,protected_before=before,price_inputs=price_inputs,
        policy='Current5slots20%,ATR025 original top3/no refill,fixedIOC,2pctvolume,7/30calendar,T+1,stop-first,original fees/slippage,expiryclose; ongoing observation: no final37day entry blackout,no forced end liquidation',
        account_and_software_unchanged=True)
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('OUTPUT',out,flush=True);print(json.dumps({k:v for k,v in report.items() if k not in ('protected_before','price_inputs','signal_cache_inputs')},ensure_ascii=False,indent=2,default=str),flush=True)
    print('DAILY\n'+c[['date','equity']].to_string(index=False));print('TRADES\n'+t.to_string(index=False));print('ATTEMPTS\n'+a.to_string(index=False))


if __name__=='__main__':main()
