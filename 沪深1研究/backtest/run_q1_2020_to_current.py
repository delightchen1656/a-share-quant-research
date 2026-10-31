"""Extend every 2020-Q1 Hushen1 start through the latest audited session."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

import engine as e


HOME = Path(__file__).resolve().parents[1]
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
TRACKING = HOME / "tracking"
SOURCE_RESULTS = HOME / "results" / "q1_2020_start_distribution"
TARGET = "2026-10-22"
OUT = HOME / "results" / "q1_2020_to_20261022"
WORK = OUT / "runtime_inputs"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def configure_current_engine():
    audit = read(ROOT / "K线数据/更新备份与审计" / TARGET.replace("-", "") / "audit.json")
    assert audit["status"] == "ok" and audit["target"] == TARGET
    cfg = read(TRACKING / "config.json")
    actual = hashlib.sha256((HOME / "supermind_hushen_1.py").read_bytes()).hexdigest()
    assert actual == cfg["entry_sha256"]

    WORK.mkdir(parents=True, exist_ok=True)
    calendar = pd.read_parquet(TRACKING / "ledger_inputs" / "calendar.parquet")
    assert str(pd.to_datetime(calendar.date).max().date()) == TARGET
    calendar.to_parquet(WORK / "calendar.parquet", index=False)
    inputs = read(TRACKING / "ledger_inputs" / "inputs.json")
    write_json(WORK / "inputs.json", inputs)

    ranks = read(HOME / "results" / "latest" / "rankings_original.json")
    for path in sorted((TRACKING / "signals").glob("*.json")):
        signal = read(path)
        assert signal["strategy_sha256"] == cfg["entry_sha256"]
        ranks[path.stem] = signal["ranks"]
    write_json(WORK / "rankings_original.json", ranks)

    e.HERE = WORK
    e.r.HERE = WORK
    e.r.DATA = ROOT / "archive/legacy_layout/sh_sz_market_research" / "data_pipeline" / "data"
    e.r.Q = dict(e.r.Q, end=TARGET)
    source = (HOME / "backtest" / "engine.py").read_text(encoding="utf-8")
    source = source.replace("BASE/'data/benchmark.parquet'", "HERE/'calendar.parquet'")
    exec(compile(source, str(HOME / "backtest" / "engine.py"), "exec"), e.__dict__)
    return audit, cfg


def validate_historical_prefix(market):
    prior = pd.read_csv(SOURCE_RESULTS / "all_starts.csv").set_index("actual_start")
    probes = [prior.index[0], prior.index[len(prior) // 2], prior.index[-1]]
    checks = []
    for start in probes:
        result, _ = e.simulate(market, start, "2026-09-30")
        expected = prior.loc[start]
        for field in ["final_equity", "total_return", "cagr", "max_drawdown", "sharpe", "total_cost"]:
            assert np.isclose(float(result[field]), float(expected[field]), rtol=0, atol=1e-8), (start, field, result[field], expected[field])
        checks.append({"start": start, "prefix_identical": True})
    return checks, prior.index.tolist()


def index_series(stem):
    base = pd.read_csv(SOURCE_RESULTS / (stem + ".csv"), usecols=["date", "close"])
    extra = pd.read_csv(SOURCE_RESULTS / (stem + "_oct.csv"), usecols=["date", "close"])
    data = pd.concat([base, extra], ignore_index=True)
    data["date"] = pd.to_datetime(data.date)
    data["close"] = pd.to_numeric(data.close)
    data = data.drop_duplicates("date", keep="last").sort_values("date").set_index("date").close
    assert data.index[-1] == pd.Timestamp(TARGET)
    return data


def benchmark_metrics(series, start):
    start = pd.Timestamp(start)
    values = series.loc[start:TARGET]
    assert values.index[0] == start and values.index[-1] == pd.Timestamp(TARGET)
    nav = values / values.iloc[0]
    daily = values.pct_change().dropna()
    days = (values.index[-1] - values.index[0]).days + 1
    return {
        "total_return": float(nav.iloc[-1] - 1),
        "cagr": float(nav.iloc[-1] ** (365.25 / days) - 1),
        "max_drawdown": float((1 - nav / nav.cummax()).max()),
        "sharpe": float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)),
    }


def annual_segments(dates, values, start, label):
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    values = pd.Series(np.asarray(values, dtype=float), index=dates).sort_index()
    start = pd.Timestamp(start)
    rows = []
    for year in range(start.year, pd.Timestamp(TARGET).year + 1):
        end_date = values.index[values.index.year == year].max()
        if pd.isna(end_date):
            continue
        if year == start.year:
            baseline = 100000.0 if label == "strategy" else float(values.loc[start])
            period_start = start
        else:
            prior = values.index[values.index < pd.Timestamp(year=year, month=1, day=1)]
            assert len(prior)
            baseline = float(values.loc[prior[-1]])
            period_start = pd.Timestamp(year=year, month=1, day=1)
        total_return = float(values.loc[end_date] / baseline - 1)
        days = (end_date - period_start).days + 1
        annualized = float((1 + total_return) ** (365.25 / days) - 1)
        rows.append(dict(year=year, period_start=str(period_start.date()), period_end=str(end_date.date()),
                         total_return=total_return, annualized_return=annualized))
    return rows


def annual_benchmark_rows(series, start, prefix):
    subset = series.loc[pd.Timestamp(start):TARGET]
    rows = annual_segments(subset.index, subset.to_numpy(), start, prefix)
    return {row["year"]: row for row in rows}


def add_benchmarks(frame):
    indexes = {"hs300": index_series("sh_000300"), "sse": index_series("sh_000001")}
    for prefix, series in indexes.items():
        rows = [benchmark_metrics(series, start) for start in frame.actual_start]
        values = pd.DataFrame(rows)
        for col in values.columns:
            frame[prefix + "_" + col] = values[col].to_numpy()
        frame["excess_vs_" + prefix + "_cagr_difference"] = frame.cagr - frame[prefix + "_cagr"]
        years = ((pd.Timestamp(TARGET) - pd.to_datetime(frame.actual_start)).dt.days + 1) / 365.25
        relative_wealth = (1 + frame.total_return) / (1 + frame[prefix + "_total_return"])
        frame["excess_vs_" + prefix + "_geometric_cagr"] = relative_wealth ** (1 / years) - 1
    return frame


def metric_row(label, series):
    return {
        "项目": label,
        "平均": float(series.mean()),
        "中位数": float(series.median()),
        "最小值": float(series.min()),
        "最大值": float(series.max()),
        "标准差": float(series.std(ddof=1)),
    }


def summarize(frame):
    rows = [
        metric_row("沪深1年化收益", frame.cagr),
        metric_row("沪深300年化收益", frame.hs300_cagr),
        metric_row("相对沪深300年化超额（直接相减）", frame.excess_vs_hs300_cagr_difference),
        metric_row("相对沪深300年化超额（财富比率）", frame.excess_vs_hs300_geometric_cagr),
        metric_row("上证指数年化收益", frame.sse_cagr),
        metric_row("相对上证年化超额（直接相减）", frame.excess_vs_sse_cagr_difference),
        metric_row("相对上证年化超额（财富比率）", frame.excess_vs_sse_geometric_cagr),
        metric_row("沪深1最大回撤", frame.max_drawdown),
        metric_row("沪深1 Sharpe", frame.sharpe),
        metric_row("沪深300最大回撤", frame.hs300_max_drawdown),
        metric_row("沪深300 Sharpe", frame.hs300_sharpe),
        metric_row("上证指数最大回撤", frame.sse_max_drawdown),
        metric_row("上证指数 Sharpe", frame.sse_sharpe),
    ]
    return pd.DataFrame(rows)


def summarize_annual(annual):
    rows = []
    for year, group in annual.groupby("year", sort=True):
        rows.append({
            "year": int(year),
            "period": ("各自起点至2020-12-31" if year == 2020 else
                       ("2026-01-01至2026-10-22" if year == 2026 else f"{year}-01-01至{year}-12-31")),
            "strategy_period_return_mean": float(group.strategy_total_return.mean()),
            "strategy_annualized_mean": float(group.strategy_annualized_return.mean()),
            "strategy_annualized_min": float(group.strategy_annualized_return.min()),
            "strategy_annualized_max": float(group.strategy_annualized_return.max()),
            "hs300_annualized_mean": float(group.hs300_annualized_return.mean()),
            "excess_vs_hs300_mean": float(group.excess_vs_hs300.mean()),
            "sse_annualized_mean": float(group.sse_annualized_return.mean()),
            "excess_vs_sse_mean": float(group.excess_vs_sse.mean()),
        })
    return pd.DataFrame(rows)


def report_markdown(summary, count):
    lines = [
        "# 沪深1：2020年第一季度逐交易日起点至2026-10-22",
        "",
        "- 独立起点：{}个；每个账户初始资金100,000元".format(count),
        "- 指数口径：起点收盘至末日收盘；策略口径沿用本地日线撮合账户",
        "- 年化超额（直接相减）=策略CAGR-指数CAGR；财富比率口径按策略净值/指数净值复合年化",
        "",
        "| 项目 | 平均 | 中位数 | 最小值 | 最大值 | 标准差 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        if "Sharpe" in row.项目:
            vals = ["{:.3f}".format(v) for v in row[1:]]
        else:
            vals = ["{:.2%}".format(v) for v in row[1:]]
        lines.append("| {} | {} |".format(row.项目, " | ".join(vals)))
    lines.append("")
    return "\n".join(lines)


def annual_markdown(annual_summary):
    lines = [
        "# 沪深1逐年收益与年化超额",
        "",
        "| 年度 | 统计区间 | 沪深1区间收益 | 沪深1年化 | 年化范围 | 沪深300年化 | 对沪深300超额 | 上证年化 | 对上证超额 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in annual_summary.itertuples(index=False):
        lines.append("| {} | {} | {:.2%} | {:.2%} | {:.2%}—{:.2%} | {:.2%} | {:+.2%} | {:.2%} | {:+.2%} |".format(
            row.year, row.period, row.strategy_period_return_mean, row.strategy_annualized_mean,
            row.strategy_annualized_min, row.strategy_annualized_max, row.hs300_annualized_mean,
            row.excess_vs_hs300_mean, row.sse_annualized_mean, row.excess_vs_sse_mean))
    lines += ["", "超额为58个账户逐一计算‘沪深1年化－指数年化’后取平均。2020起点不同；2026为截至10月22日的年化折算。", ""]
    return "\n".join(lines)


def main():
    audit, cfg = configure_current_engine()
    OUT.mkdir(parents=True, exist_ok=True)
    market = e.Market()
    try:
        prefix_checks, starts = validate_historical_prefix(market)
        results = []
        annual_rows = []
        hs300 = index_series("sh_000300")
        sse = index_series("sh_000001")
        for start in starts:
            result, account = e.simulate(market, start, TARGET)
            assert result["unresolved_actions"] == 0
            assert result["reference_differences"] == 0
            results.append(result)
            strategy_years = annual_segments(
                [x["date"] for x in account.curve], [x["equity"] for x in account.curve], start, "strategy")
            hs300_years = annual_benchmark_rows(hs300, start, "hs300")
            sse_years = annual_benchmark_rows(sse, start, "sse")
            for row in strategy_years:
                year = row["year"]
                annual_rows.append({
                    "start": start,
                    "year": year,
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "strategy_total_return": row["total_return"],
                    "strategy_annualized_return": row["annualized_return"],
                    "hs300_total_return": hs300_years[year]["total_return"],
                    "hs300_annualized_return": hs300_years[year]["annualized_return"],
                    "excess_vs_hs300": row["annualized_return"] - hs300_years[year]["annualized_return"],
                    "sse_total_return": sse_years[year]["total_return"],
                    "sse_annualized_return": sse_years[year]["annualized_return"],
                    "excess_vs_sse": row["annualized_return"] - sse_years[year]["annualized_return"],
                })
    finally:
        market.actions.close()
    frame = add_benchmarks(pd.DataFrame(results))
    summary = summarize(frame)
    annual = pd.DataFrame(annual_rows)
    annual_summary = summarize_annual(annual)
    frame.to_csv(OUT / "all_starts_with_benchmarks.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(OUT / "annual_by_start.csv", index=False, encoding="utf-8-sig")
    annual_summary.to_csv(OUT / "annual_summary.csv", index=False, encoding="utf-8-sig")
    (OUT / "report.md").write_text(report_markdown(summary, len(frame)), encoding="utf-8")
    (OUT / "annual_report.md").write_text(annual_markdown(annual_summary), encoding="utf-8")
    write_json(OUT / "audit.json", {
        "target": TARGET,
        "market_audit_updated_at": audit["updated_at"],
        "strategy_sha256": cfg["entry_sha256"],
        "starts": len(frame),
        "historical_prefix_probes": prefix_checks,
        "unresolved_actions_total": int(frame.unresolved_actions.sum()),
        "reference_differences_total": int(frame.reference_differences.sum()),
        "index_source": "BaoStock sh.000300 and sh.000001 daily close",
    })
    print("COMPLETE", OUT / "report.md", "starts", len(frame), flush=True)


if __name__ == "__main__":
    main()
