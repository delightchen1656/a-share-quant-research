"""Actual recorded account only: event observations and close-to-close cash P&L.

No fill inference, no interpolated prices, no substitution of backtest returns.
Legacy unclassified cash adjustments deliberately make that day's P&L unknown.
"""
from datetime import date
import pandas as pd


def flow_kind(event, classifications):
    return classifications.get(event['id'],event['data'].get('flow_type','unknown'))


def tracking(ledger, sessions, end, data_root, today):
    events=ledger.events()
    settings=ledger.settings()
    active=[e for e in events if not e['voided']]
    classes={int(e['data']['event_id']):e['data']['flow_type'] for e in active if e['kind']=='classify_cash'}
    with ledger.connect() as db:
        observations=[dict(r) for r in db.execute('SELECT * FROM account_observations ORDER BY at,id')]
    observations=[p for p in observations if p['revision']>=settings.get('performance_min_revision',0)]
    curve=[]
    for point in observations:
        flows=[e for e in active if e['kind']=='cash_adjust' and e['id']<=point['revision']]
        external=sum(float(e['data']['amount']) for e in flows if flow_kind(e,classes)=='external')
        unknown=any(flow_kind(e,classes)=='unknown' for e in flows)
        curve.append(dict(point,external_flow=round(external,2),net_equity=None if unknown else round(point['equity']-external,2)))
    unknown=[dict(id=e['id'],date=e['data'].get('date',e['at'][:10]),amount=e['data']['amount'],note=e['data'].get('note',''))
             for e in active if e['kind']=='cash_adjust' and flow_kind(e,classes)=='unknown']
    financial=[e for e in active if e['kind'] in ('buy','sell','cash_adjust')]
    if not end or not financial:
        return dict(curve=curve,daily=[],unknown_cash_adjustments=unknown,asof=end,today=today,calendar_sessions=sessions)
    effective=lambda e:e['data'].get('date',e['at'][:10])
    start=min(effective(e) for e in financial)
    days=sorted({d for d in sessions if start<=d<=end}|{effective(e) for e in financial if start<=effective(e)<=end})
    symbols={e['data']['symbol'] for e in active if e['kind']=='accept'}
    quotes={}
    for symbol in symbols:
        path=data_root/'raw'/symbol[-2:]/f'{symbol}.parquet'
        if path.exists():
            q=pd.read_parquet(path,columns=['date','close'])
            q['date']=pd.to_datetime(q.date).dt.strftime('%Y-%m-%d')
            quotes[symbol]=dict(zip(q.date,pd.to_numeric(q.close,errors='coerce')))
    rows=[];previous=ledger.initial_cash();session_set=set(sessions)
    for day in days:
        # Orders have no cash effect; include accepts so late-entered actual
        # fills can be reconstructed on their ACTUAL dates, not entry timestamps.
        subset=[e for e in active if e['kind']=='accept' or (e['kind'] in ('buy','sell','cash_adjust') and effective(e)<=day)]
        state=ledger.state(asof=day,events=subset)
        equity=state['cash']+state['deferred'];missing=[]
        for position in state['positions']:
            q=quotes.get(position['symbol'],{})
            mark=q.get(day)
            if day not in session_set:
                prior=max((d for d in q if d<=day),default=None);mark=q.get(prior)
            if mark is None or not pd.notna(mark) or mark<=0:missing.append(position['symbol'])
            else:equity+=position['quantity']*float(mark)
        equity=None if missing else round(equity,2)
        cash_events=[e for e in financial if e['kind']=='cash_adjust' and effective(e)==day]
        flow=sum(float(e['data']['amount']) for e in cash_events if flow_kind(e,classes)=='external')
        uncertain=any(flow_kind(e,classes)=='unknown' for e in cash_events)
        pnl=None if equity is None or previous is None or uncertain else round(equity-previous-flow,2)
        opening_baseline=day==settings.get('pnl_baseline_date')
        if opening_baseline:pnl=None
        rows.append(dict(day=day,equity=equity,pnl=pnl,external_flow=round(flow,2),
                         is_session=day in session_set,source='recorded_ledger_and_raw_close',
                         status='missing_price' if missing else 'opening_baseline' if opening_baseline else 'unclassified_cash' if uncertain else 'ready',missing_symbols=missing))
        previous=equity
    return dict(curve=curve,daily=rows,unknown_cash_adjustments=unknown,asof=end,today=today,calendar_sessions=sessions)
