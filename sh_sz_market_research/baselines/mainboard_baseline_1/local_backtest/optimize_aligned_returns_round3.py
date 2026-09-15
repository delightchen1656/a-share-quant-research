"""收益优化第三轮：交叉验证弱市权重与宽缓冲区。"""
from pathlib import Path
import json
import pandas as pd
import supermind_aligned_backtest as bt
from optimize_aligned_returns import period

OUT=Path(__file__).resolve().parent/"outputs"/"return_optimization_round_3"
V=[
 {"name":"quality25_wide","bear":(.50,.25,.25),"buffer":60,"exposure":.95,"count":20},
 {"name":"quality25_full","bear":(.50,.25,.25),"buffer":40,"exposure":1.0,"count":20},
 {"name":"quality25_wide_full","bear":(.50,.25,.25),"buffer":60,"exposure":1.0,"count":20},
 {"name":"blend_wide","bear":(.525,.275,.20),"buffer":60,"exposure":.95,"count":20},
 {"name":"deep_wide_0975","bear":(.55,.30,.15),"buffer":60,"exposure":.975,"count":20},
 {"name":"deep_wide_15","bear":(.55,.30,.15),"buffer":45,"exposure":.95,"count":15},
 {"name":"deep_wide_25","bear":(.55,.30,.15),"buffer":75,"exposure":.95,"count":25},
 {"name":"blend_wide_25","bear":(.525,.275,.20),"buffer":75,"exposure":.95,"count":25},
]
for v in V: v.update({"bull":(.25,.20,.55),"ma":120,"cap":1.5})

def main():
 OUT.mkdir(parents=True,exist_ok=True); f=bt.build_factor_cache(); rr={}; union=set()
 for v in V:
  r=bt.ranked_months(f,v["bull"],v["bear"],v["ma"]); rr[v["name"]]=r
  for x in r.values(): union.update(x.head(v["buffer"]).symbol)
 panel=bt.load_daily_panel(union); rows=[]; curves=[]
 for i,v in enumerate(V,1):
  print(f"round3 [{i}/{len(V)}] {v['name']}",flush=True)
  c,_=bt.simulate(rr[v["name"]],bt.ACTIVE_VOLUME_LIMIT,v["count"],v["buffer"],v["exposure"],v["cap"],panel)
  dev=period(c,"2020-01-02","2023-12-31"); val=period(c,"2024-01-01","2024-12-31"); hold=period(c,"2025-01-01","2026-09-11"); full=bt.metrics(c,bt.INITIAL_CASH)
  rows.append({"name":v["name"],"selection_score":.5*dev["annual"]+.5*val["annual"],"eligible_dd35":full["max_drawdown"]>=-.35,
   "dev_annual":dev["annual"],"dev_dd":dev["dd"],"val_annual":val["annual"],"val_dd":val["dd"],"holdout_annual":hold["annual"],"holdout_dd":hold["dd"],
   "full_annual":full["annualized_return"],"full_dd":full["max_drawdown"],"full_sharpe":full["sharpe"],"final_equity":full["final_equity"],"avg_holdings":full["average_holdings"],"parameters":json.dumps(v,ensure_ascii=False)})
  c["name"]=v["name"]; curves.append(c)
 out=pd.DataFrame(rows).sort_values(["eligible_dd35","selection_score"],ascending=False)
 out.to_csv(OUT/"variant_results.csv",index=False,encoding="utf-8-sig"); pd.concat(curves).to_parquet(OUT/"daily_curves.parquet",index=False)
 winner=out[out.eligible_dd35].iloc[0]; (OUT/"winner.json").write_text(winner.to_json(force_ascii=False,indent=2),encoding="utf-8")
 lines=["# 沪深基准1 收益优化第三轮","","开发期与2024验证期各占50%选择，2025—2026/9不参与选择，全期回撤不超过35%。","",
 "|排名|方向|开发年化|2024年化|观察期年化|全期年化|回撤|Sharpe|期末资产|","|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
 for i,x in enumerate(out.itertuples(),1): lines.append(f"|{i}|{x.name}|{x.dev_annual:.2%}|{x.val_annual:.2%}|{x.holdout_annual:.2%}|{x.full_annual:.2%}|{x.full_dd:.2%}|{x.full_sharpe:.3f}|{x.final_equity/10000:.2f}万|")
 lines += ["",f"预设规则胜出：**{winner['name']}**。"]
 (OUT/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8"); print(out.to_string(index=False),flush=True)

if __name__=="__main__": main()
