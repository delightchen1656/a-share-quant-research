from __future__ import annotations

import ast
import base64
import importlib.util
import json
import sys
import types
import zlib
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FILES = {
    4: HERE / "supermind_strategy4_temperature_attack_single.py",
    5: HERE / "supermind_strategy5_rising_defense_single.py",
}


def load(number: int):
    sys.modules.setdefault("mindgo_api", types.ModuleType("mindgo_api"))
    spec = importlib.util.spec_from_file_location(f"strategy{number}", FILES[number])
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def local_frames(symbols):
    folder = ROOT / "evening_accumulation" / "data" / "classified" / "SH" / "star" / "qfq"
    frames = {}
    for symbol in symbols:
        path = folder / f"{symbol}.parquet"
        if not path.exists():
            continue
        x = pd.read_parquet(path, columns=["date", "close", "amount", "isST"])
        x["date"] = pd.to_datetime(x.date)
        x = x[x.date <= "2026-07-31"].tail(263).set_index("date")
        x = x.rename(columns={"amount": "turnover", "isST": "is_st"})
        frames[symbol] = x
    return frames


result = {}
mapping_csv = pd.read_csv(ROOT / "star_industry_rotation" / "industry_map.csv")
expected = dict(zip(mapping_csv.symbol.astype(str), mapping_csv.industry.astype(str)))
for number, path in FILES.items():
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    module = load(number)
    embedded = json.loads(zlib.decompress(base64.b64decode(module._INDUSTRY_MAP_B64)).decode("utf-8"))
    assert embedded == expected
    assert module._TEMPERATURE_STRATEGY == number
    assert 'history(batch, fields, 263, "1d"' in text
    assert "import os" not in text
    assert "getattr(" not in text
    members = {}
    for symbol, industry in embedded.items():
        members.setdefault(industry, []).append(symbol)
    module.g = types.SimpleNamespace(industry_map=embedded, industry_members=members)
    temperatures = module._industry_temperature(local_frames(embedded))
    print("strategy", number, "temperature industries", len(temperatures))
    assert len(temperatures) >= 15
    assert all(0 <= x["heat"] <= 100 and 0 <= x["breadth"] <= 100 for x in temperatures.values())
    # Rule boundary checks independent of market data.
    symbol = next(s for s, ind in embedded.items() if ind in temperatures)
    ind = embedded[symbol]
    if number == 4:
        assert module._temperature_allowed(symbol, {ind: {"heat": 84, "delta": -1, "breadth": 50}}, .20)
        assert not module._temperature_allowed(symbol, {ind: {"heat": 85, "delta": -1, "breadth": 50}}, .20)
        assert not module._temperature_allowed(symbol, {ind: {"heat": 50, "delta": -6, "breadth": 50}}, .70)
    else:
        assert module._temperature_allowed(symbol, {ind: {"heat": 40, "delta": 1, "breadth": 20}}, .20)
        assert module._temperature_allowed(symbol, {ind: {"heat": 65, "delta": -3, "breadth": 55}}, .20)
        assert not module._temperature_allowed(symbol, {ind: {"heat": 64, "delta": -3, "breadth": 55}}, .20)
    result[number] = {"bytes": path.stat().st_size, "mapping": len(embedded), "temperature_industries": len(temperatures)}

(HERE / "test_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
