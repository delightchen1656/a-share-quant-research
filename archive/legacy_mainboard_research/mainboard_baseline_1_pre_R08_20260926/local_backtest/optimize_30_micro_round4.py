"""收益优化第四轮：围绕平台验证V2做30项单变量微调。"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import supermind_aligned_backtest as bt
from optimize_aligned_returns import period

OUT=Path(__file__).resolve().parent/"outputs"/"return_optimization_round_4_micro30"
BASE={"bull":(.25,.20,.55),"bear":(.50,.25,.25),"ma":120,"count":20,"buffer":40,"exposure":1.0,"cap":1.5}

def variant(name, **changes):
    x=dict(BASE); x.update(changes); x["name"]=name; return x

V=[
 variant("v2_reference"),
 variant("bear_rev_475",bear=(.475,.25,.275)),
 variant("bear_rev_525",bear=(.525,.25,.225)),
 variant("bear_rev_55",bear=(.55,.25,.20)),
 variant("bear_ma_225",bear=(.50,.225,.275)),
 variant("bear_ma_275",bear=(.50,.275,.225)),
 variant("bear_ma_30",bear=(.50,.30,.20)),
 variant("bear_div_30",bear=(.50,.20,.30)),
 variant("bear_balanced_shift",bear=(.475,.275,.25)),
 variant("bull_amount_225",bull=(.225,.20,.575)),
 variant("bull_amount_275",bull=(.275,.20,.525)),
 variant("bull_mom_175",bull=(.25,.175,.575)),
 variant("bull_mom_225",bull=(.25,.225,.525)),
 variant("bull_mom_25",bull=(.25,.25,.50)),
 variant("regime_ma100",ma=100),
 variant("regime_ma110",ma=110),
 variant("regime_ma130",ma=130),
 variant("regime_ma140",ma=140),
 variant("buffer45",buffer=45),
 variant("buffer50",buffer=50),
 variant("buffer55",buffer=55),
 variant("buffer60",buffer=60),
 variant("count18",count=18,buffer=36),
 variant("count22",count=22,buffer=44),
 variant("count24",count=24,buffer=48),
 variant("exposure97",exposure=.97),
 variant("exposure98",exposure=.98),
 variant("exposure99",exposure=.99),
 variant("cap135",cap=1.35),
 variant("cap165",cap=1.65),
]
assert len(V)==30

def main():
 OUT.mkdir(parents=True,exist_ok=True); f=bt.build_factor_cache(); ranks={}; union=set()
 for v in V:
  r=bt.ranked_months(f,v["bull"],v["bear"],v["ma"]); ranks[v["name"]]=r
  for x in r.values(): union.update(x.head(v["buffer"]).symbol)
 panel=bt.load_daily_panel(union); rows=[]; curves=[]
 for i,v in enumerate(V,1):
  print(f"micro30 [{i}/30] {v['name']}",flush=True)
  c,_=bt.simulate(ranks[v["name"]],bt.ACTIVE_VOLUME_LIMIT,v["count"],v["buffer"],v["exposure"],v["cap"],panel)
  dev=period(c,"2020-01-02","2023-12-31"); val=period(c,"2024-01-01","2024-12-31"); hold=period(c,"2025-01-01","2026-09-11"); full=bt.metrics(c,bt.INITIAL_CASH)
  annual=.5*dev["annual"]+.5*val["annual"]; sharpe=.5*dev["sharpe"]+.5*val["sharpe"]
  worst_dd=min(dev["dd"],val["dd"])
  # 以年化为主；Sharpe提供小幅奖励；回撤从30%起逐渐惩罚，35%为硬上限。
  score=annual+.025*sharpe-.35*max(0,abs(worst_dd)-.30)
  eligible=full["max_drawdown"]>=-.35
  rows.append({"name":v["name"],"selection_score":score,"eligible_dd35":eligible,
   "dev_annual":dev["annual"],"dev_dd":dev["dd"],"dev_sharpe":dev["sharpe"],
   "val_annual":val["annual"],"val_dd":val["dd"],"val_sharpe":val["sharpe"],
   "holdout_annual":hold["annual"],"holdout_dd":hold["dd"],"holdout_sharpe":hold["sharpe"],
   "full_annual":full["annualized_return"],"full_dd":full["max_drawdown"],"full_sharpe":full["sharpe"],
   "final_equity":full["final_equity"],"avg_holdings":full["average_holdings"],"parameters":json.dumps(v,ensure_ascii=False)})
  c["name"]=v["name"]; curves.append(c)
 out=pd.DataFrame(rows).sort_values(["eligible_dd35","selection_score"],ascending=False)
 out.to_csv(OUT/"variant_results.csv",index=False,encoding="utf-8-sig"); pd.concat(curves,ignore_index=True).to_parquet(OUT/"daily_curves.parquet",index=False)
 winner=out[out.eligible_dd35].iloc[0]; ref=out[out.name=="v2_reference"].iloc[0]
 (OUT/"winner.json").write_text(winner.to_json(force_ascii=False,indent=2),encoding="utf-8")
 lines=["# 沪深基准1 第四轮30项微调","","仅开发期与2024验证期参与评分；2025—2026/9保持锁定观察。评分以年化为主，轻度奖励Sharpe，并惩罚超过30%的选择期回撤；全期回撤硬限制35%。","",
 "|排名|方向|开发年化|2024年化|观察期年化|全期年化|回撤|Sharpe|期末资产|","|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
 for i,x in enumerate(out.itertuples(),1): lines.append(f"|{i}|{x.name}|{x.dev_annual:.2%}|{x.val_annual:.2%}|{x.holdout_annual:.2%}|{x.full_annual:.2%}|{x.full_dd:.2%}|{x.full_sharpe:.3f}|{x.final_equity/10000:.2f}万|")
 lines += ["",f"预设规则胜出：**{winner['name']}**。",f"相对V2：年化变化{winner['full_annual']-ref['full_annual']:+.2%}，回撤变化{winner['full_dd']-ref['full_dd']:+.2%}，Sharpe变化{winner['full_sharpe']-ref['full_sharpe']:+.3f}。"]
 (OUT/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8"); print(out.to_string(index=False),flush=True)

if __name__=="__main__": main()
