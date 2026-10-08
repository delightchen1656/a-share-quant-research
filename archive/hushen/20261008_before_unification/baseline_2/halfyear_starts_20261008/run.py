from pathlib import Path
import importlib.util,json,hashlib
import pandas as pd
import numpy as np
import ledger
HERE=Path(__file__).resolve().parent;BASE=HERE.parents[1]
ENTRY=BASE/'supermind_mainboard_baseline_2.py'
def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def dump(n,x):(HERE/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    reference=BASE/'test2_weekly/original_202001'
    assert sha(ENTRY)==json.loads((reference/'protocol.json').read_text(encoding='utf-8'))['strategy_sha256']
    p=mod(BASE/'test2_retrain_2022/pipeline.py','feature_utils');p.dump=dump
    ranks,eligible,prices,dates=p.features('evaluation')
    score=p.smooth(ranks,eligible,[.35,.20,.25,.20])
    requests=[pd.Timestamp(year=y,month=m,day=1) for y in range(2020,2027) for m in [1,7]]
    starts=[dates[dates>=d][0] for d in requests]
    wanted=set(starts)|set(d for i,d in enumerate(dates) if d>=starts[0] and (i-1)%20==0)
    signals=sorted(dates[dates.get_loc(d)-1] for d in wanted)
    rankings={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist() for d in signals}
    dump('rankings.json',rankings)
    del ranks,eligible,prices,score
    import gc;gc.collect()
    p.HERE=HERE
    engine=mod(reference/'weekly_engine.py','execution');engine.load_model=lambda k:engine.module(ENTRY,'formal_baseline2')
    days,actions,outs=ledger.load(p,engine,rankings,dates,BASE/'start_date_study')
    results=[];curves=[];fills=[];checks={};issues={};differences={}
    for requested,start in zip(requests,starts):
        a=engine.Account('D11',start,actions,days,outs)
        for i in range(dates.get_loc(start),len(dates)):
            previous=a.m.g.alpha_targets;a.step(dates[i],i,dates[i-1],rankings)
            assert (a.m.g.alpha_targets is not previous)==(dates[i]==start or (i-1)%20==0)
        q=pd.DataFrame(a.curve);t=pd.DataFrame(a.trades);nav=q.equity.to_numpy();ret=nav/np.r_[100000.,nav[:-1]]-1
        row=dict(requested_start=str(requested.date()),actual_start=str(start.date()),end=str(dates[-1].date()),initial_cash=100000,
            final_equity=float(nav[-1]),total_return=float(nav[-1]/100000-1),cagr=float((nav[-1]/100000)**(365.25/((dates[-1]-start).days+1))-1),
            max_drawdown=float((1-nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]).max()),sharpe=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)),
            trades=len(t),commission=float(t.commission.sum()),transfer=float(t.transfer.sum()),stamp=float(t.stamp.sum()),transaction_fees=a.fees,
            dividend_tax=a.tax,total_cost=a.fees+a.tax,final_cash=a.cash,final_market_value=float(q.market_value.iloc[-1]),
            unresolved_actions=len(a.issues),reference_differences=len(a.reference_diffs))
        assert q.cash.ge(-.01).all() and (t.loc[t.qty>0,'qty']%100).eq(0).all()
        assert np.isclose(row['commission']+row['transfer']+row['stamp'],a.fees)
        checks[str(requested.date())]=not a.issues and not a.reference_diffs
        if requested==requests[0]:
            old=pd.read_parquet(reference/'daily_equity.parquet')
            checks['original_daily_equity_reproduced']=bool(np.array_equal(q.equity.to_numpy(),old.equity.to_numpy()))
        results.append(row);curves.extend(a.curve);fills.extend(a.trades)
        issues[str(requested.date())]=a.issues;differences[str(requested.date())]=a.reference_diffs
        print('DONE',row,flush=True)
    dump('results.json',results);dump('validation.json',checks);dump('unresolved_actions.json',issues);dump('reference_differences.json',differences)
    dump('protocol.json',dict(entry=str(ENTRY),sha256=sha(ENTRY),requests=[str(d.date()) for d in requests],end=str(dates[-1].date()),initial_cash=100000,
        note='Independent empty starts; next available session on holidays. Original global 20-session phase retained, not reset per start. No tuning. Sharpe daily simple returns including day one, ddof1, rf0, annual252.'))
    pd.DataFrame(curves).to_parquet(HERE/'daily_equity.parquet',index=False);pd.DataFrame(fills).to_parquet(HERE/'trades.parquet',index=False)
    assert len(results)==14 and all(checks.values()),checks
    rows=[]
    for r in results:
        values=[r['requested_start'],r['actual_start'],f"{r['final_equity']:,.2f}",f"{r['total_return']:.2%}",f"{r['cagr']:.2%}",f"{r['max_drawdown']:.2%}",f"{r['sharpe']:.3f}",str(r['trades']),f"{r['commission']:,.2f}",f"{r['transaction_fees']:,.2f}",f"{r['dividend_tax']:,.2f}",f"{r['total_cost']:,.2f}"]
        rows.append('<tr>'+''.join('<td>'+v+'</td>' for v in values)+'</tr>')
    html='''<!doctype html><meta charset="utf-8"><title>沪深基准2半年度起点对照</title><style>body{font:15px Microsoft YaHei;line-height:1.8;margin:30px;color:#20344a}table{border-collapse:collapse}th,td{padding:9px;border:1px solid #ddd;text-align:right;white-space:nowrap}th{background:#edf3f8}</style><h1>沪深基准2：2020—2026年半年度起点</h1><p>各账户独立空仓10万元，统一到2026-09-30；节假日顺延到首个交易日。原版固定5只、98%目标仓位、原20交易日日历相位不变；首次入场额外触发，并非每个起点重新计满20日。资金列单位元，净值已扣列示费用，不应再次扣减。</p><table><tr><th>指定起点</th><th>实际起点</th><th>最终资产</th><th>累计收益</th><th>年化收益</th><th>最大回撤</th><th>Sharpe</th><th>成交笔数</th><th>佣金</th><th>交易费用含税</th><th>分红税</th><th>费用总计</th></tr>'''+''.join(rows)+'''</table><p>交易费用＝佣金＋过户费＋卖出印花税，费用总计另加已实现分红税。期末未强制平仓，未扣未来平仓费用及未实现分红税。成交笔数为本地成交记录数，不是完整买卖往返次数。Sharpe：每日简单收益均值/样本标准差×√252，无风险利率0%。年化按实际日历天数，尤其2026年7月开始的短区间不能当作稳定年度预期。</p><p>全部为本地日线撮合近似，非平台或实盘结果；区间互相重叠且长短不同，不能仅凭年化差异归因于入场时机，也不是独立样本。价格源、历史股票池及公司行动处理的已知局限仍适用。本次没有调参或隔夜手操规则。</p>'''
    (HERE/'report.html').write_text(html,encoding='utf-8');print('PASS',len(checks),flush=True)
if __name__=='__main__':main()
