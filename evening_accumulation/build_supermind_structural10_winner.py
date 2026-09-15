"""Build the SuperMind single-file candidate for the structural-10 winner."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "baselines/baseline_2/platform/supermind_baseline_1_2_stop_filter_single.py"
TARGET_DIR = ROOT.parent / "archive/optimization_studies/baseline_1-2_structural10_20260910/platform"
TARGET = TARGET_DIR / "supermind_high_attack_adaptive_expiry_v1.py"


text = SOURCE.read_text(encoding="utf-8")

text = text.replace(
    "    g.model = _load_model()\n",
    "    g.model = _load_model()\n"
    "    # Structural-10 research winner: use the high-attack signal cutoff.\n"
    "    g.model[\"threshold\"] = 0.63\n",
    1,
)
text = text.replace(
    'log.info("Baseline 1-2 Stop Filter initialized; daily frequency; cost=%s" % COST_SCENARIO)',
    'log.info("High Attack Adaptive Expiry v1 initialized; threshold=0.63; calendar expiry=30/60d; cost=%s" % COST_SCENARIO)',
    1,
)

old = '''        elif int(pos.position_days) >= 30:
            _submit(symbol, 0, "TIME")
'''
new = '''        else:
            # Match the local winner exactly: expiry is based on calendar days.
            # At day 30, positions still gaining at least 10% may run to day 60.
            entry_date = state.get("entry_date")
            if entry_date is not None:
                held_calendar_days = (now.date() - entry_date).days
            else:
                # A position restored after a strategy restart has no reliable
                # entry date. Fall back conservatively to platform holding days.
                held_calendar_days = int(pos.position_days)
            gain = price / state["entry"] - 1.0
            if held_calendar_days >= 60:
                _submit(symbol, 0, "TIME60")
            elif held_calendar_days >= 30 and gain < 0.10:
                _submit(symbol, 0, "TIME30")
'''
if old not in text:
    raise RuntimeError("Expected baseline expiry block was not found")
text = text.replace(old, new, 1)
text = text.replace(
    'elif action in ("STOP", "TPALL", "TIME"):',
    'elif action in ("STOP", "TPALL", "TIME30", "TIME60"):',
    1,
)

TARGET_DIR.mkdir(parents=True, exist_ok=True)
TARGET.write_text(text, encoding="utf-8")
print(TARGET)
print(TARGET.stat().st_size)
