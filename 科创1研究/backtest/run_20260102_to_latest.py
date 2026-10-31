"""One-off audited replay of Kechuang Baseline 1 from 2026-01-02.

This extends the frozen strategy over the latest transactionally committed
market data.  It does not retrain the models, change strategy parameters, or
replace the frozen 2026-09-30 parity replay in run.py.
"""

from pathlib import Path
import json
import shutil

import pandas as pd

import data_helpers as p
import engine as e


HERE = Path(__file__).resolve().parent
STAR = HERE.parent
ROOT = next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
REQUESTED_START = "2026-01-02"
INITIAL_CASH = 500000.0


def latest_committed_audit():
    audits = sorted((ROOT / "K线数据/更新备份与审计").glob("*/audit.json"))
    for path in reversed(audits):
        audit = json.loads(path.read_text(encoding="utf-8"))
        if audit.get("status") == "ok":
            target = pd.Timestamp(audit["target"])
            active = pd.Timestamp(
                audit["validation"]["active_symbol_latest_date"]
            )
            if target == active:
                return path, audit, target
    raise RuntimeError("No successful, internally consistent market-data audit")


def main():
    audit_path, audit, end = latest_committed_audit()
    out = STAR / "results" / f"20260102_to_{end:%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)

    source = STAR / "supermind_kechuang_1.py"
    provenance = json.loads(
        (STAR / "research/provenance.json").read_text(encoding="utf-8")
    )
    assert p.sha(source) == provenance["platform_sha256"], (
        "Platform source changed; provenance must be revalidated before replay"
    )
    assert audit["scope"].startswith("Downloaded market data only")
    assert audit["validation"]["transactional_staging"] is True
    assert audit["validation"]["incremental_window_no_future_dates"] is True

    ns = p.namespace(source.read_text(encoding="utf-8-sig"))
    models = [
        p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[key]))))
        for key in ["_EMBEDDED_MODEL_B64", "_EMBEDDED_STOP_MODEL_B64"]
    ]

    print(f"AUDIT PASS {audit_path} target={end.date()}", flush=True)
    print("Computing live-snapshot features without retraining", flush=True)
    ds, panels, meta = p.dataset(p.DATA, "2025-12-20", str(end.date()))
    ds = ds[ds.symbol.isin(models[0]["universe"])].copy()
    ds["p"] = ns["_batch_probabilities"](
        models[0], ds[p.F].to_numpy()
    )
    ds["stop"] = ns["_batch_probabilities"](
        models[1], ds[p.F].to_numpy()
    )
    ds["score"] = ds.p - 0.22 * ds.stop
    eligible = ds[(ds.p >= 0.63) & (ds.stop <= 0.50)].sort_values(
        ["date", "score", "symbol"], ascending=[True, False, True]
    )
    candidates = {
        date: list(group.head(8).symbol)
        for date, group in eligible.groupby("date")
    }

    calendar_path = p.DATA / "metadata" / f"trade_calendar_{end:%Y%m%d}.csv"
    if not calendar_path.exists():
        raise FileNotFoundError(calendar_path)
    calendar = pd.read_csv(calendar_path)
    dates = pd.DatetimeIndex(
        pd.to_datetime(
            calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]
        )
    )
    dates = dates[(dates >= "2025-12-20") & (dates <= end)]
    if not len(dates) or dates[-1] != end:
        raise AssertionError("Latest audited date is absent from trading calendar")

    e.OUT = out
    e.END = end
    e.CASH = INITIAL_CASH
    shutil.copy2(HERE / "data/corporate_actions.json", out / "corporate_actions.json")
    action_map = e.actions([])
    ns["_exit_action"] = e.old_exit
    models[0]["max_positions"] = 14

    metrics, curve, trades, differences = e.run_starts(
        (ns, models, dates, panels, candidates, meta, set()),
        action_map,
        REQUESTED_START,
    )
    metrics.update(
        requested_start=REQUESTED_START,
        initial_cash=INITIAL_CASH,
        fees=float(trades.fee.fillna(0).sum()) if "fee" in trades else 0.0,
    )
    assert curve.cash.min() >= -0.01
    if not trades.empty:
        assert trades.loc[trades.side == "BUY", "qty"].ge(200).all()

    p.save(out / "metrics.json", metrics)
    curve.to_parquet(out / "daily_equity.parquet", index=False)
    trades.to_parquet(out / "trades.parquet", index=False)
    p.save(out / "reference_price_differences.json", differences)
    p.save(
        out / "input_manifest.json",
        {
            "strategy": "科创基准1",
            "requested_start": REQUESTED_START,
            "actual_start": metrics["start"],
            "end": str(end.date()),
            "initial_cash": INITIAL_CASH,
            "market_audit": str(audit_path.relative_to(ROOT)),
            "market_audit_sha256": p.sha(audit_path),
            "calendar": str(calendar_path.relative_to(ROOT)),
            "calendar_sha256": p.sha(calendar_path),
            "platform_source": str(source.relative_to(ROOT)),
            "platform_sha256": p.sha(source),
            "model_retrained": False,
            "strategy_parameters_changed": False,
            "frozen_baseline_replaced": False,
        },
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
