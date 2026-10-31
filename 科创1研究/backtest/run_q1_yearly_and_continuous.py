"""Audit-only frozen-model replay for yearly and continuous Q1 starts.

Scopes:
1. Each calendar year independently, starting from its first trading day.
2. 2020 Q1 start through the latest transactionally committed trading day.
3. 2025 Q1 start through the same latest trading day.

The embedded models and trading rules are not retrained or changed.  Results
are written to a dated audit directory and do not replace the frozen parity
results ending on 2026-09-30.
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
INITIAL_CASH = 500000.0


def latest_committed_audit():
    for path in reversed(sorted((ROOT / "K线数据/更新备份与审计").glob("*/audit.json"))):
        audit = json.loads(path.read_text(encoding="utf-8"))
        if audit.get("status") != "ok":
            continue
        target = pd.Timestamp(audit["target"])
        active = pd.Timestamp(audit["validation"]["active_symbol_latest_date"])
        if target == active:
            return path, audit, target
    raise RuntimeError("No successful, internally consistent market-data audit")


def main():
    audit_path, audit, latest = latest_committed_audit()
    out = STAR / "results" / f"q1_yearly_continuous_to_{latest:%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)

    source = STAR / "supermind_kechuang_1.py"
    provenance = json.loads(
        (STAR / "research/provenance.json").read_text(encoding="utf-8")
    )
    assert p.sha(source) == provenance["platform_sha256"]
    assert audit["scope"].startswith("Downloaded market data only")
    assert audit["validation"]["transactional_staging"] is True
    assert audit["validation"]["incremental_window_no_future_dates"] is True

    calendar_path = p.DATA / "metadata" / f"trade_calendar_{latest:%Y%m%d}.csv"
    if not calendar_path.exists():
        raise FileNotFoundError(calendar_path)
    calendar = pd.read_csv(calendar_path)
    all_dates = pd.DatetimeIndex(
        pd.to_datetime(
            calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"]
        )
    )
    all_dates = all_dates[(all_dates >= "2019-12-20") & (all_dates <= latest)]
    assert len(all_dates) and all_dates[-1] == latest

    frozen_cutoff = pd.Timestamp("2026-09-30")
    snapshot = HERE / "data" / "snapshot_20260930"
    snapshot_manifest = json.loads(
        (snapshot / "manifest.json").read_text(encoding="utf-8")
    )
    assert all(
        p.sha(snapshot / relative) == item["sha256"]
        for relative, item in snapshot_manifest.items()
    )

    print(f"AUDIT PASS {audit_path} target={latest.date()}", flush=True)
    print("Computing frozen history plus audited incremental features", flush=True)
    ns = p.namespace(source.read_text(encoding="utf-8-sig"))
    models = [
        p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[key]))))
        for key in ["_EMBEDDED_MODEL_B64", "_EMBEDDED_STOP_MODEL_B64"]
    ]
    frozen_ds, frozen_panels, _ = p.dataset(
        snapshot, "2019-12-20", str(frozen_cutoff.date())
    )
    _, live_panels, meta = p.dataset(
        p.DATA, "2026-09-20", str(latest.date())
    )

    def score_candidates(frame):
        frame = frame[frame.symbol.isin(models[0]["universe"])].copy()
        frame["p"] = ns["_batch_probabilities"](
            models[0], frame[p.F].to_numpy()
        )
        frame["stop"] = ns["_batch_probabilities"](
            models[1], frame[p.F].to_numpy()
        )
        frame["score"] = frame.p - 0.22 * frame.stop
        eligible = frame[(frame.p >= 0.63) & (frame.stop <= 0.50)].sort_values(
            ["date", "score", "symbol"], ascending=[True, False, True]
        )
        return {
            date: list(group.head(8).symbol)
            for date, group in eligible.groupby("date")
        }

    candidates = score_candidates(frozen_ds[frozen_ds.date <= frozen_cutoff])

    # Reconstruct every post-freeze signal from the exact data state that
    # existed after that day's committed update.  The state after day D is the
    # transaction backup captured immediately before the next update.  This
    # avoids allowing a later ex-rights rebase to rewrite an earlier signal.
    audited = []
    for path in sorted((ROOT / "K线数据/更新备份与审计").glob("*/audit.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("status") != "ok":
            continue
        target = pd.Timestamp(item["target"])
        active = pd.Timestamp(item["validation"]["active_symbol_latest_date"])
        if target == active:
            audited.append((target, path, item))
    replay_inputs = {}
    signal_dates = all_dates[
        (all_dates > frozen_cutoff) & (all_dates < latest)
    ]
    for signal_date in signal_dates:
        later = [entry for entry in audited if entry[0] > signal_date]
        if not later:
            raise RuntimeError(f"No next-update backup for {signal_date.date()}")
        next_target, next_audit_path, _ = later[0]
        state = (
            next_audit_path.parent
            / "before_update"
            / "archive/legacy_layout/evening_accumulation"
            / "data"
        )
        if not (state / "qfq").exists() or not (state / "raw").exists():
            raise FileNotFoundError(state)
        point_ds, _, _ = p.dataset(
            state, str(signal_date.date()), str(signal_date.date())
        )
        day_candidates = score_candidates(
            point_ds[point_ds.date == signal_date]
        )
        candidates.update(day_candidates)
        replay_inputs[str(signal_date.date())] = {
            "state": str(state.relative_to(ROOT)),
            "captured_before_update": str(next_target.date()),
            "next_audit_sha256": p.sha(next_audit_path),
        }

    panels = {}
    for symbol in sorted(set(frozen_panels) | set(live_panels)):
        before = frozen_panels.get(symbol)
        after = live_panels.get(symbol)
        pieces = []
        if before is not None:
            pieces.append(before.loc[before.index <= frozen_cutoff])
        if after is not None:
            pieces.append(after.loc[after.index > frozen_cutoff])
        panels[symbol] = pd.concat(pieces).sort_index()

    e.OUT = out
    e.CASH = INITIAL_CASH
    shutil.copy2(HERE / "data/corporate_actions.json", out / "corporate_actions.json")
    action_map = e.actions([])
    ns["_exit_action"] = e.old_exit
    models[0]["max_positions"] = 14

    periods = []
    for year in range(2020, latest.year + 1):
        period_end = min(latest, pd.Timestamp(f"{year}-12-31"))
        periods.append((f"year_{year}_independent", f"{year}-01-01", period_end))
    periods.extend(
        [
            ("continuous_2020", "2020-01-01", latest),
            ("continuous_2025", "2025-01-01", latest),
        ]
    )

    rows = []
    for label, requested_start, period_end in periods:
        dates = all_dates[all_dates <= period_end]
        if not len(dates):
            raise AssertionError(f"No trading dates for {label}")
        e.END = dates[-1]
        metrics, curve, trades, differences = e.run_starts(
            (ns, models, dates, panels, candidates, meta, set()),
            action_map,
            requested_start,
        )
        metrics.update(
            label=label,
            requested_start=requested_start,
            initial_cash=INITIAL_CASH,
            fees=float(trades.fee.fillna(0).sum()) if "fee" in trades else 0.0,
        )
        assert curve.cash.min() >= -0.01
        if not trades.empty:
            assert trades.loc[trades.side == "BUY", "qty"].ge(200).all()
        dest = out / label
        dest.mkdir(exist_ok=True)
        p.save(dest / "metrics.json", metrics)
        curve.to_parquet(dest / "daily_equity.parquet", index=False)
        trades.to_parquet(dest / "trades.parquet", index=False)
        p.save(dest / "reference_price_differences.json", differences)
        rows.append(metrics)
        print(
            label,
            metrics["start"],
            metrics["end"],
            f"CAGR={metrics['cagr']:.4%}",
            f"RETURN={metrics['total_return']:.4%}",
            f"MDD={metrics['max_drawdown']:.4%}",
            f"SHARPE={metrics['sharpe_rf0']:.4f}",
            flush=True,
        )

    p.save(out / "summary.json", rows)
    reference = json.loads(
        (STAR / "research/reference_metrics.json").read_text(encoding="utf-8")
    )
    parity = {}
    for label, reference_start in [
        ("continuous_2020", "2020-01-01"),
        ("continuous_2025", "2025-01-01"),
    ]:
        reference_row = next(
            row for row in reference if row["start"] == reference_start
        )
        curve = pd.read_parquet(out / label / "daily_equity.parquet")
        trades = pd.read_parquet(out / label / "trades.parquet")
        cutoff_equity = float(
            curve.loc[curve.date == frozen_cutoff, "equity"].iloc[0]
        )
        cutoff_fees = float(
            trades.loc[trades.date <= frozen_cutoff, "fee"].fillna(0).sum()
        )
        assert cutoff_equity == reference_row["final_asset"]
        assert cutoff_fees == reference_row["fees"]
        parity[label] = {
            "cutoff": str(frozen_cutoff.date()),
            "equity": cutoff_equity,
            "reference_equity": reference_row["final_asset"],
            "fees": cutoff_fees,
            "reference_fees": reference_row["fees"],
            "exact_match": True,
        }
    p.save(out / "verification.json", parity)
    p.save(
        out / "input_manifest.json",
        {
            "strategy": "Kechuang Baseline 1",
            "scope": "yearly independent Q1 starts plus 2020/latest and 2025/latest",
            "latest_trading_day": str(latest.date()),
            "initial_cash_each_run": INITIAL_CASH,
            "market_audit": str(audit_path.relative_to(ROOT)),
            "market_audit_sha256": p.sha(audit_path),
            "calendar": str(calendar_path.relative_to(ROOT)),
            "calendar_sha256": p.sha(calendar_path),
            "frozen_snapshot": str(snapshot.relative_to(ROOT)),
            "frozen_cutoff": str(frozen_cutoff.date()),
            "post_freeze_signal_inputs": replay_inputs,
            "platform_source": str(source.relative_to(ROOT)),
            "platform_sha256": p.sha(source),
            "model_retrained": False,
            "strategy_parameters_changed": False,
            "frozen_baseline_replaced": False,
        },
    )


if __name__ == "__main__":
    main()
