"""Frozen, development-only selection of restricted stock-pool strategies."""
from pathlib import Path
import sys, json, hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'mainboard_baseline_1'/'local_backtest'))
import supermind_aligned_backtest as bt
OUT=HERE/'outputs'

def measure(c,start,end):
    z=c[c.date.between(start,end)].copy()
    previous=c[c.date<pd.Timestamp(start)]
    initial=float(previous.equity.iloc[-1]) if len(previous) else bt.INITIAL_CASH
    return bt.metrics(z,initial)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    f=bt.build_factor_cache()
    base=bt.ranked_months(f,(.25,.20,.55),(.50,.25,.25),120)
    names=['reference','lowrisk_half','liquid_half','dividend_half','trend_half',
           'quality_lowrisk','quality_trend','reversal_lowrisk','liquid_quality',
           'dividend_only','lowrisk_only','trend_only','fixed_quality_pool']
    # The fixed universe uses only 2020-2022 snapshots and is eligible from 2023.
    hist=f[f.signal_date<pd.Timestamp('2023-01-01')]
    fixed=hist.groupby('symbol').agg(quality=('dividend','mean'),risk=('downside','mean'),n=('signal_date','size'))
    fixed=fixed[fixed.n>=24]
    fixed['score']=fixed.quality.rank(pct=True)-.5*fixed.risk.rank(pct=True)
    fixed_names=set(fixed.nlargest(150,'score').index)
    ranks={n:{} for n in names}
    for date, frame in base.items():
        x=frame.copy()
        risk=x.downside.rank(pct=True); liquid=x.amount20.rank(pct=True)
        qual=x.dividend.rank(pct=True); trend=x.near_high.rank(pct=True)
        masks={'reference':pd.Series(True,index=x.index),'lowrisk_half':risk<=.5,
          'liquid_half':liquid>=.5,'dividend_half':qual>=.5,'trend_half':trend>=.5,
          'quality_lowrisk':(qual>=.5)&(risk<=.5),'quality_trend':(qual>=.5)&(trend>=.5),
          'reversal_lowrisk':(trend<=.5)&(risk<=.5),'liquid_quality':(liquid>=.5)&(qual>=.5),
          'dividend_only':qual>=.7,'lowrisk_only':risk<=.3,'trend_only':trend>=.7,
          'fixed_quality_pool':x.symbol.isin(fixed_names) if date>=pd.Timestamp('2023-01-01') else pd.Series(False,index=x.index)}
        for n,mask in masks.items():
            q=x[mask].copy()
            if n=='dividend_only':q['score']=qual[mask]
            if n=='lowrisk_only':q['score']=1-risk[mask]
            if n=='trend_only':q['score']=trend[mask]
            if len(q)>=20:ranks[n][date]=q.sort_values('score',ascending=False,kind='mergesort')
    universe=set()
    for rank in ranks.values():
        for q in rank.values():universe.update(q.head(40).symbol)
    panel=bt.load_daily_panel(universe)
    rows=[]; curves={}; transactions={}
    for n in names:
        print('RUN',n,flush=True)
        c,t=bt.simulate(ranks[n],.05,20,40,1.,1.5,panel)
        curves[n]=c;transactions[n]=t
        row={'name':n}
        for label,start,end in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
            m=measure(c,start,end)
            for key in ['annualized_return','max_drawdown','sharpe','final_equity']:row[label+'_'+key]=m[key]
        # Fixed stock selection cannot be judged over its own construction period.
        row['eligible']=n not in ['reference','fixed_quality_pool'] and row['dev_max_drawdown']>=-.35
        row['selection_score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
    results=pd.DataFrame(rows)
    eligible=results[results.eligible].sort_values('selection_score',ascending=False)
    if eligible.empty:raise RuntimeError('No candidate meets development drawdown limit')
    winner=eligible.iloc[0]['name']
    curves[winner].to_csv(OUT/'baseline2_daily_equity.csv',index=False,encoding='utf-8-sig')
    transactions[winner].to_csv(OUT/'baseline2_trades.csv',index=False,encoding='utf-8-sig')
    curves['reference'].to_csv(OUT/'reference_daily_equity.csv',index=False,encoding='utf-8-sig')
    pd.concat([c.assign(strategy=n) for n,c in curves.items()]).to_parquet(OUT/'all_curves.parquet',index=False)
    frozen={'name':'沪深基准2','variant':winner,'selection':'2020-2023 only; development drawdown <=35%; score=CAGR+.05*Sharpe-.5*abs(MDD)',
      'capital':10000000,'count':20,'buffer':40,'exposure':1.,'volume_limit':.05,
      'engine_sha256':hashlib.sha256(Path(bt.__file__).read_bytes()).hexdigest(),
      'limitations':['2025+ previously inspected in this project; not pristine out-of-sample','Corporate actions approximated by inherited engine','Fixed starting universe may contain survivorship bias','Stamp tax fixed at 0.1% for platform comparison','Daily volume cap cannot prove opening auction capacity']}
    (HERE/'frozen.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
    labels={'lowrisk_half':'低波精选','liquid_half':'流动精选','dividend_half':'分红精选','trend_half':'趋势精选','quality_lowrisk':'质量低波','quality_trend':'质量趋势','reversal_lowrisk':'低波反转','liquid_quality':'流动质量','dividend_only':'分红排序','lowrisk_only':'低波排序','trend_only':'趋势排序'}
    lines=['# 沪深基准2：'+labels.get(winner,winner),'','冻结方向：'+winner+'。以开发期评分选定，后续区间仅报告。固定股票池由2020—2022构造，其全期表现包含建池期空仓，不参加冠军选择。','',
      '|方向|开发年化|2024年化|2025后年化|全期年化|全期回撤|Sharpe|期末万元|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in results.to_dict('records'):
        lines.append('|'+r['name']+'|'+ '|'.join([f"{r[k]:.2%}" for k in ['dev_annualized_return','validation_annualized_return','observed_annualized_return','full_annualized_return','full_max_drawdown']])+f"|{r['full_sharpe']:.3f}|{r['full_final_equity']/10000:.2f}|")
    lines+=['','## 适用边界','',*['- '+s for s in frozen['limitations']], '', '执行继承基准1：月末信号、下一交易日原始开盘撮合、100股、佣金万三最低5元、双边0.2%滑点、卖出税0.1%、5%日量上限。只买沪深普通主板；平台验证尚未完成。', '', '运行：quant_env/Scripts/python.exe sh_sz_market_research/baselines/mainboard_baseline_2/research.py']
    (HERE/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    print('WINNER',winner,flush=True);print(results.to_string(index=False),flush=True)

if __name__=='__main__':main()
