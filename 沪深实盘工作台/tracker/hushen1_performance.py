"""Reconstruct manual Hushen1 closing marks from recorded events, never fills."""
import pandas as pd


def build(desk, sessions, end, data_root, today):
    active=[e for e in desk.events() if not e['voided']]
    effective=lambda e:e['data'].get('date',desk.config['created_date'])
    classes={int(e['data']['event_id']):e['data']['flow_type'] for e in active if e['kind']=='classify_cash'}
    flow_kind=lambda e:classes.get(e['id'],e['data'].get('flow_type','unknown'))
    symbols={e['data']['symbol'] for e in active if e['kind'] in ('buy','sell','corporate')}
    quotes={}
    for s in symbols:
        path=data_root/'raw'/s[-2:]/(s+'.parquet')
        if path.exists():
            q=pd.read_parquet(path,columns=['date','close'])
            q['date']=pd.to_datetime(q.date).dt.strftime('%Y-%m-%d')
            if q.date.duplicated().any():raise ValueError('收盘行情日期重复：'+s)
            quotes[s]=dict(zip(q.date,pd.to_numeric(q.close,errors='coerce')))
    days=[d for d in sessions if desk.config['created_date']<=d<=min(end,today)]
    previous=float(desk.config['initial_cash']);external=0.;uncertain=False;rows=[]
    unknown=[dict(id=e['id'],date=effective(e),amount=e['data']['amount'],note=e['data'].get('note',''))
             for e in active if e['kind']=='cash_adjust' and flow_kind(e)=='unknown']
    for day in days:
        state=desk.account([e for e in active if effective(e)<=day])
        equity=state['cash'];missing=[];marks={}
        for p in state['positions']:
            mark=quotes.get(p['symbol'],{}).get(day)
            if mark is None or not pd.notna(mark) or mark<=0:missing.append(p['symbol'])
            else:equity+=p['quantity']*float(mark);marks[p['symbol']]=float(mark)
        equity=None if missing else round(equity,2)
        adjustments=[e for e in active if e['kind']=='cash_adjust' and effective(e)==day]
        flow=sum(e['data']['amount'] for e in adjustments if flow_kind(e)=='external')
        unknown_today=any(flow_kind(e)=='unknown' for e in adjustments)
        external+=flow;uncertain=uncertain or unknown_today
        pnl=None if equity is None or previous is None or unknown_today else round(equity-previous-flow,2)
        daily_return=None if pnl is None or not previous or previous<=0 else pnl/previous
        net=None if uncertain or equity is None else round(equity-external,2)
        rows.append(dict(day=day,equity=equity,pnl=pnl,net_equity=net,
            cumulative_pnl=None if net is None else round(net-desk.config['initial_cash'],2),
            daily_return=daily_return,cumulative_return=None if net is None else (net-desk.config['initial_cash'])/desk.config['initial_cash'],
            external_flow=round(flow,2),cash=state['cash'],marks=marks,
            missing_symbols=missing,status='missing_price' if missing else 'unclassified_cash' if unknown_today else 'ready'))
        previous=equity
    return dict(daily=rows,curve=rows,asof=end,today=today,calendar_sessions=sessions,
                unknown_cash_adjustments=unknown,error='',source='actual_recorded_events_and_committed_raw_close')
