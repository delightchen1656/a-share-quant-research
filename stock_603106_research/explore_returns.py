"""Broad, reproducible CAGR exploration; selection uses 2023-24 only."""
from pathlib import Path
from datetime import datetime
import itertools
import json
import hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
import joblib
import backtest as base
import medium_term as medium

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'return_exploration'
PLAN=dict(capital=100000,initial_training='2020-2022',selection='2023-2024',evaluation='2025 onward',
          objective='maximize validation net CAGR; no drawdown or minimum holding constraint',
          families=['logistic','hgb2','hgb3'],horizons=[5,10,21,42,63,126],
          label_thresholds=[0,.05],training_windows=[0,504],
          entry_thresholds=[.45,.55,.65,.75],exit_thresholds=[.25,.40],
          trend_gates=['none','above_ma120'],policies=['free','max21','stop12_trail25','min21'],
          technical_families=['ma','breakout','rsi','bollinger'],
          test_exposure='later prices already seen in previous studies; exploratory historical evaluation',
          leverage=1,short_selling=False,execution='next opening, T+1, actual price, lots, taxes, fees, limits',
          slippage=.001,stress_slippage=.003)

def get_features(raw,qfq):
    x,_,_=medium.make_features(raw,qfq,21)
    ret=qfq.close.diff()
    for n in [2,5,14]:
        up=ret.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
        down=(-ret.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean()
        x[f'rsi{n}']=up/(up+down).replace(0,np.nan)
    x['close_location']=(qfq.close-qfq.low)/(qfq.high-qfq.low).replace(0,np.nan)
    return x.replace([np.inf,-np.inf],np.nan).fillna({'close_location':.5})

def make_model(family):
    if family=='logistic':
        return make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=2000,random_state=42))
    depth=int(family[-1])
    return HistGradientBoostingClassifier(max_iter=100,learning_rate=.04,max_depth=depth,
        max_leaf_nodes=2**depth,min_samples_leaf=30,l2_regularization=10,early_stopping=False,random_state=42)

def predict(raw,qfq,key,start,end=None,save=False):
    family,horizon,threshold,window=key
    x=get_features(raw,qfq)
    future=qfq.open.shift(-(horizon+1))/qfq.open.shift(-1)-1
    y=(future>threshold).astype(float).where(future.notna())
    label_end=pd.Series(raw.index,index=raw.index).shift(-(horizon+1))
    p=pd.Series(np.nan,index=raw.index)
    dates=raw.loc[start:end].index
    audits=[]
    for quarter in dates.to_period('Q').unique():
        test=dates[dates.to_period('Q')==quarter]
        mask=x.notna().all(axis=1)&y.notna()&(label_end<test[0])
        train=x.index[mask]
        if window:
            train=train[-window:]
        assert len(train)>=250
        model=make_model(family)
        with threadpool_limits(limits=1):
            model.fit(x.loc[train],y.loc[train])
            p.loc[test]=model.predict_proba(x.loc[test])[:,1]
        audits.append(dict(family=family,horizon=horizon,label_threshold=threshold,window=window,
                           quarter=str(quarter),training_rows=len(train),last_label=str(label_end.loc[train].max().date()),
                           prediction_start=str(test[0].date())))
        assert label_end.loc[train].max()<test[0]
        if save:
            folder=OUT/'models'
            folder.mkdir(exist_ok=True)
            slug=f'{family}_h{horizon}_t{threshold}_w{window}_{quarter}'
            joblib.dump(model,folder/f'{slug}.joblib')
    return p,pd.DataFrame(audits)

def policy(name):
    return {'free':dict(min_days=0,max_days=0,stop=0,trail=0),
            'max21':dict(min_days=0,max_days=21,stop=0,trail=0),
            'stop12_trail25':dict(min_days=0,max_days=0,stop=.12,trail=.25),
            'min21':dict(min_days=21,max_days=0,stop=0,trail=0)}[name]

