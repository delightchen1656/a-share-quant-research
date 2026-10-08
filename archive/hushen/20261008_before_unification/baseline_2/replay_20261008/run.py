"""Fresh ledger replay of the formal baseline 2; no tuning or overnight orders."""
from pathlib import Path
import importlib.util,json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
OLD=BASE/'test2_weekly/original_202001'
ENTRY=BASE/'supermind_mainboard_baseline_2.py'
def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(name,data):(HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def main():
    checks={}
    checks['formal_source_matches_frozen']=sha(ENTRY)==read(OLD/'protocol.json')['strategy_sha256']
    inputs=read(OLD/'evaluation_inputs.json')
    p=mod(BASE/'test2_retrain_2022/pipeline.py','utils');p.HERE=OLD
    checks['market_input_hashes']=all(sha(p.DATA/'raw'/r['symbol'][-2:]/(r['symbol']+'.parquet'))==r['sha256'] for r in inputs['files'])
    calendar=BASE/'start_date_study/benchmark.parquet'
    checks['calendar_hash']=sha(calendar)==inputs['benchmark_sha256']
    assert all(checks.values()),checks
    ranks=read(OLD/'rankings.json')
    engine=mod(OLD/'weekly_engine.py','original_engine')
    engine.load_model=lambda k:engine.module(ENTRY,'formal_baseline2')
    ledger=mod(OLD/'ledger.py','ledger')
    dates=pd.DatetimeIndex(pd.read_parquet(calendar).date)
    assert dates.max()==pd.Timestamp('2026-09-30')
    days,actions,outs=ledger.load(p,engine,ranks,dates,calendar.parent)
    start=pd.Timestamp('2020-01-02');a=engine.Account('D11',start,actions,days,outs)
    for i in range(dates.get_loc(start),len(dates)):a.step(dates[i],i,dates[i-1],ranks)
    q=pd.DataFrame(a.curve);trades=pd.DataFrame(a.trades);nav=q.equity.to_numpy()
    ret=nav/np.r_[100000.,nav[:-1]]-1
    result=dict(start=str(start.date()),end=str(dates[-1].date()),initial_cash=100000,final_equity=float(nav[-1]),
        total_return=float(nav[-1]/100000-1),cagr=float((nav[-1]/100000)**(365.25/((dates[-1]-start).days+1))-1),
        max_drawdown=float((1-nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]).max()),
        sharpe=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)),trades=len(trades),fees=a.fees,dividend_tax=a.tax,
        final_cash=a.cash,final_market_value=float(q.market_value.iloc[-1]),avg_exposure=float(q.exposure.mean()),
        unresolved_actions=len(a.issues),reference_differences=len(a.reference_diffs))
    previous=pd.read_parquet(OLD/'daily_equity.parquet')
    checks['daily_equity_reproduced']=bool(np.array_equal(q.equity.to_numpy(),previous.equity.to_numpy()) and q.date.tolist()==previous.date.tolist())
    previous_trades=pd.read_parquet(OLD/'trades.parquet')
    checks['fills_reproduced']=trades.equals(previous_trades)
    checks['cash_and_actions']=bool(q.cash.ge(-.01).all() and not a.issues and not a.reference_diffs)
    assert all(checks.values()),checks
    q.to_parquet(HERE/'daily_equity.parquet',index=False);trades.to_parquet(HERE/'trades.parquet',index=False)
    dump('results.json',result);dump('validation.json',checks)
    dump('manifest.json',dict(strategy_sha256=sha(ENTRY),ranking_sha256=sha(OLD/'rankings.json'),input_manifest_sha256=sha(OLD/'evaluation_inputs.json'),
        note='Reuse identical frozen historical rankings after full market hash validation; fresh independent cash ledger through formal entry. No retraining or overnight execution.'))
    rows=[('本金','10万元'),('期末资产',f"{result['final_equity']:,.2f}元"),('累计收益',f"{result['total_return']:.2%}"),('年化收益',f"{result['cagr']:.2%}"),('最大回撤',f"{result['max_drawdown']:.2%}"),('Sharpe',f"{result['sharpe']:.3f}"),('成交笔数',str(result['trades'])),('期末股票市值',f"{result['final_market_value']:,.2f}元"),('期末现金',f"{result['final_cash']:,.2f}元")]
    html='''<!doctype html><meta charset="utf-8"><title>沪深基准2本地复跑</title><style>body{font:16px Microsoft YaHei;max-width:900px;margin:40px auto;line-height:1.8}td{padding:8px 24px;border-bottom:1px solid #ddd}</style><h1>沪深基准2原版：2026-10-08复跑</h1><p>区间2020-01-02至2026-09-30。每日运行、固定5只目标、98%目标仓位、20交易日调仓，原开盘执行逻辑。未使用隔夜手操、月初换仓或扩容规则。</p><table>'''+''.join('<tr><td>'+k+'</td><td>'+v+'</td></tr>' for k,v in rows)+'''</table><p>校验正式入口哈希及全部原始行情哈希后，复用冻结排名，重新从空仓10万元运行现金账本；逐日净值和逐笔成交与此前结果完全一致。夏普按日简单收益、样本标准差、252日年化、无风险利率0%，包含首日收益。</p><p>本地日线撮合近似，非SuperMind服务器或实盘成绩；包含交易费用、分红税及公司行动，期末不强制平仓，不计未来平仓费用及未实现分红税。数据截止9月30日，不代表已更新至10月8日。现有历史股票池及公司行动数据局限仍保留。</p>'''
    (HERE/'report.html').write_text(html,encoding='utf-8')
    print(json.dumps(result,indent=2));print('PASS',len(checks))
if __name__=='__main__':main()
