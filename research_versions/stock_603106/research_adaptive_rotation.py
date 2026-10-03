"""Causal strategy rotation: compare meta-rules on 2024, evaluate frozen rule on 2025+."""
from pathlib import Path
from datetime import datetime
import itertools
import json
import hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import backtest as base
import explore_returns as ex

OUT=ex.OUT/'adaptive'
PLAN=dict(underlying_candidates=5340,underlying_prediction_start='2023-01-01',
          initial_scoring_history='2023',meta_validation='2024',final_evaluation='2025 onward',
          lookbacks=[21,63,126,252],reselection=['M','Q'],top_n=[1,3,10],scores=['return','calmar'],
          meta_objective='maximum 2024 net CAGR, no risk cap',
          market_timing='select using prior session and earlier performance; vote using today close; trade next open',
          contamination='adaptive family added after inspecting failed static out-of-period results; exploratory only')

def source_universe(raw,qfq):
    folder=OUT/'prediction_cache'
    folder.mkdir(exist_ok=True)
    input_hash=hashlib.sha256((base.ROOT/'data/manifest.json').read_bytes()).hexdigest()
    code_hash=hashlib.sha256(Path(ex.__file__).read_bytes()).hexdigest()
    context_hash=hashlib.sha256((input_hash+code_hash).encode()).hexdigest()
    data=ex.prepare(raw,qfq,'2023-01-01')
    specs,entries,exits=[],[],[]
    keys=list(itertools.product(ex.PLAN['families'],ex.PLAN['horizons'],ex.PLAN['label_thresholds'],ex.PLAN['training_windows']))
    for i,key in enumerate(keys):
        name=f'{key[0]}_h{key[1]}_t{key[2]}_w{key[3]}'
        path=folder/f'{name}.parquet'
        stamp=folder/f'{name}.sha256'
        if path.exists() and stamp.exists() and stamp.read_text()==context_hash:
            p=pd.read_parquet(path)['probability']
        else:
            p,a=ex.predict(raw,qfq,key,'2023-01-01')
            p.rename('probability').to_frame().to_parquet(path)
            a.to_csv(folder/f'{name}_audit.csv',index=False)
            stamp.write_text(context_hash)
        for entry,exit_,gate,name in itertools.product(ex.PLAN['entry_thresholds'],ex.PLAN['exit_thresholds'],[False,True],ex.PLAN['policies']):
            en,exit_signal=ex.ml_conditions(p,qfq,entry,exit_,gate)
            specs.append(dict(family=key[0],horizon=key[1],label_threshold=key[2],window=key[3],entry=entry,exit=exit_,gate=gate,policy=name,**ex.policy(name)))
            entries.append(en.loc[data['dates']].to_numpy())
            exits.append(exit_signal.loc[data['dates']].to_numpy())
        if (i+1)%6==0:
            print(f'Causal candidate streams ready {i+1}/{len(keys)}',flush=True)
    for spec in ex.technical_specs():
        en,exit_signal=ex.technical_conditions(qfq,spec)
        specs.append(spec)
        entries.append(en.loc[data['dates']].to_numpy())
        exits.append(exit_signal.loc[data['dates']].to_numpy())
    for i,spec in enumerate(specs):
        spec['id']=i
    return data,specs,np.array(entries).T,np.array(exits).T

def rotate(dates,equities,positions,params,start='2024-01-01'):
    equity=np.column_stack([equities,np.full(len(dates),base.INITIAL)])
    position=np.column_stack([positions,np.zeros(len(dates),dtype=bool)])
    target=np.zeros(len(dates),dtype=bool)
    audits=[]
    periods=dates.to_period(params['frequency'])
    first=np.flatnonzero(dates>=pd.Timestamp(start))[0]
    selected=np.array([equities.shape[1]])
    for i in range(first,len(dates)):
        if i==first or periods[i]!=periods[i-1]:
            end=i-1
            begin=max(0,end-params['lookback'])
            performance=equity[end]/equity[begin]-1
            if params['score']=='calmar':
                sample=equity[begin:end+1]
                drawdown=-(sample/np.maximum.accumulate(sample,axis=0)-1).min(axis=0)
                performance=performance/np.maximum(drawdown,.05)
            # Cash is an explicit expert; negative-return experts are not admitted to the vote.
            candidates=np.flatnonzero(performance>0)
            selected=candidates[np.argsort(performance[candidates],kind='stable')[-params['top_n']:]] if len(candidates) else np.array([equities.shape[1]])
            audits.append(dict(selection_date=str(dates[i].date()),history_start=str(dates[begin].date()),
                               history_end=str(dates[end].date()),selected_ids=','.join(map(str,selected)),
                               selected_count=len(selected)))
        target[i]=position[i,selected].mean()>=.5
    return target,pd.DataFrame(audits)

