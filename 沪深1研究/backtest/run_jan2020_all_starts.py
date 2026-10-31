"""Run Hushen1 from every January-2020 trading-session start to 2026-10-23."""
from pathlib import Path
import json

import pandas as pd

import run_jan2016_all_starts as base


OUT = base.HOME / "results/holdout_restricted/jan2020_all_starts_to_20261023"


def report(summary: pd.DataFrame, detail: pd.DataFrame, parity: list[dict]) -> str:
    lines = [
        "# 沪深1：2020年1月逐交易日起点至2026-10-23", "",
        f"- 起点：2020年1月全部{len(detail)}个交易日；每个独立账户初始资金100,000元。",
        "- 排名：使用沪深1登记基线冻结排名及随后逐日冻结的跟踪信号。",
        "- 执行：次日开盘日线近似、A股整手/T+1/涨跌停/停牌/成交量约束及历史费率；未在末日强平。",
        "- 冻结排名重建核验：{}。".format("全部一致" if all(x["equal"] for x in parity) else "失败"),
        "", "| 项目 | 平均 | 中位数 | 最小值 | 最大值 | 标准差 |", "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        values = [row.平均, row.中位数, row.最小值, row.最大值, row.标准差]
        if row.单位 == "percent":
            cells = [f"{value:.2%}" for value in values]
        elif row.单位 == "currency":
            cells = [f"{value:,.2f}" for value in values]
        else:
            cells = [f"{value:.3f}" for value in values]
        lines.append("| {} | {} |".format(row.项目, " | ".join(cells)))
    lines += ["", "## 各起点", "",
              "| 起点 | 期末资产 | 累计收益 | 年化 | 最大回撤 | Sharpe | 成交笔数 | 总成本 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in detail.itertuples(index=False):
        lines.append(f"| {row.actual_start} | {row.final_equity:,.2f} | {row.total_return:.2%} | "
                     f"{row.cagr:.2%} | {row.max_drawdown:.2%} | {row.sharpe:.3f} | "
                     f"{int(row.trades)} | {row.total_cost:,.2f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_audit = base.read_json(base.ROOT / "K线数据/更新备份与审计/20261023/audit.json")
    assert source_audit["status"] == "ok" and source_audit["target"] == base.TARGET
    dates = base.trading_calendar()
    meta = base.universe()
    receipts = base.verified_receipts()
    historical, rank_audit = base.build_historical_rankings(dates, meta, receipts)
    ranks = base.full_rankings(historical)
    starts = dates[(dates >= "2020-01-01") & (dates <= "2020-01-31")]
    assert len(starts) == 16
    runtime_dates = dates[dates >= "2015-12-01"]
    required = base.required_signal_dates(runtime_dates, starts)
    missing = sorted(required - set(ranks))
    if missing:
        raise RuntimeError("Missing signal dates: " + str(missing))
    ranks = {key: ranks[key] for key in required}
    symbols = sorted({symbol for values in ranks.values() for symbol in values})
    print("RUNTIME", len(starts), "starts", len(required), "signal dates", len(symbols), "symbols", flush=True)
    market = base.HistoricalMarket(dates, symbols, meta, receipts)
    results, curves, trades = [], [], []
    try:
        for index, start in enumerate(starts, 1):
            result, account = base.simulate(market, start, ranks)
            if result["unresolved_actions"] or result["reference_differences"]:
                raise RuntimeError(f"Unresolved ledger issue for {start.date()}: {result['issues']} {result['reference']}")
            results.append(result)
            curve = pd.DataFrame(account.curve)
            curve.insert(0, "requested_start", str(start.date()))
            curves.append(curve)
            tx = pd.DataFrame(account.trades)
            if len(tx):
                tx.insert(0, "requested_start", str(start.date()))
                trades.append(tx)
            print("RUN", index, len(starts), start.date(), round(result["cagr"], 4),
                  round(result["max_drawdown"], 4), flush=True)
    finally:
        market.actions.close()

    detail = pd.DataFrame(results)
    summary = base.metric_summary(detail)
    detail.to_csv(OUT / "all_starts.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    pd.concat(curves, ignore_index=True).to_parquet(OUT / "daily_equity_all_starts.parquet", index=False)
    if trades:
        pd.concat(trades, ignore_index=True).to_parquet(OUT / "trades_all_starts.parquet", index=False)
    base.write_json(OUT / "audit.json", {
        "status": "ok", "target": base.TARGET, "starts": len(starts), "initial_cash_each": 100000,
        "source_market_audit": source_audit, "historical_rank_audit": rank_audit,
        "required_signal_dates": len(required), "runtime_symbols": len(symbols),
        "ranking_policy": "registered frozen Hushen1 ranks and subsequently frozen tracking signals",
    })
    (OUT / "report.md").write_text(report(summary, detail, rank_audit["overlap_parity"]), encoding="utf-8")
    print("COMPLETE", OUT, flush=True)


if __name__ == "__main__":
    main()
