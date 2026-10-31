"""One-way posterior audit of the frozen leader-pool variants. No fitting."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
import argparse
import ast
import json
import pickle
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

from research_hushen2_leader_pool import VARIANTS, LEADERS, ranked
from replay_hushen2_local import ROOT, STRATEGY, APP, GAME, CASES, sha, load
from research_hushen2_buy_weekdays import make_engine

PRE = ROOT / 'archive/reports/holdout_restricted/hushen2_leader_pool/pre2025_20261028_200500'
DATA = ROOT / 'K线数据/沪深'
G = {}


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def market_health():
    import subprocess
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'daily_market_update\\.py' } | Select-Object -ExpandProperty ProcessId"
    r = subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,check=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    assert not r.stdout.strip(), 'Updater still running'
    assert not list((ROOT/'K线数据/更新备份与审计').glob('*/staging')), 'Uncommitted staging exists'
    candidates = sorted((ROOT/'K线数据/更新备份与审计').glob('*/audit.json'), reverse=True)
    ap = next(p for p in candidates if json.loads(p.read_text(encoding='utf-8')).get('status')=='ok')
    a = json.loads(ap.read_text(encoding='utf-8'))
    date = a['target']
    assert a['committed_files'] and a['validation']['transactional_staging']
    assert a['validation']['active_symbol_latest_date']==date
    refresh = DATA/'metadata'/f"refresh_{date.replace('-','')}.json"
    m = json.loads(refresh.read_text(encoding='utf-8'))
    assert all(m.get(k)==a.get(k) for k in ('status','target','updated_at','datasets','validation'))
    commit = ap.parent/'commit_manifest.json'
    cm = json.loads(commit.read_text(encoding='utf-8'))
    assert cm['target']==date and len(cm['files'])==a['committed_files']
    cal = DATA/'metadata'/f"trade_calendar_{date.replace('-','')}.csv"
    c = pd.read_csv(cal,dtype=str)
    days = list(pd.to_datetime(c.loc[c.is_trading_day.eq('1'),'calendar_date']))
    assert pd.Timestamp(date) in days
    return dict(end=date,audit=str(ap),audit_sha256=sha(ap),refresh_sha256=sha(refresh),commit_sha256=sha(commit),calendar_sha256=sha(cal)),days


def components(out):
    cp = out/'COMPONENT_PANEL_FROZEN_20261022.parquet'
    if cp.exists():return pd.read_parquet(cp)
    prior = pd.read_parquet(PRE/'COMPONENT_PANEL_PRE2025.parquet')
    evidence = json.loads((PRE/'PANEL_INPUTS.json').read_text(encoding='utf-8'))
    text = (APP/'tracker/market.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='model_features')
    source = ast.get_source_segment(text,node)
    assert source==evidence['feature_source']
    namespace=dict(pd=pd,np=np,SIGNAL_START='2015-01-01')
    exec(compile(source,'<unchanged_frozen_features>','exec'),namespace)
    manifest=json.loads((GAME/'frozen_inputs/market/DOWNLOAD_COMPLETE.json').read_text(encoding='utf-8'))
    assert manifest['end']=='2026-10-22'
    models={}
    for name,expected in evidence['models'].items():
        path=STRATEGY/'model'/f'{name}.txt';assert sha(path)==expected
        models[name]=lgb.Booster(model_str=path.read_text(encoding='utf-8'))
    rows=[];inputs={}
    for i,(symbol,files) in enumerate(manifest['receipts'].items(),1):
        if symbol in evidence['excluded_symbols']:continue
        rel,expected=next((r,h) for r,h in files.items() if 'qfq' in r)
        path=GAME/'frozen_inputs/market'/rel;assert sha(path)==expected
        inputs[str(path.relative_to(ROOT))]=expected
        b=pd.read_parquet(path).sort_values('date').reset_index(drop=True)
        if len(b)<120:continue
        b['date']=pd.to_datetime(b.date);assert b.date.max()<=pd.Timestamp('2026-10-22')
        for c in ['open','high','low','close','preclose','volume','amount','turn','tradestatus','isST']:
            b[c]=pd.to_numeric(b[c],errors='coerce')
        b['symbol']=symbol
        f=namespace['model_features'](b)
        f=f.loc[f.date.ge('2025-01-01')]
        if len(f):rows.append(f)
        if i%600==0:print('FEATURE_FILES',i,len(manifest['receipts']),flush=True)
    p=pd.concat(rows,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    for name,model in models.items():
        p[name]=model.predict(p[model.feature_name()],num_threads=4)
    p['pen100']=0.
    p['_cap']=p.f_log_amount-np.log(p.f_turn.clip(lower=1e-6))
    r=p.groupby('date')[['_cap','vol60','overnight20','intraday20','mom120','close_to_high60','mom20']].rank(pct=True,method='average')-.5
    p['h_size_neg']=-r['_cap'];p['h_vol60_neg']=-r.vol60;p['h_overnight_pos']=r.overnight20;p['h_intraday_neg']=-r.intraday20
    p['t_mom120_pos']=r.mom120;p['t_high60_pos']=r.close_to_high60;p['t_mom20_pos']=r.mom20;p['t_vol60_neg']=-r.vol60
    allp=pd.concat([prior,p[prior.columns]],ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    assert not allp.duplicated(['date','symbol']).any()
    allp.to_parquet(cp,index=False)
    dump(out/'PANEL_INPUTS.json',dict(qfq_snapshot='2026-10-22',quote_hashes=inputs,models=evidence['models'],prior_panel_sha256=sha(PRE/'COMPONENT_PANEL_PRE2025.parquet'),feature_source=source))
    return allp


def prepare(out):
    health,days=market_health();end=pd.Timestamp(health['end'])
    assert end>=pd.Timestamp('2026-10-22') and end<=pd.Timestamp('2026-11-28'), 'Signal snapshot too old for 37day terminal gate'
    before={str(p):sha(p) for p in [STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',PRE/'PROTOCOL.json']+list((STRATEGY/'model').glob('*.txt'))}
    protocol=dict(scope='2025 and2026 yearly Q1 full starts, same year end/latest committed date',variants=VARIANTS,end=health['end'],frozen_pre_protocol_sha256=sha(PRE/'PROTOCOL.json'),protected_before=before,market_health=health,parameters_changed=False,retraining=False,holdout_feedback=False,caution='Current20261027 leader classification retrospectively applied; not historical membership or fresh blind development',signal_vintage='FrozenOct22 qfq, no rebase. Latest entries stop37calendar days before endpoint. Actual raw bars extended only after overlapping prices verified.')
    dump(out/'PROTOCOL.json',protocol)
    p=pickle.load((CASES/'INPUT_PACK.pkl').open('rb'));frozen_end=pd.Timestamp(p['end'])
    panel=components(out)
    spec=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))['selection']['factor_spec']
    builder=load('posterior_leader_builder',STRATEGY/'runtime/frozen_builder.py')
    codes=set(json.loads(LEADERS.read_text(encoding='utf-8-sig')))
    full=ranked(panel,builder,spec);pool=panel.loc[panel.symbol.str[:6].isin(codes)].copy()
    cols=[c for c in pool if c.startswith(('t_','h_'))]
    pool[cols]=pool.groupby('date',sort=False)[cols].rank(pct=True,method='average')-.5
    pr=ranked(pool,builder,spec)
    full=full.loc[full.date.ge('2025-01-01')];pr=pr.loc[pr.date.ge('2025-01-01')]
    top=full.groupby('date',sort=False).head(3)
    signals=dict(current=top.copy(),leader_no_refill=top.loc[top.symbol.str[:6].isin(codes)].copy(),leader_refill=full.loc[full.symbol.str[:6].isin(codes)].groupby('date',sort=False).head(3).copy(),leader_pool_rank=pr.groupby('date',sort=False).head(3).copy())
    manifest=json.loads((GAME/'frozen_inputs/market/DOWNLOAD_COMPLETE.json').read_text(encoding='utf-8'))
    symbols=sorted(set().union(*(set(s.symbol) for s in signals.values())))
    raw_hashes={};extended=[]
    numeric=['open','high','low','close','preclose','volume','amount']
    for symbol in symbols:
        if symbol not in p['bars']:
            rel,expected=next((r,h) for r,h in manifest['receipts'][symbol].items() if 'raw' in r)
            path=GAME/'frozen_inputs/market'/rel;assert sha(path)==expected
            b=pd.read_parquet(path);b.date=pd.to_datetime(b.date)
            for c in numeric:b[c]=pd.to_numeric(b[c],errors='raise')
            p['bars'][symbol]=b.set_index('date').sort_index()[next(iter(p['bars'].values())).columns]
        local=DATA/'raw'/symbol[-2:]/f'{symbol}.parquet'
        if not local.exists():
            assert p['delists'].get(symbol,pd.Timestamp.max)<=frozen_end,symbol
            continue
        raw_hashes[str(local.relative_to(ROOT))]=sha(local)
        b=pd.read_parquet(local);b.date=pd.to_datetime(b.date)
        for c in numeric:b[c]=pd.to_numeric(b[c],errors='raise')
        b=b.set_index('date').sort_index();old=p['bars'][symbol]
        overlap=old.index[(old.index>=pd.Timestamp('2025-01-01'))&(old.index<=frozen_end)]
        assert len(b.index.intersection(overlap))==len(overlap),symbol
        for c in numeric:assert np.allclose(b.loc[overlap,c],old.loc[overlap,c],rtol=1e-10,atol=1e-7,equal_nan=True),(symbol,c)
        tail=b.loc[(b.index>frozen_end)&(b.index<=end)]
        if len(tail):p['bars'][symbol]=pd.concat([old,tail[old.columns]]);extended.append(symbol)
    look=pd.concat([pd.DataFrame(dict(date=p['bars'][s].index,symbol=s,close=p['bars'][s].close.to_numpy())) for s in symbols],ignore_index=True)
    for v,s in signals.items():
        s=s.drop(columns='close').merge(look,on=['date','symbol'],how='left',validate='one_to_one')
        assert s[['close','atr_pct']].notna().all().all()
        signals[v]=s.loc[s.atr_pct.ge(.025)].sort_values(['date','score','symbol'],ascending=[True,False,True]).reset_index(drop=True)
    reference=p['signals'].loc[p['signals'].date.ge('2025-01-01')].sort_values(['date','score','symbol'],ascending=[True,False,True]).reset_index(drop=True)
    pd.testing.assert_frame_equal(signals['current'][['date','symbol']],reference[['date','symbol']])
    for c in ['score','atr_pct','close']:assert np.allclose(signals['current'][c],reference[c],atol=1e-12,rtol=1e-12),c
    for v,s in signals.items():s.to_parquet(out/f'SIGNALS_{v}.parquet',index=False)
    p['calendar']=sorted(set(p['calendar'])|{d for d in days if frozen_end<d<=end})
    p['calendar']=[d for d in p['calendar'] if d<=end]
    # Read-only public index query through the unified market updater's adapter.
    indexpath=out/'INDEX_TAIL.parquet'
    if not indexpath.exists():
        import daily_market_update as updater
        assert updater.bs.login().error_code=='0'
        try:idx=updater.query_history('sh.000001',str((frozen_end+pd.Timedelta(days=1)).date()),str(end.date()),'3')
        finally:updater.bs.logout()
        idx.to_parquet(indexpath,index=False)
    idx=pd.read_parquet(indexpath)
    tail=pd.Series(pd.to_numeric(idx.close).to_numpy(),index=pd.to_datetime(idx.date))
    p['index']=pd.concat([p['index'].loc[:frozen_end],tail]).sort_index();assert not p['index'].index.duplicated().any()
    assert p['index'].index.max()==end
    p['end']=end
    with (out/'INPUT_PACK.pkl').open('wb') as f:pickle.dump(p,f,pickle.HIGHEST_PROTOCOL)
    assert market_health()[0]==health
    protocol.update(baseline_signal_parity=True,raw_overlap_verified=True,raw_hashes=raw_hashes,extended_symbols=extended,input_pack_sha256=sha(out/'INPUT_PACK.pkl'),signal_counts={v:{str(y):int(s.date.dt.year.eq(y).sum()) for y in [2025,2026]} for v,s in signals.items()})
    dump(out/'PROTOCOL.json',protocol);print('PREPARED',protocol['signal_counts'],flush=True)


def apply_actions(p,out):
    for path in (Path(out)/'actions').glob('*.json'):
        r=json.loads(path.read_text(encoding='utf-8'));assert r['error_code']=='0';key=r['key'];symbol,year=key.split('/')
        assert int(year) in [2025,2026]
        if key in p['known']:continue
        p['known'].add(key)
        for row in r['records']:
            if not row.get('dividOperateDate'):continue
            d=pd.Timestamp(row['dividOperateDate']);n=lambda k:float(str(row.get(k,'')).strip() or 0)
            p['actions'].setdefault((d,symbol),[]).append(dict(cash=n('dividCashPsBeforeTax'),stock=n('dividStocksPs')+n('dividReserveToStockPs'),taxable_stock=n('dividStocksPs'),pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d),source=str(path)))


def initialize(out):
    out=Path(out);p=pickle.load((out/'INPUT_PACK.pkl').open('rb'));apply_actions(p,out)
    G.update(out=out,p=p,signals={v:pd.read_parquet(out/f'SIGNALS_{v}.parquet') for v in VARIANTS},risk=load('posterior_risk',STRATEGY/'backtest/compute_risk_metrics.py'))


def run(job):
    variant,year,endpoint,tag=job;p=G['p'];end=pd.Timestamp(endpoint);core=make_engine(None)
    core.asdict=asdict;anchor='result["fixed_order_attempts"] = fixed_order_attempts';source=core.adapted_source.replace(anchor,anchor+'\n    result["terminal_positions"] = [asdict(x) for x in holdings]')
    exec(compile(source,'<posterior_terminal_diagnostics>','exec'),core.__dict__)
    last=end-pd.Timedelta(days=37);calendar=[d for d in p['calendar'] if d<=end];starts=[d for d in calendar if d.year==year and d.month<=3]
    records=[];trades=[];gapsall=set();curves=[]
    for i,start in enumerate(starts,1):
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=[year]
        curve=[];gaps=set();s=G['signals'][variant]
        r,t=core.simulate(s.loc[s.date.between(start,last)],p['bars'],calendar,'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
        c=pd.DataFrame(curve);c['start_ordinal']=i;c['start_date']=start
        a=pd.DataFrame(r['fixed_order_attempts']);filled=int(a.filled_quantity.gt(0).sum()) if len(a) else 0;zero=int(a.filled_quantity.eq(0).sum()) if len(a) else 0
        assert filled==r['filled_orders']==len(t)+r['open_positions_at_end']
        assert r['pending_orders_created']==filled+zero+r['expired_entry_orders']+r['pending_orders_at_end']
        residual=0.
        for h in r['terminal_positions']:
            value=h['frozen_value'] if h['frozen'] else h['shares']*float(p['bars'][h['symbol']].loc[:end,'close'].iloc[-1])
            residual+=value+h['dividends']-h['entry_cost']
        assert abs(c.equity.iloc[-1]-100000-t.pnl.sum()-residual)<1e-6
        m=G['risk'].recompute_metrics(c).iloc[0].to_dict();elapsed=(c.date.iloc[-1]-start).days
        bm=(p['index'].loc[c.date.iloc[-1]]/p['index'].loc[start])**(365/elapsed)-1
        m.update(start_date=str(start.date()),start_ordinal=i,benchmark_annualized=float(bm),annualized_excess=m['annualized_return']-bm,created=r['pending_orders_created'],filled=filled,failed=zero+r['expired_entry_orders'],expired=r['expired_entry_orders'],cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()) if len(a) else 0,take_count=int(t.reason.eq('take').sum()),stop_count=int(t.reason.eq('stop').sum()),expiry_count=int(t.reason.eq('expiry').sum()),terminal_positions=r['open_positions_at_end'],pending_orders=r['pending_orders_at_end'])
        records.append(m);gapsall.update(gaps);t['start_ordinal']=i;trades.append(t);curves.append(c)
    m=pd.DataFrame(records);folder=G['out']/tag/variant;folder.mkdir(parents=True,exist_ok=True)
    m.to_parquet(folder/'START_METRICS.parquet',index=False);pd.concat(trades,ignore_index=True).to_parquet(folder/'TRADES.parquet',index=False);pd.concat(curves,ignore_index=True).to_parquet(folder/'EQUITY_CURVES.parquet',index=False)
    if tag in ('2025','regression_2026_1022') and variant=='current':
        ref=pd.read_parquet(CASES/str(year)/'START_METRICS.parquet');keys=['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']
        assert list(pd.to_datetime(m.start_date))==list(pd.to_datetime(ref.start_date))
        assert (m[keys]-ref[keys]).abs().max().max()<1e-12,'baseline regression failed'
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0','created','filled','failed','expired','cash_rejected','take_count','stop_count','expiry_count','terminal_positions','pending_orders']
    return dict(variant=variant,year=year,tag=tag,starts=len(starts),end=str(end.date()),**{k:float(m[k].mean()) for k in keys},cumulative_return_median=float(m.cumulative_return.median()),annualized_return_median=float(m.annualized_return.median()),positive_fraction=float(m.cumulative_return.gt(0).mean()),beat_fraction=float(m.annualized_excess.gt(0).mean()),action_gaps=sorted(gapsall))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--resume',action='store_true');parser.add_argument('--fetch-gaps',action='store_true');args=parser.parse_args()
    out=(args.output or ROOT/'archive/reports/holdout_restricted/hushen2_leader_pool'/datetime.now().strftime('post2024_%Y%m%d_%H%M%S')).resolve();out.mkdir(parents=True,exist_ok=True);print('OUTPUT',out,flush=True)
    if not args.resume:prepare(out)
    if args.fetch_gaps:
        import daily_market_update as updater
        gaps=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))['action_gaps'];(out/'actions').mkdir(exist_ok=True)
        assert updater.bs.login().error_code=='0'
        try:
            for key in gaps:
                symbol,year=key.split('/');assert int(year) in [2025,2026]
                r=updater.bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');records=[]
                while r.error_code=='0' and r.next():records.append(dict(zip(r.fields,r.get_row_data())))
                assert r.error_code=='0';dump(out/'actions'/(key.replace('/','_')+'.json'),dict(key=key,error_code='0',records=records,fetched_at=datetime.now().isoformat()));print('ACTION',key,len(records),flush=True)
        finally:updater.bs.logout()
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'));end=protocol['end']
    jobs=[(v,y,'2025-12-31' if y==2025 else end,str(y)) for y in [2025,2026] for v in VARIANTS]+[('current',2026,'2026-10-22','regression_2026_1022')]
    rows=[]
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(str(out),)) as pool:
        for f in as_completed([pool.submit(run,j) for j in jobs]):
            r=f.result();rows.append(r);print('COMPLETE',r['tag'],r['variant'],'GAPS',len(r['action_gaps']),flush=True)
    gaps=sorted({g for r in rows for g in r['action_gaps']});assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    assert market_health()[0]==protocol['market_health']
    rows.sort(key=lambda r:(r['year'],r['tag'],VARIANTS.index(r['variant'])))
    summary=dict(status='verified' if not gaps else 'incomplete_action_coverage',end=end,rows=[r for r in rows if r['tag'] in ['2025','2026']],regression=[r for r in rows if r['tag'].startswith('regression')],action_gaps=gaps,protected_unchanged=True,retraining=False)
    dump(out/'SUMMARY.json',summary);print('STATUS',summary['status'],'GAPS',gaps,flush=True)


if __name__=='__main__':main()