def evaluate(name,params,data,equities,positions,start,end=None,save=False,slippage=.001):
    target,audit=rotate(data['dates'],equities,positions,params,start)
    dates=data['dates']
    mask=(dates>=pd.Timestamp(start))
    if end:
        mask&=dates<=pd.Timestamp(end)
    subset=dict(dates=dates[mask],raw=data['raw'].loc[dates[mask]],qfq=data['qfq'].loc[dates[mask]],
                prior_volume=data['prior_volume'][mask],actions=[a for a in data['actions'] if dates[mask][0]<=a['ex']<=dates[mask][-1]])
    stats,curve,hold,trades=ex.simulate(subset,target[mask,None],(~target[mask,None]),[ex.policy('free')],slippage,detail=save)
    result=stats.iloc[0].to_dict()
    if save:
        pd.DataFrame(dict(equity=curve[:,0],position=hold[:,0],target=target[mask]),index=subset['dates']).to_csv(OUT/f'{name}_equity.csv',index_label='date')
        audit.to_csv(OUT/f'{name}_selection_audit.csv',index=False)
        trades.to_csv(OUT/f'{name}_trades.csv',index=False)
        assert (pd.to_datetime(audit.history_end)<pd.to_datetime(audit.selection_date)).all()
    return result,curve[:,0],audit

def main():
    OUT.mkdir(exist_ok=True)
    (OUT/'plan.json').write_text(json.dumps(PLAN,ensure_ascii=False,indent=2),encoding='utf-8')
    raw,qfq,_=base.load_data()
    data,specs,entries,exits=source_universe(raw,qfq)
    assert len(specs)==PLAN['underlying_candidates']
    _,equities,positions,_=ex.simulate(data,entries,exits,specs)
    # Prefix replay: earlier candidate NAVs exactly match the previous validation run.
    cutoff=np.flatnonzero(data['dates']<=pd.Timestamp('2024-12-31'))[-1]
    previous=pd.read_csv(ex.OUT/'all_validation_candidates.csv').sort_values('id')
    np.testing.assert_allclose(equities[cutoff],previous.final_equity,atol=1e-6,rtol=0)
    vdata=dict(dates=data['dates'][:cutoff+1],raw=data['raw'].iloc[:cutoff+1],qfq=data['qfq'].iloc[:cutoff+1],
               prior_volume=data['prior_volume'][:cutoff+1],actions=[])
    configs=[dict(lookback=lb,frequency=freq,top_n=n,score=score) for lb,freq,n,score in itertools.product(
        PLAN['lookbacks'],PLAN['reselection'],PLAN['top_n'],PLAN['scores'])]
    results=[]
    for params in configs:
        stats,_,_=evaluate('candidate',params,vdata,equities[:cutoff+1],positions[:cutoff+1],'2024-01-01','2024-12-31')
        results.append(dict(**params,**stats))
    table=pd.DataFrame(results).sort_values(['cagr','max_drawdown'],ascending=False)
    table.to_csv(OUT/'meta_validation_candidates.csv',index=False)
    row=table.iloc[0]
    chosen=dict(lookback=int(row.lookback),frequency=str(row.frequency),top_n=int(row.top_n),score=str(row.score))
    selection=dict(chosen=chosen,selected_at=datetime.now().isoformat(),validation='2024 only',
                   validation_stats=row.to_dict(),candidate_count=len(configs),
                   code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'selection_frozen.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Adaptive parameters frozen:',chosen,flush=True)
    validation,_,_=evaluate('selected_validation',chosen,vdata,equities[:cutoff+1],positions[:cutoff+1],'2024-01-01','2024-12-31',save=True)
    final,curve,audit=evaluate('selected_final',chosen,data,equities,positions,'2025-01-01',save=True)
    stressed,_,_=evaluate('selected_stress',chosen,data,equities,positions,'2025-01-01',save=True,slippage=.003)
    # Verify the frozen selector cannot change previous decisions when future data are removed.
    cut=np.flatnonzero(data['dates']<=pd.Timestamp('2025-09-30'))[-1]
    full_signal,_=rotate(data['dates'],equities,positions,chosen,'2025-01-01')
    prefix_signal,_=rotate(data['dates'][:cut+1],equities[:cut+1],positions[:cut+1],chosen,'2025-01-01')
    np.testing.assert_array_equal(full_signal[:cut+1],prefix_signal)
    used_ids=set()
    for text in audit.selected_ids:
        used_ids.update(map(int,text.split(',')))
    used=[specs[i] for i in sorted(used_ids) if i<len(specs)]
    (OUT/'selected_experts.json').write_text(json.dumps(used,ensure_ascii=False,indent=2),encoding='utf-8')
    dates=data['dates'][data['dates']>=pd.Timestamp('2025-01-01')]
    curve=pd.Series(curve,index=dates)
    yearly={}
    value=base.INITIAL
    for year,values in curve.groupby(curve.index.year):
        yearly[str(year)]=float(values.iloc[-1]/value-1)
        value=values.iloc[-1]
    summary=dict(plan=PLAN,selection=selection,validation=validation,final=final,stress=stressed,
                 yearly=yearly,checks=dict(source_validation_nav_replay=True,selection_history_strictly_prior=True,
                 future_prefix_invariance=True),data_last=str(dates[-1].date()))
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    report(summary)
    plot()
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

