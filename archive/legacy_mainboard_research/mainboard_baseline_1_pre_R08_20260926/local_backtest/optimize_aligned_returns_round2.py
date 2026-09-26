"""收益优化第二轮：验证弱市深度反转与组合结构的交互。"""
from pathlib import Path
import json
import pandas as pd

import supermind_aligned_backtest as bt
from optimize_aligned_returns import period


OUT = Path(__file__).resolve().parent / "outputs" / "return_optimization_round_2"
V = [
 {"name":"deep_base","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":20,"buffer":40,"exposure":.95,"cap":1.5},
 {"name":"deep_full","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":20,"buffer":40,"exposure":1.0,"cap":1.5},
 {"name":"deep_wide","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":20,"buffer":60,"exposure":.95,"cap":1.5},
 {"name":"deep_full_wide","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":20,"buffer":60,"exposure":1.0,"cap":1.5},
 {"name":"deep_25","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":25,"buffer":50,"exposure":.95,"cap":1.5},
 {"name":"deep_15","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":15,"buffer":30,"exposure":.95,"cap":1.5},
 {"name":"deeper_65","bull":(.25,.20,.55),"bear":(.65,.30,.05),"ma":120,"count":20,"buffer":40,"exposure":.95,"cap":1.5},
 {"name":"deep_quality25","bull":(.25,.20,.55),"bear":(.50,.25,.25),"ma":120,"count":20,"buffer":40,"exposure":.95,"cap":1.5},
 {"name":"deep_fast80","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":80,"count":20,"buffer":40,"exposure":.95,"cap":1.5},
 {"name":"deep_cap20","bull":(.25,.20,.55),"bear":(.55,.30,.15),"ma":120,"count":20,"buffer":40,"exposure":.95,"cap":2.0},
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    f=bt.build_factor_cache(); ranks={}; union=set()
    for v in V:
        r=bt.ranked_months(f,v["bull"],v["bear"],v["ma"]); ranks[v["name"]]=r
        for x in r.values(): union.update(x.head(v["buffer"]).symbol)
    panel=bt.load_daily_panel(union); rows=[]; curves=[]
    for i,v in enumerate(V,1):
        print("round2 [%d/%d] %s"%(i,len(V),v["name"]),flush=True)
        c,_=bt.simulate(ranks[v["name"]],bt.ACTIVE_VOLUME_LIMIT,v["count"],v["buffer"],v["exposure"],v["cap"],panel)
        dev=period(c,"2020-01-02","2023-12-31"); val=period(c,"2024-01-01","2024-12-31")
        hold=period(c,"2025-01-01","2026-09-11"); full=bt.metrics(c,bt.INITIAL_CASH)
        rows.append({"name":v["name"],"selection_score":.5*dev["annual"]+.5*val["annual"],
          "eligible_dd35":full["max_drawdown"]>=-.35,"dev_annual":dev["annual"],"dev_dd":dev["dd"],
          "val_annual":val["annual"],"val_dd":val["dd"],"holdout_annual":hold["annual"],
          "holdout_dd":hold["dd"],"full_annual":full["annualized_return"],"full_dd":full["max_drawdown"],
          "full_sharpe":full["sharpe"],"final_equity":full["final_equity"],
          "avg_holdings":full["average_holdings"],"parameters":json.dumps(v,ensure_ascii=False)})
        c["name"]=v["name"]; curves.append(c)
    out=pd.DataFrame(rows).sort_values(["eligible_dd35","selection_score"],ascending=False)
    out.to_csv(OUT/"variant_results.csv",index=False,encoding="utf-8-sig")
    pd.concat(curves,ignore_index=True).to_parquet(OUT/"daily_curves.parquet",index=False)
    winner=out[out.eligible_dd35].iloc[0]
    (OUT/"winner.json").write_text(winner.to_json(force_ascii=False,indent=2),encoding="utf-8")
    lines=["# 沪深基准1 收益优化第二轮","","选择规则仍为开发期与2024验证期年化各50%，全期回撤不超过35%。","",
      "|排名|方向|开发年化|2024年化|观察期年化|全期年化|回撤|Sharpe|期末资产|",
      "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i,x in enumerate(out.itertuples(),1):
        lines.append(f"|{i}|{x.name}|{x.dev_annual:.2%}|{x.val_annual:.2%}|{x.holdout_annual:.2%}|{x.full_annual:.2%}|{x.full_dd:.2%}|{x.full_sharpe:.3f}|{x.final_equity/10000:.2f}万|")
    lines += ["",f"按预先选择规则胜出：**{winner['name']}**。"]
    (OUT/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(out.to_string(index=False),flush=True)


if __name__ == "__main__": main()
