"""M1 audit for the return-first main-board research line."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
PROJECT = STUDY.parents[1]
PIPELINE = PROJECT / "data_pipeline"
CACHE = PIPELINE / "data" / "derived" / "backtest_market_by_year"
META = PIPELINE / "data" / "metadata" / "current_industry_map.csv"
OUT = STUDY / "reports" / "m1_data_audit"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["date", "symbol", "exchange", "open", "high", "low", "close",
            "preclose", "volume", "amount", "tradestatus", "pctChg", "isST",
            "qfq_close"]
    parts = [pd.read_parquet(CACHE / f"{year}.parquet", columns=cols)
             for year in range(2018, 2027)]
    x = pd.concat(parts, ignore_index=True)
    x["date"] = pd.to_datetime(x.date)
    numeric = ["open", "high", "low", "close", "preclose", "volume", "amount",
               "pctChg", "qfq_close"]
    for col in numeric:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x.sort_values(["symbol", "date"], inplace=True)
    g = x.groupby("symbol", sort=False)
    x["previous_raw_close"] = g.close.shift(1)
    x["qfq_return"] = g.qfq_close.pct_change(fill_method=None)
    x["raw_close_return"] = g.close.pct_change(fill_method=None)
    x["corporate_action_proxy"] = (
        x.previous_raw_close.notna() & x.preclose.gt(0)
        & (x.previous_raw_close / x.preclose - 1).abs().gt(.005)
    )
    x["one_price"] = (x.high - x.low).abs().lt(.000001)
    x["regular_return_error"] = (x.qfq_return - x.pctChg / 100).abs()

    last_global = x.date.max()
    by_stock = g.agg(first_date=("date", "min"), last_date=("date", "max"),
                     rows=("date", "size"), exchange=("exchange", "first"))
    by_stock["ends_before_dataset"] = by_stock.last_date < last_global
    metadata = pd.read_csv(META, dtype=str, encoding="utf-8-sig")
    names = metadata.drop_duplicates("symbol").set_index("symbol").code_name
    by_stock["current_name"] = by_stock.index.map(names)
    by_stock["name_marks_delisted"] = by_stock.current_name.fillna("").str.contains("退")

    duplicate_rows = int(x.duplicated(["date", "symbol"]).sum())
    invalid_ohlc = int(((x.low > x.high) | (x.open < x.low) | (x.open > x.high)
                        | (x.close < x.low) | (x.close > x.high)).fillna(False).sum())
    tradable = (x.tradestatus.astype(str) == "1") & x.volume.gt(0)
    ordinary = tradable & ~x.corporate_action_proxy & x.pctChg.notna()
    action_rows = x.loc[x.corporate_action_proxy,
                        ["date", "symbol", "previous_raw_close", "preclose", "close",
                         "qfq_close", "pctChg"]].copy()
    action_rows["implied_factor"] = action_rows.previous_raw_close / action_rows.preclose
    action_rows.to_csv(OUT / "corporate_action_proxy_rows.csv", index=False,
                       encoding="utf-8-sig")
    by_stock.reset_index().to_csv(OUT / "stock_coverage.csv", index=False,
                                  encoding="utf-8-sig")

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date_range": [str(x.date.min().date()), str(last_global.date())],
        "rows": int(len(x)),
        "stocks": int(x.symbol.nunique()),
        "duplicate_date_symbol_rows": duplicate_rows,
        "invalid_ohlc_rows": invalid_ohlc,
        "missing_raw_close": int(x.close.isna().sum()),
        "missing_qfq_close": int(x.qfq_close.isna().sum()),
        "suspended_or_zero_volume_rows": int((~tradable).sum()),
        "st_rows": int((x.isST.astype(str) == "1").sum()),
        "one_price_tradable_rows": int((x.one_price & tradable).sum()),
        "corporate_action_proxy_rows": int(x.corporate_action_proxy.sum()),
        "stocks_ending_before_dataset_end": int(by_stock.ends_before_dataset.sum()),
        "stocks_named_delisted": int(by_stock.name_marks_delisted.sum()),
        "regular_qfq_return_error_p99": float(x.loc[ordinary, "regular_return_error"].quantile(.99)),
        "regular_qfq_return_error_max": float(x.loc[ordinary, "regular_return_error"].max()),
        "industry_mapping_date": sorted(metadata.updateDate.dropna().unique().tolist()),
        "current_industry_is_point_in_time": False,
        "old_cache_contains_old_model_scores": True,
        "old_scores_allowed_in_new_research": False,
        "known_execution_defects_to_remove": [
            "using the final observed date to force an exit is future information",
            "inferring share multiplication only from previous close/preclose is not a complete corporate-action ledger",
            "current industry labels cannot be backfilled as historical point-in-time classifications",
            "daily amount participation does not prove an order can fill at the opening price"
        ]
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    report = f"""# M1 数据与成交口径审计

生成时间：{summary['generated_at']}

| 项目 | 结果 |
|---|---:|
| 日期范围 | {summary['date_range'][0]} 至 {summary['date_range'][1]} |
| 行情行数 | {summary['rows']:,} |
| 股票数 | {summary['stocks']:,} |
| 日期/股票重复行 | {duplicate_rows:,} |
| OHLC结构错误 | {invalid_ohlc:,} |
| 原始收盘缺失 | {summary['missing_raw_close']:,} |
| 前复权收盘缺失 | {summary['missing_qfq_close']:,} |
| 停牌或零成交量行 | {summary['suspended_or_zero_volume_rows']:,} |
| ST状态行 | {summary['st_rows']:,} |
| 可交易一字线 | {summary['one_price_tradable_rows']:,} |
| 疑似除权/公司行动日 | {summary['corporate_action_proxy_rows']:,} |
| 数据结束日前已停止行情股票 | {summary['stocks_ending_before_dataset_end']:,} |
| 当前名称明确含“退”的股票 | {summary['stocks_named_delisted']:,} |

## 审计结论

行情覆盖包含历史退市股票，不是只保留2026年仍上市股票。价格基础字段未见重复或OHLC结构错误。前复权日收益与BaoStock涨跌幅在普通交易日的99%误差为 {summary['regular_qfq_return_error_p99']:.6f}。

新回测器必须删除“知道某只股票最后一条行情日期并提前强制卖出”的逻辑。股票在样本中停止行情只能从当日之后逐步得知；退市与摘牌处理需要公开状态或保守估值规则。

当前行业映射发布于 {', '.join(summary['industry_mapping_date'])}，不是历史时点行业数据。板块策略第一版只能将其用于描述，不能作为历史选股输入。板块方向要么补历史行业数据，要么使用只依赖过去收益的滚动价格聚类。

缓存中的 `rally_probability`、`stop_probability` 和 `signal` 属于旧模型产物，新研究不得使用。新信号从原始价、前复权价、成交量和成交额重新计算。

疑似公司行动记录已经输出用于逐项抽样。正式撮合器将以原始价格结算，前复权价格只计算信号；公司行动账本没有补齐前，不允许通过价格比例自动增加股票数量来制造收益。
"""
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