def report(s):
    params=s['selection']['chosen']
    lines=['# 自适应策略轮换：收益优先探索','',
           '固定参数在后期失效后，增加这一轮探索；因此它是已知后期结果后的研究扩展，不是独立测试。',
           f"底层5,340个专家策略，2023年开始生成各自的因果预测和独立账户。比较48个轮换规则：过去21/63/126/252交易日、月度/季度换选、选前1/3/10名、累计收益或收益/回撤评分。",'',
           '2023年作为首次评分历史，2024年用于选择轮换规则；2025年至今评估冻结后的规则。每次选择仅用选择日前一个交易日及更早的专家净值，负历史收益专家不入选，无正收益专家时选现金。',
           f"所选规则：回看{params['lookback']}交易日、{'每月' if params['frequency']=='M' else '每季度'}换选、前{params['top_n']}名、{params['score']}评分。候选专家的持仓多数票在当日收盘形成账户目标，次日执行。",'',
           '|阶段|累计收益|年化收益|最大回撤|期末资产|买入/卖出|','|---|---:|---:|---:|---:|---:|']
    for key,name in [('validation','2024选参期'),('final','2025年至今历史评估'),('stress','2025年至今：滑点0.3%')]:
        m=s[key]
        lines.append(f"|{name}|{m['total_return']:.2%}|{m['cagr']:.2%}|{m['max_drawdown']:.2%}|{m['final_equity']:,.2f}|{int(m['buy_count'])}/{int(m['sell_count'])}|")
    lines+=['', '年度收益：'+ '；'.join(f'{y}：{r:.2%}' for y,r in s['yearly'].items())+'。','',
            '现金账户、费用、分红和交易限制与前一轮一致。底层专家账户连续运行，轮换账户每个评估区间独立从10万元开始；专家累计净值只用于排名，不直接计入轮换账户收益。',
            '校验：底层专家2023—2024净值逐一与前一轮结果一致；每次换选使用的数据截止日期严格早于选择日期；截断未来数据不会改变早期轮换信号。',
            '轮换规则本身也会过拟合，历史高年化不代表可实现或可持续的未来收益。',
            '', '![轮换与固定策略对照](research.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')

def plot():
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(13,9),constrained_layout=True)
    sources=[('自适应轮换',OUT/'selected_final_equity.csv'),('固定年化冠军',ex.OUT/'cagr_champion_equity.csv'),
             ('上一轮满月模型',base.ROOT/'medium_term/selected_final_equity.csv'),('买入持有',ex.OUT/'buy_hold_equity.csv')]
    for label,path in sources:
        curve=pd.read_csv(path,index_col=0,parse_dates=True).equity
        axes[0].plot(curve.index,curve/10000,label=label)
        axes[1].plot(curve.index,(curve/curve.cummax().clip(lower=base.INITIAL)-1)*100,label=label)
    axes[0].set_title('恒银科技：自适应探索与此前策略（2025年至今）')
    axes[0].set_ylabel('账户资产（万元）')
    axes[1].set_ylabel('回撤（%）')
    for ax in axes:
        ax.legend()
        ax.grid(alpha=.2)
    fig.savefig(OUT/'research.png',dpi=160)
    plt.close(fig)

if __name__=='__main__':
    main()
