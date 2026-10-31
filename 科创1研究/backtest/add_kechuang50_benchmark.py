"""Attach STAR 50 benchmark and excess-return metrics to the frozen replay."""

from pathlib import Path
import hashlib
import json
import time

import numpy as np
import pandas as pd
import requests


ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
RESULT = (
    ROOT
    / "archive/legacy_layout/strategies"
    / "kechuang"
    / "results"
    / "q1_yearly_continuous_to_20261026"
)
URL = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sh000688,day,2019-12-20,2026-10-26,2000,qfq"
)


def download():
    session = requests.Session()
    session.trust_env = False
    error = None
    for attempt in range(6):
        try:
            response = session.get(
                URL,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://stockapp.finance.qq.com/",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("data", {}).get("sh000688", {}).get("day"):
                return response.content, payload
        except Exception as exc:
            error = exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Benchmark download failed: {error}")


def main():
    content, payload = download()
    data = payload["data"]["sh000688"]
    columns = ["date", "open", "close", "high", "low", "volume"]
    frame = pd.DataFrame(
        data["day"], columns=columns
    )
    frame["date"] = pd.to_datetime(frame["date"])
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    assert frame.date.min() <= pd.Timestamp("2019-12-31")
    assert frame.date.max() == pd.Timestamp("2026-10-26")

    raw_path = RESULT / "benchmark_000688_tencent.json"
    raw_path.write_bytes(content)
    frame.to_parquet(RESULT / "benchmark_000688.parquet", index=False)

    strategies = json.loads((RESULT / "summary.json").read_text(encoding="utf-8"))
    rows = []
    indexed = frame.set_index("date")
    for strategy in strategies:
        start = pd.Timestamp(strategy["start"])
        end = pd.Timestamp(strategy["end"])
        prior = indexed.index[indexed.index < start][-1]
        base = float(indexed.loc[prior, "close"])
        closes = indexed.loc[(indexed.index >= start) & (indexed.index <= end), "close"]
        if closes.empty or closes.index[-1] != end:
            raise AssertionError((strategy["label"], start, end))
        daily = pd.concat([pd.Series([base], index=[prior]), closes]).pct_change().dropna()
        benchmark_total = float(closes.iloc[-1] / base - 1)
        years = (end - start).days / 365.25
        benchmark_cagr = float((1 + benchmark_total) ** (1 / years) - 1)
        wealth = pd.concat([pd.Series([base], index=[prior]), closes]) / base
        benchmark_mdd = float((wealth / wealth.cummax() - 1).min())
        benchmark_sharpe = float(daily.mean() / daily.std() * np.sqrt(252))
        rows.append(
            {
                "label": strategy["label"],
                "start": strategy["start"],
                "end": strategy["end"],
                "strategy_total_return": strategy["total_return"],
                "benchmark_total_return": benchmark_total,
                "cumulative_excess_percentage_points": strategy["total_return"] - benchmark_total,
                "relative_wealth_excess": (1 + strategy["total_return"]) / (1 + benchmark_total) - 1,
                "strategy_cagr": strategy["cagr"],
                "benchmark_cagr": benchmark_cagr,
                "annualized_excess_percentage_points": strategy["cagr"] - benchmark_cagr,
                "strategy_max_drawdown": strategy["max_drawdown"],
                "benchmark_max_drawdown": benchmark_mdd,
                "strategy_sharpe": strategy["sharpe_rf0"],
                "benchmark_sharpe": benchmark_sharpe,
            }
        )

    (RESULT / "benchmark_comparison.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(rows).to_csv(
        RESULT / "benchmark_comparison.csv", index=False, encoding="utf-8-sig"
    )
    provenance = {
        "benchmark": "STAR 50",
        "code": "000688.SH",
        "price_source": "Tencent historical kline API",
        "url": URL,
        "downloaded_rows": len(frame),
        "first_date": str(frame.date.min().date()),
        "last_date": str(frame.date.max().date()),
        "raw_sha256": hashlib.sha256(content).hexdigest(),
        "return_base": "previous trading day close before strategy actual start",
        "excess_definition": "strategy return minus benchmark return, percentage points",
    }
    (RESULT / "benchmark_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
