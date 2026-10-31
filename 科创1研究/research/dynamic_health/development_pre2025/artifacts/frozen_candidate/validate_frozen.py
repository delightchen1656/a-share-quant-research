from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from engine import add_matured_event_outcomes, canonical_sha256, metrics, score_candidates, simulate


def load_adapter(path: Path):
    spec = importlib.util.spec_from_file_location("dynamic_health_adapter", path)
    if spec is None or spec.loader is None: raise ImportError(path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if not hasattr(module, "load_panels"): raise AttributeError("adapter must define load_panels(start_date, end_date) -> (raw, qfq)")
    return module


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the immutable dynamic-health candidate on an independently supplied data adapter.")
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(); root = Path(__file__).resolve().parent
    cfg = json.loads((root / "candidate.json").read_text(encoding="utf-8"))
    history_start = cfg["history_start"]
    adapter = load_adapter(args.adapter.resolve()); raw, qfq = adapter.load_panels(cfg["data_start"], args.end)
    raw, qfq = raw.copy(), qfq.copy(); raw["date"] = pd.to_datetime(raw.date); qfq["date"] = pd.to_datetime(qfq.date)
    scored, meta = score_candidates(qfq, root)
    scored = add_matured_event_outcomes(scored, qfq, meta["event_horizon"], meta["event_target"])
    eq, tr, decisions = simulate(raw, scored, cfg["event_threshold"], cfg["scheme"], history_start, args.end)
    eq = eq[pd.to_datetime(eq.date) >= pd.Timestamp(args.start)].reset_index(drop=True)
    tr = tr[pd.to_datetime(tr.exit_date) >= pd.Timestamp(args.start)].reset_index(drop=True) if len(tr) else tr
    decisions = decisions[pd.to_datetime(decisions.date) >= pd.Timestamp(args.start)].reset_index(drop=True)
    args.output.mkdir(parents=True, exist_ok=False)
    eq.to_csv(args.output / "equity.csv", index=False); tr.to_csv(args.output / "trades.csv", index=False); decisions.to_csv(args.output / "decisions.csv", index=False)
    result = {"candidate_config_sha256": canonical_sha256(cfg), "period": [args.start, args.end], "metrics": metrics(eq, tr)}
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