def prepare(raw,qfq,start,end=None):
    dates=raw.loc[start:end].index
    r=raw.loc[dates]
    q=qfq.loc[dates]
    actions=[]
    for action in base.events():
        if dates[0]<=action['ex']<=dates[-1]:
            assert action['bonus']==0 and action['pay']==action['ex'], 'Array engine supports same-day cash dividends only'
            actions.append(action)
    return dict(dates=dates,raw=r,qfq=q,prior_volume=raw.volume.shift(1).loc[dates].to_numpy(),actions=actions)

def simulate(data,entries,exits,specs,slippage=.001,detail=False):
    """Vectorized independent cash ledgers, one column per candidate; no return approximation."""
    n=len(specs)
    days=data['dates']
    r=data['raw']
    q=data['qfq']
    entries=np.asarray(entries,dtype=bool)
    exits=np.asarray(exits,dtype=bool)
    assert entries.shape==exits.shape==(len(days),n)
    cash=np.full(n,base.INITIAL)
    shares=np.zeros(n,dtype=np.int64)
    order=np.zeros(n,dtype=np.int8)
    entry_index=np.full(n,-1,dtype=int)
    entry_adjusted=np.zeros(n)
    peak_close=np.zeros(n)
    minimum=np.array([s.get('min_days',0) for s in specs])
    maximum=np.array([s.get('max_days',0) for s in specs])
    stop=np.array([s.get('stop',0) for s in specs])
    trail=np.array([s.get('trail',0) for s in specs])
    equities=np.empty((len(days),n))
    positions=np.empty((len(days),n),dtype=bool)
    buy_count=np.zeros(n,dtype=int)
    sell_count=np.zeros(n,dtype=int)
    fees=np.zeros(n)
    records=[]
    entitlements={a['ex']:np.zeros(n,dtype=np.int64) for a in data['actions']}
    arrays={col:r[col].to_numpy() for col in ['open','close','preclose','volume','tradestatus']}
    qopen=q.open.to_numpy()
    qclose=q.close.to_numpy()
    for i,date in enumerate(days):
        for a in data['actions']:
            if date==a['ex']:
                cash+=entitlements[a['ex']]*a['cash']*(1-base.CONFIG['dividend_tax_assumption'])
        up=base.round_cent(arrays['preclose'][i]*1.10)
        down=base.round_cent(arrays['preclose'][i]*.90)
        op=arrays['open'][i]
        volume_cap=int(data['prior_volume'][i]*.01//100)*100
        tradeable=arrays['tradestatus'][i]==1 and arrays['volume'][i]>0 and volume_cap>0
        if tradeable:
            if op<up-.005:
                buy=(order==1)&(shares==0)
                price=base.round_cent(min(up,op*(1+slippage)))
                qty=np.minimum((cash/price//100).astype(np.int64)*100,volume_cap)
                transfer=.00002 if date<pd.Timestamp('2022-04-29') else .00001
                value=qty*price
                fee=np.maximum(5.,value*.0003)+value*transfer
                while np.any(buy&(qty>0)&(value+fee>cash)):
                    qty[buy&(qty>0)&(value+fee>cash)]-=100
                    value=qty*price
                    fee=np.maximum(5.,value*.0003)+value*transfer
                buy&=qty>0
                cash[buy]-=(value+fee)[buy]
                shares[buy]+=qty[buy]
                entry_index[buy]=i
                entry_adjusted[buy]=price*qopen[i]/op
                peak_close[buy]=entry_adjusted[buy]
                fees[buy]+=fee[buy]
                buy_count[buy]+=1
                if detail:
                    for j in np.flatnonzero(buy):
                        records.append(dict(candidate=int(j),date=date,signal_date=days[i-1],side='BUY',shares=int(qty[j]),
                                            price=price,fee=float(fee[j]),cash_after=float(cash[j]),shares_after=int(shares[j]),
                                            entry_date=date,holding_sessions=0,holding_calendar_days=0))
            if op>down+.005:
                sell=(order==-1)&(shares>0)&(entry_index<i)
                price=base.round_cent(max(down,op*(1-slippage)))
                qty=np.minimum(shares,volume_cap)
                value=qty*price
                transfer=.00002 if date<pd.Timestamp('2022-04-29') else .00001
                stamp=.001 if date<pd.Timestamp('2023-08-28') else .0005
                fee=np.maximum(5.,value*.0003)+value*(transfer+stamp)
                cash[sell]+=(value-fee)[sell]
                shares[sell]-=qty[sell]
                fees[sell]+=fee[sell]
                sell_count[sell]+=1
                if detail:
                    for j in np.flatnonzero(sell):
                        records.append(dict(candidate=int(j),date=date,signal_date=days[i-1],side='SELL',shares=int(qty[j]),
                                            price=price,fee=float(fee[j]),cash_after=float(cash[j]),shares_after=int(shares[j]),
                                            entry_date=days[entry_index[j]],holding_sessions=int(i-entry_index[j]),
                                            holding_calendar_days=(date-days[entry_index[j]]).days))
        for a in data['actions']:
            if date==a['record']:
                entitlements[a['ex']]=shares.copy()
        equities[i]=cash+shares*arrays['close'][i]
        positions[i]=shares>0
        assert np.all(cash>=-1e-6) and np.all(shares>=0)
        held=shares>0
        peak_close[held]=np.maximum(peak_close[held],qclose[i])
        age=i-entry_index
        loss=np.divide(qclose[i],entry_adjusted,out=np.ones(n),where=entry_adjusted>0)-1
        draw=np.divide(qclose[i],peak_close,out=np.ones(n),where=peak_close>0)-1
        should_exit=exits[i]|((maximum>0)&(age>=maximum-1))|((stop>0)&(loss<=-stop))|((trail>0)&(draw<=-trail))
        # Entry/exit decisions use this close, execute next session; minimum counts execution sessions.
        order=np.zeros(n,dtype=np.int8)
        order[(~held)&entries[i]]=1
        order[held&should_exit&(age>=minimum-1)]=-1
    years=(days[-1]-days[0]).days/365.25
    peaks=np.maximum.accumulate(np.maximum(equities,base.INITIAL),axis=0)
    summary=pd.DataFrame(dict(total_return=equities[-1]/base.INITIAL-1,
        cagr=(equities[-1]/base.INITIAL)**(1/years)-1,
        max_drawdown=np.min(equities/peaks-1,axis=0),final_equity=equities[-1],
        buy_count=buy_count,sell_count=sell_count,total_fees=fees,invested_day_fraction=positions.mean(axis=0)))
    return summary,equities,positions,pd.DataFrame(records)

def ml_conditions(p,qfq,entry,exit_,gate):
    above=qfq.close>qfq.close.rolling(120).mean()
    en=p>=entry
    ex=p<=exit_
    if gate:
        en &= above
        ex |= ~above
    return en,ex

def technical_conditions(qfq,spec):
    close=qfq.close
    kind=spec['family']
    if kind=='ma':
        condition=close.rolling(spec['fast']).mean()>close.rolling(spec['slow']).mean()
        return condition,~condition
    if kind=='breakout':
        return close>qfq.high.rolling(spec['lookback']).max().shift(1),close<qfq.low.rolling(spec['exit_days']).min().shift(1)
    if kind=='rsi':
        delta=close.diff()
        up=delta.clip(lower=0).ewm(alpha=1/spec['length'],adjust=False,min_periods=spec['length']).mean()
        down=(-delta.clip(upper=0)).ewm(alpha=1/spec['length'],adjust=False,min_periods=spec['length']).mean()
        rsi=100*up/(up+down)
        en=rsi<spec['buy_rsi']
        ex=rsi>spec['sell_rsi']
    else:
        avg=close.rolling(spec['length']).mean()
        sd=close.rolling(spec['length']).std()
        en=close<avg-spec['band']*sd
        ex=close>avg+spec['exit_band']*sd
    if spec.get('gate',False):
        above=close>close.rolling(120).mean()
        en &= above
        ex |= ~above
    return en,ex

def technical_specs():
    items=[]
    for fast,slow in itertools.product([3,5,10,20,40],[20,40,60,120,200]):
        if fast<slow:
            items.append(dict(family='ma',fast=fast,slow=slow))
    for look,exit_ in itertools.product([10,20,40,60,120],[5,10,20,40]):
        if exit_<=look:
            items.append(dict(family='breakout',lookback=look,exit_days=exit_))
    for n,buy,sell,gate in itertools.product([2,5,14],[10,20,30,40],[50,65,80],[False,True]):
        items.append(dict(family='rsi',length=n,buy_rsi=buy,sell_rsi=sell,gate=gate))
    for n,band,exit_,gate in itertools.product([10,20,40,60],[1,1.5,2],[0,.5,1],[False,True]):
        items.append(dict(family='bollinger',length=n,band=band,exit_band=exit_,gate=gate))
    return [dict(s,policy=name,**policy(name)) for s in items for name in PLAN['policies']]

def conditions_for(raw,qfq,spec,p_cache,start,end=None,save=False):
    if 'horizon' in spec:
        key=(spec['family'],spec['horizon'],spec['label_threshold'],spec['window'])
        if key not in p_cache:
            p_cache[key],audit=predict(raw,qfq,key,start,end,save)
            audit.to_csv(OUT/f'audit_{spec["id"]}_{start}.csv',index=False)
        return ml_conditions(p_cache[key],qfq,spec['entry'],spec['exit'],spec['gate'])
    return technical_conditions(qfq,spec)

def save_result(name,spec,data,entries,exits,slippage=.001):
    stats,equity,positions,trades=simulate(data,entries[:,None],exits[:,None],[spec],slippage,detail=True)
    curve=pd.DataFrame(dict(equity=equity[:,0],position=positions[:,0]),index=data['dates'])
    curve.index.name='date'
    curve.to_csv(OUT/f'{name}_equity.csv')
    trades.to_csv(OUT/f'{name}_trades.csv',index=False)
    result=stats.iloc[0].to_dict()
    sells=trades[trades.side.eq('SELL')] if len(trades) else trades
    result.update(min_holding_days=int(sells.holding_calendar_days.min()) if len(sells) else None,
                  median_holding_days=float(sells.holding_calendar_days.median()) if len(sells) else None,
                  max_holding_days=int(sells.holding_calendar_days.max()) if len(sells) else None)
    return result,curve,trades

def main():
    OUT.mkdir(exist_ok=True)
    (OUT/'plan.json').write_text(json.dumps(PLAN,ensure_ascii=False,indent=2),encoding='utf-8')
    raw,qfq,manifest=base.load_data()
    dev_raw,dev_qfq=raw.loc[:'2024-12-31'],qfq.loc[:'2024-12-31']
    data=prepare(dev_raw,dev_qfq,'2023-01-01','2024-12-31')
    specs,entries,exits,audits=[],[],[],[]
    keys=list(itertools.product(PLAN['families'],PLAN['horizons'],PLAN['label_thresholds'],PLAN['training_windows']))
    for i,key in enumerate(keys):
        p,a=predict(dev_raw,dev_qfq,key,'2023-01-01','2024-12-31')
        audits.append(a)
        for entry,exit_,gate,name in itertools.product(PLAN['entry_thresholds'],PLAN['exit_thresholds'],[False,True],PLAN['policies']):
            en,ex=ml_conditions(p,dev_qfq,entry,exit_,gate)
            specs.append(dict(family=key[0],horizon=key[1],label_threshold=key[2],window=key[3],
                              entry=entry,exit=exit_,gate=gate,policy=name,**policy(name)))
            entries.append(en.loc[data['dates']].to_numpy())
            exits.append(ex.loc[data['dates']].to_numpy())
        if (i+1)%6==0:
            print(f'Trained validation prediction streams {i+1}/{len(keys)}; strategy candidates {len(specs)}',flush=True)
    for spec in technical_specs():
        en,ex=technical_conditions(dev_qfq,spec)
        specs.append(spec)
        entries.append(en.loc[data['dates']].to_numpy())
        exits.append(ex.loc[data['dates']].to_numpy())
    for i,spec in enumerate(specs):
        spec['id']=i
    pd.concat(audits,ignore_index=True).to_csv(OUT/'validation_training_audit.csv',index=False)
    entries=np.array(entries).T
    exits=np.array(exits).T
    stats,equities,positions,_=simulate(data,entries,exits,specs)
    table=pd.concat([pd.DataFrame(specs),stats],axis=1)
    year23=np.flatnonzero(data['dates'].year==2023)[-1]
    table['return_2023']=equities[year23]/base.INITIAL-1
    table['return_2024']=equities[-1]/equities[year23]-1
    table['worst_validation_year']=table[['return_2023','return_2024']].min(axis=1)
    ranked=table.sort_values(['cagr','max_drawdown'],ascending=False)
    ranked.to_csv(OUT/'all_validation_candidates.csv',index=False)
    champion=int(ranked.iloc[0]['id'])
    balanced=int(table.sort_values(['worst_validation_year','cagr'],ascending=False).iloc[0]['id'])
    topids=ranked['id'].head(10).astype(int).tolist()
    frozen=dict(timestamp=datetime.now().isoformat(),champion=specs[champion],balanced=specs[balanced],top10=topids,
                candidates=len(specs),selection_last_date='2024-12-31',
                code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                manifest_sha256=hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest())
    (OUT/'selection_frozen.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Frozen selection:',frozen['champion'],'validation CAGR',float(table.loc[champion,'cagr']),flush=True)
    # Only preselected candidates reach later data. No later-data reranking.
    final_data=prepare(raw,qfq,'2025-01-01')
    p_cache={}
    selected_ids=list(dict.fromkeys([champion,balanced]+topids))
    selected_specs=[specs[i] for i in selected_ids]
    final_entry,final_exit=[],[]
    for sid in selected_ids:
        en,ex=conditions_for(raw,qfq,specs[sid],p_cache,'2025-01-01',save=True)
        final_entry.append(en.loc[final_data['dates']].to_numpy())
        final_exit.append(ex.loc[final_data['dates']].to_numpy())
    final_entry=np.array(final_entry).T
    final_exit=np.array(final_exit).T
    _,_,member_positions,_=simulate(final_data,final_entry,final_exit,selected_specs)
    results,curves={},{}
    for name,sid in [('cagr_champion',champion),('balanced_years',balanced)]:
        j=selected_ids.index(sid)
        results[name],curves[name],_=save_result(name,specs[sid],final_data,final_entry[:,j],final_exit[:,j])
        results[name+'_validation'],_,_=save_result(name+'_validation',specs[sid],data,entries[:,sid],exits[:,sid])
    j=selected_ids.index(champion)
    results['champion_stress'],_,_=save_result('champion_stress',specs[champion],final_data,final_entry[:,j],final_exit[:,j],slippage=.003)
    votes=member_positions[:,[selected_ids.index(sid) for sid in topids]].mean(axis=1)>=.5
    results['top10_vote'],curves['top10_vote'],_=save_result('top10_vote',policy('free'),final_data,votes,~votes)
    # Buy/hold signal was already known at the previous close; seed an initial order with one warm-up day.
    bh_target=pd.Series(1,index=raw.index)
    bh_curve,bh_trades,_,_=base.simulate(raw,bh_target,'buy_hold',start='2025-01-01')
    results['buy_hold']=base.metrics(bh_curve,bh_trades)
    curves['buy_hold']=bh_curve
    bh_curve.to_csv(OUT/'buy_hold_equity.csv')
    bh_trades.to_csv(OUT/'buy_hold_trades.csv',index=False)
    previous=json.loads((ROOT/'medium_term/summary.json').read_text(encoding='utf-8'))
    results['previous_monthly']=previous['final']
    curves['previous_monthly']=pd.read_csv(ROOT/'medium_term/selected_final_equity.csv',index_col=0,parse_dates=True)
    # Verify vector engine against original cash ledger for unrestricted rule signals.
    probe=next(i for i,s in enumerate(specs) if s['family']=='ma' and s['policy']=='free')
    en,ex=technical_conditions(dev_qfq,specs[probe])
    en.loc[en.index<'2023-01-01']=False
    bc,bt,_,_=base.simulate(dev_raw,en.astype(int),'probe',start='2023-01-01',end='2024-12-31')
    np.testing.assert_allclose(bc.equity,equities[:,probe],atol=1e-6,rtol=0)
    # Future truncation for ML winner, where applicable.
    if 'horizon' in specs[champion]:
        c=specs[champion]
        key=(c['family'],c['horizon'],c['label_threshold'],c['window'])
        cut='2025-09-30'
        prefix,_=predict(raw.loc[:cut],qfq.loc[:cut],key,'2025-01-01')
        np.testing.assert_allclose(prefix,p_cache[key].loc[:cut],atol=1e-12,equal_nan=True)
    years=[]
    for name,curve in curves.items():
        previous_value=base.INITIAL
        for year,values in curve.equity.groupby(curve.index.year):
            years.append(dict(strategy=name,year=int(year),return_=float(values.iloc[-1]/previous_value-1)))
            previous_value=values.iloc[-1]
    pd.DataFrame(years).to_csv(OUT/'yearly_returns.csv',index=False)
    summary=dict(data_last=str(raw.index[-1].date()),candidate_count=len(specs),selected=frozen,
                 results=results,yearly=years,checks=dict(vector_ledger_matches_reference=True,training_labels_purged=True,
                 selection_excludes_later_period=True,prefix_invariance=True))
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    plot(curves)
    report(summary,table)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

def plot(curves):
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(13,9),constrained_layout=True)
    labels=dict(cagr_champion='验证期年化最高方案',balanced_years='验证期跨年均衡方案',top10_vote='验证期前十投票',
                buy_hold='买入持有',previous_monthly='上一轮满月持仓模型')
    for name,curve in curves.items():
        axes[0].plot(curve.index,curve.equity/10000,label=labels[name])
        axes[1].plot(curve.index,(curve.equity/curve.equity.cummax().clip(lower=base.INITIAL)-1)*100,label=labels[name])
    axes[0].set_title('603106：取消持仓限制后的探索 | 2025年至今历史评估')
    axes[0].set_ylabel('账户资产（万元）')
    axes[1].set_ylabel('回撤（%）')
    for ax in axes:
        ax.grid(alpha=.2)
        ax.legend()
    fig.savefig(OUT/'research.png',dpi=160)
    plt.close(fig)

def report(s,table):
    c=s['selected']['champion']
    results=s['results']
    lines=['# 恒银科技：取消持仓限制、探索最大化年化收益','',
           f"重新下载的2020年以来数据，截至{s['data_last']}。初始资金统一10万元。探索{s['candidate_count']:,}组方案，选参目标为2023—2024年扣费后年化收益最大。",'',
           '## 研究边界','',
           '取消用户指定的最低一个月持仓，也取消上一轮45%验证回撤上限。搜索可自行选择短线、长线、固定最长持仓、止损、移动止盈及均线过滤。',
           '不融资、不做空，最大名义仓位100%。本金只决定资金和整数手规模，不通过加杠杆机械放大收益；T+1、涨跌停与费用是市场执行约束。',
           '2020—2022年初始训练，2023—2024年大范围选参，2025年以后仅评估预先选中的方案。每季度滚动扩展或使用最近504个可用训练样本，标签必须在当时完整实现。',
           '后期数据在之前实验中已被看过，本次不属于完全独立测试；上千次筛选显著增加过拟合风险，验证期最高收益不能视作未来收益。',
           '### 收益优先方案的参数','', '```json',json.dumps(c,ensure_ascii=False,indent=2),'```','',
           '## 结果','',
           '|阶段/策略|累计收益|年化收益|最大回撤|期末资金|买入/卖出|',
           '|---|---:|---:|---:|---:|---:|']
    labels=[('cagr_champion_validation','2023—2024：年化冠军（择优偏差）'),('balanced_years_validation','2023—2024：跨年均衡（择优偏差）'),
            ('cagr_champion','2025年至今：年化冠军'),('champion_stress','2025年至今：冠军滑点0.3%'),
            ('balanced_years','2025年至今：跨年均衡'),('top10_vote','2025年至今：前十投票'),
            ('previous_monthly','2025年至今：上一轮满月模型'),('buy_hold','2025年至今：买入持有')]
    for key,label in labels:
        m=results[key]
        lines.append(f"|{label}|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_drawdown']:.2%}|{m['final_equity']:,.2f}|{int(m['buy_count'])}/{int(m['sell_count'])}|")
    winner=results['cagr_champion']
    old=results['previous_monthly']
    lines+=['','## 如何解读','',
            f"验证期选出的年化最高方案在后期的年化为{winner['cagr']:.2%}，上一轮方案为{old['cagr']:.2%}，差值{winner['cagr']-old['cagr']:+.2%}（百分点）。最大回撤为{winner['max_drawdown']:.2%}。",
            '这里没有再根据后期表现重新命名冠军或修改参数。跨年均衡方案事先按验证期两个年度中较差一年的收益最高选取；前十投票按验证期前十方案当日已知持仓多数票，次日执行。它们是预设对照，而非后期择优结论。',
            f"冠军在后期已卖出记录的自然日持有期：最短{winner['min_holding_days']}、中位{winner['median_holding_days']}、最长{winner['max_holding_days']}。未卖出持仓不包含在这些统计中。",'',
            '## 交易和风控口径','',
            '收盘后计算信号，下一交易日开盘成交。止损和移动止盈也只在收盘检查、次日执行，不假定盘中精准成交；跳空和涨跌停可能使损失超过阈值。',
            '原始价模拟成交与账户，前复权价只用于特征和风险阈值。按100股整数手买入，佣金万三且每笔最低5元，印花税和过户费按历史日期切换，默认单边0.1%不利滑点。',
            '停牌不交易，开盘涨停不买、跌停不卖，每笔不超过前一日成交量1%。日线不能证明实际开盘容量或排队可成交。分红按登记日持仓、派息日入账，统一预扣20%股息税作为保守近似。',
            '本次模拟从2023年起，无送转事件；数组引擎遇到送转或非除息日支付分红将拒绝运行，避免静默近似。期末持仓按收盘估值，不扣未来清仓费用。',
            'min21表示自实际成交起至少21个交易日；max21表示收盘触发、最早于第21个交易日后的开盘退出；free表示无主动持仓期限限制，仍遵守T+1。',
            '', '## 复现与核对','',
            '运行 `..\\quant_env\\Scripts\\python.exe explore_returns.py`（当前目录为本研究文件夹）。',
            'plan.json 是搜索范围；all_validation_candidates.csv 是全部验证结果；selection_frozen.json 保存评估后期之前确定的方案；summary.json 保存统计；各策略 trades/equity 文件保存成交和账户。',
            '校验项目：源数据SHA256、标签完成日期、未来数据截断不改变早期预测、数组引擎与原现金账户逐日净值一致；另有执行边界测试。',
            '', '![净值及回撤](research.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':
    main()
