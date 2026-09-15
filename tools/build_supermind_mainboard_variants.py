"""Build Shanghai/Shenzhen Main Board variants of three frozen SuperMind files.

Only the security universe, board-specific trading rules, benchmark and the
industry membership map are migrated. Embedded prediction models and strategy
thresholds are intentionally left unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import zlib
from pathlib import Path

import baostock as bs
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CSV = ROOT / "evening_accumulation/data/metadata/universe.csv"
OUT = ROOT / "sh_sz_market_research" / "platform" / "supermind"
SOURCES = {
    "baseline_1_2": ROOT / "supermind_baselines/supermind_baseline_1_2_stop_filter.py",
    "baseline_2_2": ROOT / "supermind_baselines/supermind_baseline_2_2_rising_defense.py",
    "baseline_3_1": ROOT / "supermind_baselines/supermind_baseline_3_1_high_attack_adaptive_expiry_daily_120k_dynamic20.py",
}


def packed(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def mainboard_universe() -> list[str]:
    frame = pd.read_csv(UNIVERSE_CSV)
    return sorted(frame.loc[frame.board.eq("main"), "symbol"].astype(str).unique())


def industry_map(symbols: list[str]) -> dict[str, str]:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError("BaoStock login failed: " + login.error_msg)
    try:
        rs = bs.query_stock_industry()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if rs.error_code != "0":
            raise RuntimeError("BaoStock industry query failed: " + rs.error_msg)
    finally:
        bs.logout()
    frame = pd.DataFrame(rows, columns=rs.fields)
    allowed = set(symbols)
    result = {}
    for row in frame.itertuples(index=False):
        market, code = str(row.code).split(".")
        symbol = code + "." + market.upper()
        if symbol not in allowed:
            continue
        # The CSRC category code is stable even when a Windows console cannot
        # render the following Chinese description.
        match = re.match(r"([A-Z]\d{2})", str(row.industry).strip())
        result[symbol] = match.group(1) if match else "UNKNOWN"
    return result


def inject_common(text: str, universe_b64: str) -> str:
    marker = "import pandas as pd\n"
    addition = (
        marker
        + "\n\n_MAINBOARD_UNIVERSE_B64 = \"" + universe_b64 + "\"\n\n"
        + "def _load_mainboard_universe():\n"
        + "    raw = zlib.decompress(base64.b64decode(_MAINBOARD_UNIVERSE_B64.encode(\"ascii\")))\n"
        + "    return json.loads(raw.decode(\"utf-8\"))\n"
    )
    if marker not in text:
        raise ValueError("pandas import marker missing")
    text = text.replace(marker, addition, 1)
    init_marker = "    g.model = _load_model()\n"
    if init_marker not in text:
        raise ValueError("init model marker missing")
    text = text.replace(init_marker, init_marker + "    g.model[\"universe\"] = _load_mainboard_universe()\n", 1)
    text = text.replace('set_benchmark("000688.SH")', 'set_benchmark("000300.SH")')
    text = text.replace('float(x["quote_rate"].iloc[-1]) >= 19.5',
                        'float(x["quote_rate"].iloc[-1]) >= 9.5')
    text = text.replace("STAR orders require at least 200 shares", "Main Board buys require 100-share lots")
    text = text.replace("STAR Market 200-share minimum", "Main Board 100-share lot minimum")
    text = text.replace("price * 200 * 1.005", "price * 100 * 1.005")
    text = text.replace("target >= 200 and sell_amount >= 200", "target >= 100 and sell_amount >= 100")
    return text


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = mainboard_universe()
    sectors = industry_map(symbols)
    if len(symbols) < 3000 or len(sectors) < 2500:
        raise RuntimeError(f"unexpected coverage universe={len(symbols)} industries={len(sectors)}")
    universe_b64 = packed(symbols)
    industry_b64 = packed(sectors)

    for key, source in SOURCES.items():
        text = source.read_text(encoding="utf-8")
        text = inject_common(text, universe_b64)
        text = text.replace("STAR events", "Shanghai/Shenzhen Main Board events")
        text = text.replace("dynamic STAR sizing", "dynamic Main Board sizing")
        if key == "baseline_3_1":
            text = text.replace("MIN_STAR_SHARES = 200", "MIN_MAINBOARD_SHARES = 100")
            text = text.replace("MIN_STAR_SHARES", "MIN_MAINBOARD_SHARES")
            text = text.replace("MAX_POSITION_FRACTION_120K", "MAX_POSITION_FRACTION_SMALL_ACCOUNT")
            text = text.replace("High Attack Adaptive Expiry DAILY 120K DYNAMIC initialized",
                                "Main Board High Attack Adaptive Expiry DAILY initialized")
        if key == "baseline_2_2":
            old_marker = "_INDUSTRY_MAP_B64 = "
            start = text.find(old_marker)
            if start < 0:
                raise ValueError("industry map marker missing")
            line_end = text.find("\n", start)
            text = text[:start] + f'_INDUSTRY_MAP_B64 = "{industry_b64}"' + text[line_end:]
        target = OUT / f"supermind_mainboard_{key}.py"
        target.write_text(text, encoding="utf-8")

    generated = sorted(OUT.glob("supermind_mainboard_*.py"))
    metadata = {
        "created_at": "2026-09-12",
        "scope": "Shanghai and Shenzhen Main Boards, securities existing at 2026-07-31",
        "universe_count": len(symbols),
        "shanghai_count": sum(s.endswith(".SH") for s in symbols),
        "shenzhen_count": sum(s.endswith(".SZ") for s in symbols),
        "industry_mapped": len(sectors),
        "benchmark": "000300.SH",
        "buy_lot": 100,
        "regular_price_limit_filter": "quote_rate < 9.5%; live high_limit/low_limit still authoritative",
        "model_warning": "prediction and bear models remain STAR-trained; these are transfer-test files, not validated Main Board models",
        "sources": {k: str(v.relative_to(ROOT)) for k, v in SOURCES.items()},
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest().upper() for p in generated},
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
