"""Frozen 3-2, independent Q1-2021 starts, common 2026-09-30 end.
No fit/selection. Real raw-share accounting with vendor corporate actions.
"""
from pathlib import Path
import ast
import base64
import hashlib
import importlib.util
import json
import time
import zlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DATA = ROOT / 'evening_accumulation/data'
OUT = HERE / 'start_dates_2021q1_to_20260930'
OUT.mkdir(exist_ok=True)
END = pd.Timestamp('2026-09-30')
CASH = 1_000_000.


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def load_platform():
    source = (HERE.parent / 'supermind_baseline_3_2_audited_daily.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    keep = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))]
    from types import SimpleNamespace
    ns = {'np': np, 'pd': pd, 'base64': base64, 'zlib': zlib, 'json': json,
          'g': SimpleNamespace()}
    exec(compile(ast.Module(body=keep, type_ignores=[]), 'platform', 'exec'), ns)
    models = []
    for name in ['_EMBEDDED_MODEL_B64', '_EMBEDDED_STOP_MODEL_B64']:
        m = json.loads(zlib.decompress(base64.b64decode(ns[name])))
        m['fast_trees'] = [tuple(np.array([n[k] for n in t], dtype=d) for k, d in
            [('f',int),('t',float),('m',bool),('l',int),('r',int),('leaf',bool),('v',float)]) for t in m['trees']]
        models.append(m)
    ns['g'].model = models[0]
    return ns, models, hashlib.sha256(source.encode()).hexdigest()


def prepare():
    ns, models, sha = load_platform()
    spec = importlib.util.spec_from_file_location('feature_source', HERE.parent/'training_source/src/model.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    meta = pd.read_csv(DATA/'metadata/universe.csv').set_index('symbol')
    cal = pd.read_csv(DATA/'metadata/trade_calendar_20261004.csv')
    dates = pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1), 'calendar_date']))
    dates = dates[(dates >= '2020-12-01') & (dates <= END)]
    panels, chunks, fingerprints, errors = {}, [], {}, []
    for j, f in enumerate(sorted((DATA/'raw').glob('688*.parquet'))):
        sym = f.stem
        raw = pd.read_parquet(f).sort_values('date').set_index('date').loc[:END]
        qfile = DATA/'qfq'/f.name
        q = pd.read_parquet(qfile).sort_values('date').set_index('date').loc[:END]
        if not raw.index.equals(q.index): raise ValueError('unaligned '+sym)
        fingerprints[sym] = [hashlib.sha256(f.read_bytes()).hexdigest(), hashlib.sha256(qfile.read_bytes()).hexdigest()]
        frame = mod._one(q.reset_index(), 20, .30)
        # Only named backward-looking features are used; label is discarded.
        age = np.arange(len(frame)) + 1
        valid = ((age >= 120) & (frame.date >= '2020-12-01') & (frame.date <= END)
                 & (frame.ret5 <= .12) & (frame.ret20 <= .20) & (frame.rise_from_low60 <= .30)
                 & (frame.volume_spike <= 5) & (frame.high != frame.low) & (frame.pctChg < 19.5)
                 & (np.expm1(frame.amount20) >= 50e6) & (frame.isST.astype(str) != '1'))
        out_date = pd.to_datetime(meta.loc[sym, 'outDate'], errors='coerce')
        if pd.notna(out_date): valid &= frame.date < out_date
        x = frame.loc[valid, ['date']+models[0]['features']].replace([np.inf,-np.inf],np.nan).dropna()
        if len(x):
            # Compare vectorized preparation with exact platform feature function.
            for ix in list(x.index[::max(1,len(x)//3)])[:3]:
                h = q.iloc[max(0,ix-120):ix+1].rename(columns={'turn':'turnover_rate','amount':'turnover','pctChg':'quote_rate','isST':'is_st'}).copy()
                h['is_st'] = h.is_st.astype(str).eq('1')
                v = ns['_last_features'](h)
                if v is None or not np.allclose(v, frame.loc[ix,models[0]['features']].to_numpy(float),rtol=1e-6,atol=1e-7):
                    errors.append([sym,str(frame.loc[ix,'date'])])
            values = x[models[0]['features']].to_numpy(float)
            x['p'] = ns['_batch_probabilities'](models[0],values)
            x['stop'] = ns['_batch_probabilities'](models[1],values)
            x = x[(x.p >= .63)&(x.stop <= .5)].copy()
            x['symbol'] = sym; x['score'] = x.p - .22*x.stop
            chunks.append(x[['date','symbol','p','stop','score']])
        raw['prev_actual'] = raw.close.shift(1)
        raw['adjust_ratio'] = raw.preclose / raw.prev_actual
        raw['age'] = age
        panels[sym] = raw
        if j % 100 == 0: print('PREPARE',j,flush=True)
    if errors: raise ValueError('Platform feature parity failures '+str(errors[:10]))
    scores = pd.concat(chunks).sort_values(['date','score','symbol'],ascending=[True,False,True])
    candidates = {d:list(g.head(models[0]['top_per_day']).symbol) for d,g in scores.groupby('date')}
    required_symbols = set(s for v in candidates.values() for s in v)
    requests = set()
    for sym in required_symbols:
        p = panels[sym]
        event = p[(abs(p.adjust_ratio-1)>1e-5) & (p.index >= '2021-01-01')]
        requests.update((sym,int(d.year)) for d in event.index)
    dump(OUT/'protocol.json', {'initial_cash':CASH,'start_range':['2021-01-01','2021-03-31'],
         'end':str(END.date()),'strategy_sha256':sha,'model_retrained':False,'evaluation':'retrospective start-date sensitivity, not independent OOS',
         'commission':.0003,'minimum_commission':5,'sell_stamp':.001,'dividend_tax_conservative':.20,
         'slippage_each_side':.002,'daily_capacity':.25,'max_market_order_shares':50000,
         'marking':'actual raw close, missing quote carried; zero residual on observed delisting',
         'feature_parity_checks':'3 samples per eligible stock, passed','symbols':len(panels),
         'candidates_symbols':len(required_symbols),'dividend_queries':len(requests)})
    dump(OUT/'input_hashes.json',fingerprints)
    scores.to_parquet(OUT/'frozen_scores.parquet',index=False)
    print('PREPARED',len(scores),'signals;',len(required_symbols),'stocks;',len(requests),'action queries',flush=True)
    return ns,models,dates,panels,candidates,meta,requests


def actions(requests):
    import baostock as bs
    path=OUT/'corporate_actions.json'
    cache=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    missing=[(s,y) for s,y in sorted(requests) if s+'/'+str(y) not in cache]
    if missing:
        if bs.login().error_code!='0': raise RuntimeError('BaoStock login')
        try:
            for i,(s,y) in enumerate(missing):
                r=bs.query_dividend_data(code='sh.'+s[:6],year=str(y),yearType='operate')
                if r.error_code!='0': raise RuntimeError(r.error_msg)
                cache[s+'/'+str(y)]=r.get_data().to_dict('records')
                if i%20==0:
                    dump(path,cache); print('ACTIONS',i,'/',len(missing),flush=True)
            dump(path,cache)
        finally: bs.logout()
    result={}
    def num(v): return float(v) if str(v).strip() else 0.
    for key,rows in cache.items():
        s=key.split('/')[0]
        for row in rows:
            if not row['dividOperateDate']: continue
            d=pd.Timestamp(row['dividOperateDate'])
            result[(s,d)]={'cash':num(row['dividCashPsBeforeTax']),
                'stock':num(row['dividStocksPs'])+num(row['dividReserveToStockPs']),
                'pay':pd.Timestamp(row['dividPayDate'] or row['dividOperateDate']),
                'stock_day':pd.Timestamp(row['dividStockMarketDate'] or row['dividOperateDate'])}
    return result


def run_starts(prep, action_map):
    ns,models,dates,panels,candidates,meta,_=prep
    # Fast immutable day dictionaries; rows use native attribute access.
    days={d:{} for d in dates}
    for s,p in panels.items():
        for row in p.loc[dates[0]:END].itertuples():
            if row.Index in days: days[row.Index][s]=row
    starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]
    all_curves,results,all_trades=[],[],[]
    reference_differences={}
    for start in starts:
        cash=CASH; holdings={}; curve=[]; trades=[]; receivables=[]; action_issues=[]; capacity_hits=0
        for di,date in enumerate(dates):
            if date<start: continue
            day=days[date]; prev=dates[di-1]; prevday=days[prev]
            # Credit cash / release bonus shares on actual vendor dates.
            still=[]
            for pay,amount in receivables:
                if pay<=date: cash+=amount
                else: still.append((pay,amount))
            receivables=still
            for s,pos in list(holdings.items()):
                row=day.get(s)
                for release,qty in list(pos['locked']):
                    if release<=date: pos['locked'].remove((release,qty))
                action=action_map.get((s,date))
                if action:
                    old=pos['qty']; amount=old*action['cash']*.8
                    if action['pay']<=date: cash+=amount
                    else: receivables.append((action['pay'],amount))
                    bonus=int(np.floor(old*action['stock']+1e-8))
                    pos['qty']+=bonus
                    if action['stock_day']>date: pos['locked'].append((action['stock_day'],bonus))
                    # Mark old close ex-action before open NAV/order sizing.
                    if row is not None: pos['last']=float(row.preclose)
                if row is not None and np.isfinite(row.adjust_ratio) and abs(row.adjust_ratio-1)>1e-5:
                    if not action: action_issues.append([s,str(date.date()),row.adjust_ratio])
                    elif abs(row.preclose-(row.prev_actual-action['cash'])/(1+action['stock'])) > max(.025,row.preclose*.0001):
                        # Differential distributions can legitimately use a virtual
                        # exchange reference distinct from actual shareholder payouts.
                        reference_differences[s+'/'+str(date.date())]={'preclose':float(row.preclose),'previous_close':float(row.prev_actual),'cash_per_share':action['cash'],'bonus_per_share':action['stock']}
                    pos['state']['entry']*=row.adjust_ratio
                out=pd.to_datetime(meta.loc[s,'outDate'],errors='coerce')
                if pd.notna(out) and date>=out:
                    trades.append({'date':date,'symbol':s,'side':'WRITE_OFF','qty':pos['qty'],'price':0,'amount':0})
                    del holdings[s]
            def equity(use_open=False):
                return cash+sum(a for _,a in receivables)+sum(p['qty']*(float(day[s].open) if use_open and s in day and day[s].open>0 else p['last']) for s,p in holdings.items())
            used={}
            def tradable(s,buy):
                r=day.get(s)
                if r is None or str(r.tradestatus)!='1' or r.volume<=0 or r.open<=0: return False
                limit=1.2 if buy else .8
                px=np.floor(r.preclose*limit*100+.5)/100
                return r.open < px-.001 if buy else r.open > px+.001
            for s in candidates.get(prev,[]):
                if len(holdings)>=models[0]['max_positions']: break
                if s in holdings or not tradable(s,True): continue
                r=day[s]; px=min(r.open*1.002,np.floor(r.preclose*1.2*100+.5)/100)
                desired=int(equity(True)*.10/px)
                cap=min(50000,max(0,int(r.volume*.25)-used.get(s,0)))
                affordable=int(max(0,cash-5)/(px*1.0003))
                qty=min(desired,cap,affordable)
                if desired>cap: capacity_hits+=1
                if qty<200: continue
                amt=qty*px; fee=max(5,amt*.0003)
                if amt+fee>cash+1e-8: continue
                cash-=amt+fee; used[s]=used.get(s,0)+qty
                holdings[s]={'qty':qty,'last':float(r.open),'locked':[],
                     'state':{'entry':px,'half':False,'entry_date':date.date()}}
                trades.append({'date':date,'symbol':s,'side':'BUY','qty':qty,'price':px,'amount':amt,'fee':fee})
            for s,pos in list(holdings.items()):
                if pos['state']['entry_date']==date.date() or s not in prevday or not tradable(s,False): continue
                r=day[s]
                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)
                dec=ns['_exit_action'](signal,pos['state'],pos['qty'],date.date(),0)
                if dec is None: continue
                sellable=pos['qty']-sum(q for _,q in pos['locked'])
                req=pos['qty']-dec[1]
                cap=min(50000,max(0,int(r.volume*.25)-used.get(s,0)))
                qty=min(req,sellable,cap)
                if req>cap: capacity_hits+=1
                if qty<=0 or (qty<200 and qty!=sellable): continue
                px=max(r.open*.998,np.floor(r.preclose*.8*100+.5)/100)
                amt=qty*px;fee=max(5,amt*.0003)+amt*.001
                cash+=amt-fee;pos['qty']-=qty;used[s]=used.get(s,0)+qty
                if dec[0]=='TPHALF':pos['state']['half']=True
                trades.append({'date':date,'symbol':s,'side':dec[0],'qty':qty,'price':px,'amount':amt,'fee':fee})
                if pos['qty']==0:del holdings[s]
            for s,p in holdings.items():
                if s in day and day[s].close>0:p['last']=float(day[s].close)
            if cash < -.01:raise AssertionError('negative cash')
            eq=equity();curve.append({'date':date,'equity':eq,'cash':cash,'positions':len(holdings),'exposure':sum(p['qty']*p['last'] for p in holdings.values())/eq})
        if action_issues:
            dump(OUT/'unresolved_actions.json',action_issues)
            raise ValueError('Unresolved held corporate actions '+str(action_issues[:5]))
        c=pd.DataFrame(curve);nav=c.equity/CASH
        ret=c.equity.pct_change();ret.iloc[0]=nav.iloc[0]-1
        years=(END-start).days/365.25
        dd=nav/np.maximum.accumulate(np.r_[1,nav.to_numpy()])[1:]-1
        result={'start':str(start.date()),'end':str(END.date()),'final_asset':float(c.equity.iloc[-1]),
                'total_return':float(nav.iloc[-1]-1),'cagr':float(nav.iloc[-1]**(1/years)-1),
                'max_drawdown':float(dd.min()),'sharpe_rf0':float(ret.mean()/ret.std()*np.sqrt(252)),
                'avg_exposure':float(c.exposure.mean()),'fills':len(trades),'capacity_capped_orders':capacity_hits}
        results.append(result);c['start']=result['start'];all_curves.append(c)
        for t in trades:t['start']=result['start']
        all_trades.extend(trades)
        print('RUN',len(results),'/',len(starts),result['start'],'CAGR',round(result['cagr'],4),flush=True)
    out=pd.DataFrame(results)
    out.to_csv(OUT/'start_date_results.csv',index=False,encoding='utf-8-sig')
    pd.concat(all_curves).to_parquet(OUT/'daily_equity.parquet',index=False)
    pd.DataFrame(all_trades).to_parquet(OUT/'trades.parquet',index=False)
    summary={'count':len(out),'metrics':out[['final_asset','total_return','cagr','max_drawdown','sharpe_rf0','avg_exposure']].describe(percentiles=[.1,.25,.5,.75,.9]).to_dict(),
             'best_cagr':out.loc[out.cagr.idxmax()].to_dict(),'worst_cagr':out.loc[out.cagr.idxmin()].to_dict(),
             'asset_max_min_ratio':out.final_asset.max()/out.final_asset.min()}
    dump(OUT/'summary.json',summary)
    dump(OUT/'reference_price_differences.json',reference_differences)
    dump(OUT/'unresolved_actions.json',[])
    plot(out)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


def plot(out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,ax=plt.subplots(2,2,figsize=(13,8),layout='constrained')
    for a,col,title,unit in [(ax[0,0],'cagr','年化收益率分布','%'),(ax[0,1],'final_asset','期末资产分布','万元'),(ax[1,0],'max_drawdown','最大回撤幅度分布','%')]:
        v=out[col]/10000 if col=='final_asset' else out[col]*(-100 if col=='max_drawdown' else 100)
        a.hist(v,bins=10,color='#287d9c',edgecolor='white')
        a.axvline(v.median(),color='#d18a2b',ls='--',label=f'中位数 {v.median():.2f}{unit}')
        a.set(title=title,xlabel=unit,ylabel='起点数量');a.legend();a.grid(axis='y',alpha=.2)
    ax[1,1].plot(pd.to_datetime(out.start),out.cagr*100,'o-',ms=3,color='#287d9c')
    ax[1,1].set(title='开始日期与年化收益率',ylabel='年化 %');ax[1,1].tick_params(axis='x',rotation=25);ax[1,1].grid(alpha=.2)
    fig.suptitle('科创3-2 · 起点敏感性\n2021年一季度逐交易日空仓投入100万元，统一至2026-09-30',fontsize=15)
    fig.text(.5,-.035,'固定旧模型历史回放，非独立样本外；本地成交与平台仍有口径差异。',ha='center',fontsize=10)
    fig.savefig(OUT/'start_date_distribution.png',dpi=170,bbox_inches='tight');plt.close(fig)


if __name__=='__main__':
    prep=prepare()
    run_starts(prep,actions(prep[-1]))
