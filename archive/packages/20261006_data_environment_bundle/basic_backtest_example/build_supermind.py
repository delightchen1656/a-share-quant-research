"""Embed 默认策略.py into a standalone SuperMind file."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = "# FACTOR_SOURCE_INSERTED_HERE"
factor = (HERE / "默认策略.py").read_text(encoding="utf-8")
template = (HERE / "supermind_template.py").read_text(encoding="utf-8")
if TOKEN not in template:
    raise RuntimeError("template insertion marker is missing")
output = HERE / "默认SuperMind策略.py"
output.write_text(template.replace(TOKEN, factor), encoding="utf-8")
compile(output.read_text(encoding="utf-8"), str(output), "exec")
print(output)
