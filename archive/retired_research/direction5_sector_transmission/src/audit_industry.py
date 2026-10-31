"""Render source-table samples, build publication-aware whitelist and audit coverage."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "_vendor"))
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STORE = (ROOT / CONFIG["industry_store"]).resolve() / "official_history_v1"
CUTOFF = pd.Timestamp(CONFIG["research_cutoff"])
if CUTOFF > pd.Timestamp("2024-12-31"):
    raise RuntimeError("Research date boundary cannot be widened by config alone.")


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render():
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    records = json.loads((STORE / "sources.json").read_text(encoding="utf-8"))
    output = ROOT / "audits/pdf_preview"
    output.mkdir(parents=True, exist_ok=True)
    cell_w, cell_h = 440, 650
    sheet = Image.new("RGB", (cell_w * 3, cell_h * ((len(records) + 2) // 3)), "#dddddd")
    draw = ImageDraw.Draw(sheet)
    selected = {"ae4789d5c5d5", "73e89f7cc994", "adc5a6637835", "9c8eab91dc36", "f254e1214655"}
    for index, record in enumerate(records):
        doc = pdfium.PdfDocument(record["attachment_file"])
        page = doc[0]
        image = page.render(scale=0.75).to_pil().convert("RGB")
        if record["id"] in selected:
            image.save(output / f"{record['id']}_page1.png")
            if len(doc) > 1:
                doc[1].render(scale=1.2).to_pil().save(output / f"{record['id']}_page2.png")
        image.thumbnail((cell_w - 12, cell_h - 40))
        x, y = index % 3 * cell_w, index // 3 * cell_h
        sheet.paste(image, (x + 6, y + 30))
        draw.text((x + 8, y + 6), f"{record['id']} published {record['published_date']}", fill="black")
        doc.close()
    path = output / "all_first_pages.png"
    sheet.save(path)
    print(str(path))


def membership_for_date(frame, day):
    """Whole-publication as-of join; never fill an absent stock from an older version."""
    if pd.Timestamp(day) > CUTOFF:
        raise ValueError("As-of query exceeds this research snapshot's date boundary.")
    available = frame.loc[frame["knowledge_start"] <= pd.Timestamp(day)]
    if available.empty:
        return available
    latest = available["knowledge_start"].max()
    return available.loc[available["knowledge_start"] == latest]


def promote():
    visual = json.loads((ROOT / "audits/industry_visual_review.json").read_text(encoding="utf-8"))
    if not visual.get("passed"):
        raise RuntimeError("Visual sample review has not passed.")
    sources = json.loads((STORE / "sources.json").read_text(encoding="utf-8"))
    audits = json.loads((STORE / "parse_audit.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in sources}
    if {r["id"] for r in audits} != set(by_id):
        raise RuntimeError("Not all discovered sources have parse audits.")
    frames, manifest_files, name_variants = [], [], []
    for audit in audits:
        source = by_id[audit["id"]]
        folder = Path(source["attachment_file"]).parent
        csv = folder / "membership.csv"
        if not audit.get("text_table_codes_match"):
            raise RuntimeError("Source text/table reconciliation failed.")
        if sha(Path(source["attachment_file"])) != source["attachment_sha256"] or sha(csv) != audit["membership_sha256"]:
            raise RuntimeError("Official source or extracted table changed.")
        df = pd.read_csv(csv, dtype=str)
        if df["stock_code"].duplicated().any():
            raise RuntimeError("Duplicate stock code in publication.")
        # Some historical PDFs truncate a repeated name at a page break or
        # contain overlapping duplicate text. Preserve extraction verbatim and
        # use a within-publication display label; NEVER alter membership codes.
        df["industry_name_raw"] = df["industry_name"]
        canonical = {}
        for code, group in df.groupby("industry_code", sort=False):
            counts = group["industry_name"].value_counts()
            names = counts.index.tolist()
            if not names:
                raise RuntimeError("No name for industry code anywhere in this publication.")
            complete = [name for name in names if all(name.startswith(other) for other in names)]
            chosen = complete[0] if complete else names[0]
            canonical[code] = chosen
            if len(names) > 1 or group["industry_name"].isna().any():
                name_variants.append({"source_id": source["id"], "industry_code": code,
                                      "source_variants": counts.to_dict(), "display_name": chosen,
                                      "missing_source_name_rows": int(group["industry_name"].isna().sum()),
                                      "policy": "within-document complete-prefix name, otherwise modal source name; codes unchanged"})
        df["industry_name"] = df["industry_code"].map(canonical)
        if not df["industry_code"].str.fullmatch(r"[A-S]\d{2}").all():
            raise RuntimeError("Invalid industry code.")
        if not df["published_date"].eq(source["published_date"]).all():
            raise RuntimeError("Membership/source publication dates disagree.")
        df["knowledge_start"] = pd.to_datetime(df["earliest_usable_date"])
        if not (df["knowledge_start"] > pd.to_datetime(df["published_date"])).all():
            raise RuntimeError("Industry information was made usable too early.")
        if pd.to_datetime(df["published_date"]).max() > CUTOFF:
            raise RuntimeError("Publication beyond research boundary.")
        stock = df["stock_code"]
        scope = stock.str.match(r"^(?:60|68|00|30)\d{4}$")
        df = df.loc[scope].copy()
        df["symbol"] = df["stock_code"] + df["stock_code"].map(lambda x: ".SH" if x.startswith(("60", "68")) else ".SZ")
        frames.append(df)
        manifest_files.append({"source_id": source["id"], "title": source["title"],
                               "published_date": source["published_date"], "source_url": source["page_url"],
                               "attachment_url": source["attachment_url"],
                               "attachment_sha256": source["attachment_sha256"], "membership_sha256": audit["membership_sha256"]})
    history = pd.concat(frames, ignore_index=True).sort_values(["knowledge_start", "symbol"])
    dates = sorted(history["knowledge_start"].unique())
    if len(dates) != len(sources):
        raise RuntimeError("Multiple whole-market publications share one knowledge date; resolve precedence explicitly.")
    next_dates = {d: (dates[i + 1] if i + 1 < len(dates) else CUTOFF + pd.Timedelta(days=1)) for i, d in enumerate(dates)}
    history["knowledge_end_exclusive"] = history["knowledge_start"].map(next_dates)
    target = ROOT / "inputs_pre2025/industry_official_v1"
    if target.exists():
        raise RuntimeError("Industry whitelist already exists; do not overwrite.")
    target.mkdir(parents=True, exist_ok=False)
    path = target / "membership_publication_history.parquet"
    history.to_parquet(path, index=False)
    manifest = {"boundary_version": CONFIG["boundary_version"], "cutoff": str(CUTOFF.date()),
                "file": path.name, "sha256": sha(path), "rows": len(history), "publications": manifest_files,
                "semantics": "last officially published membership known after publication; not exact effective-date history",
                "source_staleness": "explicit age diagnostics required; never silently fill a missing stock from an older publication",
                "sector_taxonomy": "industry major class; schema transitions are preserved and must be assessed before factor pooling"}
    save(target / "manifest.json", manifest)
    save(ROOT / "audits/industry_display_name_variants.json", name_variants)
    print(json.dumps({"promoted_publications": len(sources), "membership_rows": len(history)}, ensure_ascii=True))


def coverage():
    source = ROOT / "inputs_pre2025/industry_official_v1"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    path = source / manifest["file"]
    if sha(path) != manifest["sha256"]:
        raise RuntimeError("Industry whitelist hash mismatch.")
    history = pd.read_parquet(path)
    kline_root = ROOT / CONFIG["snapshot"]
    kline = json.loads((kline_root / "manifest.json").read_text(encoding="utf-8"))
    available_symbols = {r["symbol"] for r in kline["files"]}

    def summarize(record):
        df = pq.read_table(kline_root / record["snapshot_file"], columns=["date", "tradestatus"]).to_pandas()
        df = df.loc[df["tradestatus"].astype(str).eq("1")]
        return record["symbol"], df["date"].tolist()

    date_symbols = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for symbol, days in pool.map(summarize, kline["files"]):
            for day in days:
                date_symbols.setdefault(day, set()).add(symbol)
    # Quarterly snapshots describe input availability only, not model performance.
    all_days = pd.Series(sorted(date_symbols), dtype="datetime64[ns]")
    quarter_ends = all_days.groupby(all_days.dt.to_period("Q")).max()
    rows = []
    for day in quarter_ends:
        mapping = membership_for_date(history, day)
        members = set(mapping["symbol"])
        mainboard_members = {s for s in members if s.startswith(("60", "00"))}
        active = date_symbols[day]
        published = mapping["published_date"].iloc[0] if len(mapping) else None
        rows.append({"date": str(day.date()), "active_kline_symbols": len(active),
                     "classified_active_symbols": len(active & members), "unclassified_active_symbols": len(active - members),
                     "coverage_ratio": len(active & members) / len(active) if active else None,
                     "last_publication_date": published,
                     "publication_age_calendar_days": (day - pd.Timestamp(published)).days if published else None,
                     "official_scope_members_without_any_kline_file": len(members - available_symbols),
                     "official_mainboard_members_without_any_kline_file": len(mainboard_members - available_symbols),
                     "other_board_members_without_any_kline_file": len((members - mainboard_members) - available_symbols)})
    pd.DataFrame(rows).to_csv(ROOT / "audits/industry_kline_coverage_quarterly.csv", index=False, encoding="utf-8-sig")
    # Causality checks across every publication boundary, including a stock that disappears.
    for start in sorted(history["knowledge_start"].unique()):
        before = membership_for_date(history, pd.Timestamp(start) - pd.Timedelta(days=1))
        after = membership_for_date(history, start)
        if len(before) and not (before["knowledge_start"] < start).all():
            raise RuntimeError("Future industry publication leaked into prior day.")
        if not after["knowledge_start"].eq(start).all():
            raise RuntimeError("As-of publication selection failed.")
    registration_path = ROOT / "audits/protocol_v1_registration.json"
    design_registered = False
    if registration_path.exists():
        registration = json.loads(registration_path.read_text(encoding="utf-8"))
        design_registered = (
            sha(ROOT / "research_protocol_v1.json") == registration["protocol_sha256"]
            and sha(ROOT / "RESEARCH_SPEC_V1.md") == registration["readable_spec_sha256"]
            and all(sha(ROOT / item["path"]) == item["sha256"] for item in registration["input_manifests"])
        )
    outstanding = ["historical_kline_universe_incomplete_or_unverified", "volume_units_not_yet_documented",
                   "corporate_action_and_execution_return_labels_not_audited",
                   "industry_transition_warmup_to_be_implemented_with_registered_factor_windows"]
    if not design_registered:
        outstanding.extend(["research_objective_and_time_split_not_frozen",
                            "industry_staleness_and_taxonomy_transition_policy_not_frozen"])
    semantics_path = ROOT / CONFIG.get("data_semantics_audit", "audits/stage8_data_audit.json")
    semantics = json.loads(semantics_path.read_text(encoding="utf-8")) if semantics_path.exists() else {}
    if semantics.get("unit_and_quote_formula_checks_passed"):
        outstanding.remove("volume_units_not_yet_documented")
    outstanding.extend(semantics.get("outstanding", []))
    outstanding = list(dict.fromkeys(outstanding))
    missing = history.loc[history["symbol"].str.startswith(("60", "00")) & ~history["symbol"].isin(available_symbols),
                          ["symbol", "source_id", "published_date", "knowledge_start", "knowledge_end_exclusive"]].copy()
    for column in ("knowledge_start", "knowledge_end_exclusive"):
        missing[column] = missing[column].dt.strftime("%Y-%m-%d")
    save(ROOT / "audits/historical_mainboard_kline_exceptions.json", {
        "source_membership_without_kline": missing.to_dict("records"),
        "interpretation": "An industry publication lists the security but no authorized Kline file exists. This alone does not establish listing, tradability, or delisting status at a later date.",
        "policy": "Keep exception visible; never synthesize prices or use later delisting information to remove historical names."
    })
    report = {"cutoff": str(CUTOFF.date()), "official_publications": len(manifest["publications"]),
              "publication_boundary_checks_passed": True, "quarterly_coverage": rows,
              "research_design_registered_and_hash_verified": design_registered,
              "data_semantics_audit_completed": semantics.get("audit_execution_completed", False),
              "data_semantics_audit_path": str(semantics_path.relative_to(ROOT)),
              "stage8_fully_passed": semantics.get("stage8_fully_passed", False),
              "unit_and_quote_formula_checks_passed": semantics.get("unit_and_quote_formula_checks_passed", False),
              "model_experiments_enabled": False,
              "outstanding": outstanding}
    save(ROOT / "audits/data_readiness.json", report)
    print(json.dumps({"official_publications": report["official_publications"],
                      "quarterly_checks": len(rows), "coverage_min": min(r["coverage_ratio"] for r in rows),
                      "coverage_max": max(r["coverage_ratio"] for r in rows), "model_experiments_enabled": False}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["render", "promote", "coverage"])
    args = parser.parse_args()
    {"render": render, "promote": promote, "coverage": coverage}[args.command]()
