"""Forward paper account. Uses previously frozen signals only; never sends live orders."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json,hashlib,sys,os
import pandas as pd
HERE=Path(__file__).resolve().parent;HOME=HERE.parent;ROOT=HOME.parents[1]
sys.path.insert(0,str(HOME/'backtest'))
import engine as e

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str),encoding='utf-8');tmp.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build_daily_report(cfg,target,account,result,trades,names):
    """Create the small user-facing account/position/trade tables."""
    open_cost={};open_qty={}
    for trade in trades:
        symbol=trade['symbol'];qty=int(trade['qty']);price=float(trade['price'])
        held=open_qty.get(symbol,0);cost=open_cost.get(symbol,0.)
        if qty>0:
            open_qty[symbol]=held+qty;open_cost[symbol]=cost+qty*price
        elif held>0:
            sold=min(-qty,held);average=cost/held
            open_qty[symbol]=held-sold;open_cost[symbol]=cost-average*sold
    positions=[]
    for symbol,holding in sorted(account.holdings.items()):
        qty=int(holding['qty']);close=float(holding['last'])
        # Quantity may change through a verified corporate action. Economic
        # open cost is retained and divided by the current credited shares.
        cost=open_cost.get(symbol)
        average=(cost/qty) if cost is not None and qty>0 else None
        market_value=qty*close
        pnl=(market_value-cost) if cost is not None else None
        positions.append(dict(symbol=symbol,name=names.get(symbol,''),quantity=qty,
            average_buy_price=average,close=close,market_value=market_value,
            unrealized_pnl=pnl,unrealized_return=(pnl/cost if pnl is not None and cost else None)))
    curve=account.curve;last=curve[-1]
    previous_equity=float(curve[-2]['equity']) if len(curve)>1 else float(cfg['initial_cash'])
    today_trades=[t for t in trades if t['date']==target]
    payload=dict(asof=target,account=dict(initial_cash=float(cfg['initial_cash']),
        equity=float(last['equity']),cash=float(last['cash']),market_value=float(last['market_value']),
        exposure=float(last['exposure']),daily_pnl=float(last['equity'])-previous_equity,
        cumulative_pnl=float(last['equity'])-float(cfg['initial_cash']),
        cumulative_return=float(last['equity'])/float(cfg['initial_cash'])-1,
        cumulative_fees=float(result['total_cost'])),positions=positions,today_trades=today_trades)
    save(HERE/'daily_report.json',payload)
    money=lambda x:'-' if x is None else f'{x:,.2f}'
    percent=lambda x:'-' if x is None else f'{x*100:.2f}%'
    a=payload['account']
    lines=[f'# 沪深1本地模拟 · {target}','',
        '| 初始资金 | 总资产 | 现金 | 持仓市值 | 仓位 | 当日盈亏 | 累计盈亏 | 累计收益 | 累计费用 |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
        f"| {money(a['initial_cash'])} | {money(a['equity'])} | {money(a['cash'])} | {money(a['market_value'])} | {percent(a['exposure'])} | {money(a['daily_pnl'])} | {money(a['cumulative_pnl'])} | {percent(a['cumulative_return'])} | {money(a['cumulative_fees'])} |",'',
        '| 代码 | 名称 | 数量 | 买入均价 | 收盘价 | 持仓市值 | 浮动盈亏 | 浮动收益 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for x in positions:
        lines.append(f"| {x['symbol']} | {x['name']} | {x['quantity']} | {money(x['average_buy_price'])} | {money(x['close'])} | {money(x['market_value'])} | {money(x['unrealized_pnl'])} | {percent(x['unrealized_return'])} |")
    lines+=['','| 操作 | 代码 | 名称 | 数量 | 成交价 | 佣金 | 过户费 | 印花税 | 分红税 |','|---|---|---|---:|---:|---:|---:|---:|---:|']
    if today_trades:
        for x in today_trades:
            lines.append(f"| {'买入' if x['qty']>0 else '卖出'} | {x['symbol']} | {names.get(x['symbol'],'')} | {abs(int(x['qty']))} | {money(x['price'])} | {money(x['commission'])} | {money(x['transfer'])} | {money(x['stamp'])} | {money(x['dividend_tax'])} |")
    else:lines.append('| 无成交 | - | - | - | - | - | - | - | - |')
    (HERE/'daily_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return payload
def main():
    lock=HERE/'run.lock'
    try:fd=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('Tracking lock exists; inspect running process before retrying')
    try:
        os.close(fd);run()
    except Exception as exc:
        save(HERE/'last_error.json',dict(error=str(exc),at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()))
        raise
    finally:lock.unlink()
def run():
    cfg=read(HERE/'config.json');assert sha(HOME/'supermind_hushen_1.py')==cfg['entry_sha256'],'Strategy changed; review before accepting'
    data=e.r.DATA;meta=data/'metadata';refresh=sorted(meta.glob('refresh_*.json'))[-1];audit=read(refresh)
    assert audit['status']=='ok'
    target=audit['target'];committed=ROOT/'data_updates'/target.replace('-','')/'audit.json'
    assert read(committed)['status']=='ok' and read(committed)['target']==target
    # An active update must not be read as a consistent snapshot.
    for f in (ROOT/'data_updates').rglob('*.lock'):
        raise RuntimeError('Market update lock present: '+str(f))
    calendar=pd.read_csv(meta/('trade_calendar_'+target.replace('-','')+'.csv'))
    dates=pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar.iloc[:,1].astype(str).eq('1')].iloc[:,0]))
    dates=dates[dates>=pd.Timestamp('2018-01-01')];assert dates[-1]==pd.Timestamp(target)
    signals=HERE/'signals';signals.mkdir(exist_ok=True)
    source=e.r.mod(HOME/'supermind_hushen_1.py','tracking_source')
    latest=signals/(target+'.json')
    manifest=[];raw={}
    universe=pd.read_csv(meta/'historical_mainboard_universe.csv').set_index('symbol')
    for path in sorted((data/'raw').glob('*/*.parquet')):
        x=pd.read_parquet(path);x.date=pd.to_datetime(x.date)
        assert not x.date.duplicated().any()
        x=x[x.date<=target].set_index('date').sort_index()
        assert path.stem in universe.index
        u=universe.loc[path.stem];out=pd.to_datetime(u.outDate,errors='coerce')
        if pd.isna(out) or out>pd.Timestamp(target):
            # A security may remain in the historical universe while trading is
            # already suspended.  Do not fabricate bars or remove it early;
            # accept the missing target row only when the target-date security
            # master has already marked it inactive and its last vendor row is
            # an explicit suspended row.
            current_status = int(float(u.status))
            last_status = int(float(x.iloc[-1].tradestatus))
            if x.index.max()!=pd.Timestamp(target):
                assert current_status==0 and last_status==0, ('Missing latest active stock',path.stem)
        y=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'}).copy()
        y['is_paused']=1-pd.to_numeric(y.tradestatus);raw[path.stem]=y[source.FIELDS].astype(float).iloc[-320:]
        manifest.append(dict(symbol=path.stem,sha256=sha(path)))
    if not latest.exists():
        ds=dates[-source.SMOOTH:];members={}
        for d in ds:
            members[str(d.date())]={s for s,u in universe.iterrows() if pd.Timestamp(u.ipoDate)<=d and (pd.isna(u.outDate) or pd.Timestamp(u.outDate)>d)}
        wanted=set().union(*members.values());ranks,info=source.compute_signals({s:x for s,x in raw.items() if s in wanted},members,ds)
        assert ranks
        save(latest,dict(asof=target,created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),strategy_sha256=cfg['entry_sha256'],ranks=ranks,input_hashes=manifest,meaning='ranking only; target quantities require next session opening prices'))
    # Do not create retroactive signals for missed execution sessions.
    sessions=dates[dates>=pd.Timestamp(cfg['not_before'])]
    ranks={}
    for f in signals.glob('*.json'):ranks[f.stem]=read(f)['ranks']
    if not len(sessions):
        save(HERE/'tracker.json',dict(status='awaiting_first_trading_session',asof=target,cash=cfg['initial_cash'],equity=cfg['initial_cash'],holdings={},trades=[],signal_file=str(latest.relative_to(HERE)),not_before=cfg['not_before']))
        print('READY',target,'cash',cfg['initial_cash'],'no executed trades');return
    for i,d in enumerate(sessions):
        index=dates.get_loc(d)
        if i==0 or (index-1)%source.INTERVAL==0:assert str(dates[index-1].date()) in ranks,('Missing previously frozen signal; do not backfill',str(d.date()))
    work=HERE/'ledger_inputs';work.mkdir(exist_ok=True)
    pd.DataFrame({'date':dates}).to_parquet(work/'calendar.parquet',index=False)
    save(work/'inputs.json',{'files':manifest});save(work/'rankings_original.json',ranks)
    e.HERE=work;e.r.HERE=work;e.r.Q=dict(e.r.Q,end=target)
    # Reuse audited market/account code with a current verified calendar.
    text=(HOME/'backtest/engine.py').read_text(encoding='utf-8')
    text=text.replace("BASE/'data/benchmark.parquet'","HERE/'calendar.parquet'")
    exec(compile(text,str(HOME/'backtest/engine.py'),'exec'),e.__dict__)
    # Tracking has its own audited action responses.  Make them visible to the
    # shared engine without copying local account evidence into backtest data.
    e.actions.OWN_PATH=work/'additional_actions.json'
    market=e.Market()
    try:result,account=e.simulate(market,str(sessions[0].date()),target,initial=cfg['initial_cash'])
    finally:market.actions.close()
    current=[dict(t,date=str(t['date'].date()),start=str(t['start'])) for t in account.trades]
    previous=read(HERE/'tracker.json') if (HERE/'tracker.json').exists() else {}
    old=previous.get('trades',[])
    assert current[:len(old)]==old,'Historical fills changed; stop reconciliation'
    save(HERE/'tracker.json',dict(status='active',asof=target,metrics=result,cash=account.cash,equity=account.curve[-1]['equity'],holdings=account.holdings,trades=current))
    pd.DataFrame(account.curve).to_parquet(HERE/'equity.parquet',index=False)
    names=universe['code_name'].to_dict()
    build_daily_report(cfg,target,account,result,current,names)
    print('UPDATED',target,result['final_equity'],'fills',len(current))
if __name__=='__main__':main()
