"""Run Hushen1 from every 2020-Q1 trading-session start to 2026-09-30."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import tempfile

import numpy as np
import pandas as pd

import engine as e


HOME = Path(__file__).resolve().parents[1]
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
OUT = HOME / "results" / "q1_2020_start_distribution"
SNAPSHOT = ROOT / "K线数据/更新备份与审计" / "20261009" / "before_update" / "archive/legacy_layout/sh_sz_market_research" / "data_pipeline" / "data"
LIVE_DATA = ROOT / "archive/legacy_layout/sh_sz_market_research" / "data_pipeline" / "data"
END = "2026-09-30"
METRICS = [
    "final_equity",
    "total_return",
    "cagr",
    "max_drawdown",
    "sharpe",
    "trades",
    "total_cost",
    "average_exposure",
]


def validate_frozen_inputs():
    manifest = json.loads((HOME / "research" / "migration.json").read_text(encoding="utf-8"))
    actual = hashlib.sha256((HOME / "supermind_hushen_1.py").read_bytes()).hexdigest()
    assert actual == manifest["entry_sha256"], "Strategy changed: rebuild and validate rankings first"
    for relative, expected in manifest["runtime_input_hashes"].items():
        actual = hashlib.sha256((HOME / relative).read_bytes()).hexdigest()
        assert actual == expected, "Frozen input changed: " + relative
    inputs = json.loads((HOME / "results" / "latest" / "inputs.json").read_text(encoding="utf-8"))
    assert SNAPSHOT.is_dir(), "Frozen 2026-09-30 market snapshot is missing"
    sources = {}
    for record in inputs["files"]:
        relative = Path("raw") / record["symbol"][-2:] / (record["symbol"] + ".parquet")
        matches = []
        for root in (SNAPSHOT, LIVE_DATA):
            path = root / relative
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]:
                matches.append(path)
        assert matches, "No byte-identical frozen market input: " + record["symbol"]
        sources[relative] = matches[0]
    return manifest, sources


def materialize_frozen_root(root, sources):
    root = Path(root)
    for relative, source in sources.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    metadata = root / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAPSHOT / "metadata" / "historical_mainboard_universe.csv",
                 metadata / "historical_mainboard_universe.csv")


def stats_table(frame):
    rows = []
    labels = [("最小值", 0), ("P10", .10), ("P25", .25), ("中位数", .50),
              ("均值", "mean"), ("标准差", "std"), ("P75", .75), ("P90", .90), ("最大值", 1)]
    for label, operation in labels:
        row = {"统计": label}
        for col in METRICS:
            series = pd.to_numeric(frame[col], errors="coerce")
            if operation == "mean":
                value = series.mean()
            elif operation == "std":
                value = series.std(ddof=1)
            else:
                value = series.quantile(operation)
            row[col] = float(value)
        rows.append(row)
    return pd.DataFrame(rows)


def pct(value):
    return "{:.2%}".format(value)


def money(value):
    return "{:,.2f}".format(value)


def build_markdown(frame, stats):
    best = frame.loc[frame.total_return.idxmax()]
    worst = frame.loc[frame.total_return.idxmin()]
    positive = float((frame.total_return > 0).mean())
    dispersion = float(frame.total_return.std(ddof=1))
    lines = [
        "# 沪深1：2020年第一季度逐交易日起点回测",
        "",
        "- 策略：当前冻结的沪深1 D7f（固定5只、98%仓位、20交易日调仓）",
        "- 初始资金：100,000元；统一终点：2026-09-30",
        "- 口径：日线近似撮合、T+1、整手、涨跌停/停牌限制、历史费用和公司行动；末日不强制平仓",
        "- 起点：2020年第一季度全部交易日，共{}个独立账户".format(len(frame)),
        "",
        "## 综合统计",
        "",
        "| 统计 | 最终资产 | 累计收益 | 年化收益 | 最大回撤 | Sharpe | 成交笔数 | 总费用 | 平均仓位 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in stats.itertuples(index=False):
        lines.append("| {} | {} | {} | {} | {} | {:.3f} | {:.0f} | {} | {} |".format(
            row[0], money(row.final_equity), pct(row.total_return), pct(row.cagr),
            pct(row.max_drawdown), row.sharpe, row.trades, money(row.total_cost),
            pct(row.average_exposure)))
    lines += [
        "",
        "## 起点敏感度",
        "",
        "| 项目 | 结果 |",
        "|---|---:|",
        "| 盈利起点占比 | {} |".format(pct(positive)),
        "| 累计收益标准差 | {} |".format(pct(dispersion)),
        "| 最好起点 | {} |".format(best.actual_start),
        "| 最好累计收益 | {} |".format(pct(best.total_return)),
        "| 最差起点 | {} |".format(worst.actual_start),
        "| 最差累计收益 | {} |".format(pct(worst.total_return)),
        "| 最好与最差收益差 | {} |".format(pct(best.total_return - worst.total_return)),
        "",
        "## 全部起点",
        "",
        "完整逐日起点结果见 `all_starts.csv`。",
        "",
    ]
    return "\n".join(lines)


def main():
    manifest, sources = validate_frozen_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    # Active shares come from the exact pre-update snapshot; delisted files that were
    # not copied into that snapshot are accepted only when the live file still matches
    # the frozen whole-file hash. A temporary hard-link tree gives Market one clean root.
    with tempfile.TemporaryDirectory(prefix="hushen1_frozen_") as temp:
        materialize_frozen_root(temp, sources)
        e.r.DATA = Path(temp)
        market = e.Market()
        try:
            starts = market.dates[(market.dates >= "2020-01-01") & (market.dates <= "2020-03-31")]
            assert len(starts) > 0
            for start in starts:
                start_text = str(start.date())
                result, _ = e.simulate(market, start_text, END)
                assert result["actual_start"] == start_text
                assert result["unresolved_actions"] == 0
                result["version"] = "Hushen1 D7f; every 2020-Q1 session start"
                results.append(result)
        finally:
            market.actions.close()

    frame = pd.DataFrame(results).sort_values("actual_start").reset_index(drop=True)
    assert frame.actual_start.is_unique
    assert len(frame) == len(starts)
    stats = stats_table(frame)
    detail_columns = ["requested_start", "actual_start", "end", "initial_cash"] + METRICS + [
        "commission", "transfer", "stamp", "dividend_tax", "rejected_orders",
        "unresolved_actions", "reference_differences",
    ]
    frame[detail_columns].to_csv(OUT / "all_starts.csv", index=False, encoding="utf-8-sig")
    stats.to_csv(OUT / "aggregate.csv", index=False, encoding="utf-8-sig")
    report = build_markdown(frame, stats)
    (OUT / "report.md").write_text(report, encoding="utf-8")
    audit = {
        "strategy_sha256": manifest["entry_sha256"],
        "start_window": ["2020-01-01", "2020-03-31"],
        "end": END,
        "number_of_starts": len(frame),
        "initial_cash_each": 100000,
        "market_snapshot": str(SNAPSHOT),
        "delisted_frozen_files_reused_from_live_library": sum(1 for p in sources.values() if LIVE_DATA in p.parents),
        "all_actual_starts_unique": bool(frame.actual_start.is_unique),
        "unresolved_actions_total": int(frame.unresolved_actions.sum()),
        "reference_differences_total": int(frame.reference_differences.sum()),
    }
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COMPLETE", OUT / "report.md", "starts", len(frame), flush=True)


if __name__ == "__main__":
    main()
