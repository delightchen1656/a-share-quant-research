"""Embed the generated compressed risk model in the V4 SuperMind strategy."""
from pathlib import Path


HERE = Path(__file__).resolve().parent
target = HERE / "supermind_event_risk_control_v4_single.py"
encoded = (HERE / "market_risk_model.b64").read_text(encoding="ascii").strip()
chunks = [encoded[i:i + 100] for i in range(0, len(encoded), 100)]
literal = "_EMBEDDED_RISK_MODEL_B64 = (\n" + "\n".join(
    '    "' + chunk + '"' for chunk in chunks
) + "\n)"
source = target.read_text(encoding="utf-8")
marker = '_EMBEDDED_RISK_MODEL_B64 = ""'
if source.count(marker) != 1:
    raise RuntimeError("risk model placeholder missing or duplicated")
target.write_text(source.replace(marker, literal), encoding="utf-8")
print(target, len(encoded))
