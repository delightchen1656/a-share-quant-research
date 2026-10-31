"""Add audited identity metadata without rewriting any registered Kline/industry input."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "inputs_pre2025/security_identity_v1"
LINK_KNOWN = pd.Timestamp("2018-04-28")  # conservative: day after issuer's actual-change confirmation
CHANGE = pd.Timestamp("2018-02-28")
CUTOFF = pd.Timestamp("2024-12-31")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(symbol, day):
    if symbol in {"601313.SH", "601360.SH"} and pd.Timestamp(day) >= LINK_KNOWN:
        return "issuer_601313_601360"
    return symbol


def membership(day):
    day = pd.Timestamp(day)
    if day > CUTOFF:
        raise ValueError("After research boundary.")
    frame = pd.read_parquet(ROOT / "inputs_pre2025/industry_official_v1/membership_publication_history.parquet")
    frame = frame.loc[frame.knowledge_start.le(day)]
    frame = frame.loc[frame.knowledge_start.eq(frame.knowledge_start.max())].copy()
    frame["entity_join_key"] = frame.symbol.map(lambda symbol: key(symbol, day))
    if frame.entity_join_key.duplicated().any():
        raise RuntimeError("Multiple industry rows resolve to one legal issuer; resolve explicitly.")
    return frame


def main():
    evidence = json.loads((ROOT / "audits/semantics_v1/security_identity_audit.json").read_text(encoding="utf-8"))
    sources = []
    for source in evidence["issuer_notices"]:
        path = ROOT / source["document"]
        if digest(path) != source["sha256"]:
            raise RuntimeError("Identity source changed.")
        sources.append({"file": source["document"], "sha256": source["sha256"],
                        "published_date": source["published_date"], "source_url": source["url"]})
    links = pd.DataFrame([{
        "old_symbol": "601313.SH", "new_symbol": "601360.SH", "storage_symbol": "601360.SH",
        "entity_join_key": "issuer_601313_601360", "effective_date": CHANGE,
        "announced_date": pd.Timestamp("2018-02-13"), "actual_change_confirmation_date": pd.Timestamp("2018-04-27"),
        "asof_join_knowledge_start": LINK_KNOWN,
        "scope": "identifier_metadata_only_never_a_model_feature",
        "pre_confirmation_policy": "do_not_link_old_industry_code_to_retrospectively_named_storage_file",
    }])
    trade_codes = pd.DataFrame([
        {"storage_symbol": "601360.SH", "historical_trading_symbol": "601313.SH", "valid_from": pd.Timestamp("2018-01-02"),
         "valid_to_exclusive": CHANGE, "retrospective_history_only": True},
        {"storage_symbol": "601360.SH", "historical_trading_symbol": "601360.SH", "valid_from": CHANGE,
         "valid_to_exclusive": CUTOFF + pd.Timedelta(days=1), "retrospective_history_only": True},
    ])
    exceptions = {
        "000033.SZ": {"event_date": "2017-07-07", "research_period_relation": "before_2018_start", "not_a_future_delisting_filter": True},
        "000916.SZ": {"event_date": "2017-12-25", "research_period_relation": "before_2018_start", "merger_is_not_a_one_to_one_symbol_alias": True},
    }
    checks = []
    for day in ["2018-04-27", "2018-04-28", "2018-05-21", "2018-05-22"]:
        frame = membership(day)
        k = key("601360.SH", day)
        selected = frame.loc[frame.entity_join_key.eq(k)]
        linked = len(selected) == 1
        if pd.Timestamp(day) < LINK_KNOWN:
            assert key("601313.SH", day) != k
        else:
            assert key("601313.SH", day) == k
            assert linked
        checks.append({"day": day, "join_key": k, "mapped_industry_row_found": linked,
                       "source_symbol": selected.symbol.iloc[0] if linked else None,
                       "source_publication_date": selected.published_date.iloc[0] if linked else None})
    TARGET.mkdir(parents=True, exist_ok=True)
    paths = [TARGET / "identity_links.parquet", TARGET / "historical_trading_codes.parquet"]
    for frame, path in zip([links, trade_codes], paths):
        if not path.exists():
            frame.to_parquet(path, index=False)
        else:
            pd.testing.assert_frame_equal(pd.read_parquet(path), frame)
    manifest = {"cutoff": str(CUTOFF.date()), "source_evidence": sources,
                "files": [{"file": p.name, "sha256": digest(p)} for p in paths],
                "knowledge_policy": "Conservative confirmation-date gating; no pre-confirmation as-of industry repair.",
                "scope": "audited_exception_sidecar_only_not_full_security_master",
                "original_kline_and_industry_inputs_unchanged": True}
    p = TARGET / "manifest.json"
    if p.exists() and json.loads(p.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("Identity sidecar version differs; create new version.")
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    audit = {"sidecar_created": True, "boundary_checks": checks, "out_of_period_publication_exceptions": exceptions,
             "asof_industry_join_repair_verified_from": str(LINK_KNOWN.date()),
             "frozen_original_inputs_modified": False, "complete_historical_security_master": False,
             "future_model_features_must_exclude_identity_metadata": True}
    (ROOT / "audits/security_identity_sidecar.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sidecar_created": True, "asof_boundary_checks": len(checks), "original_inputs_modified": False}))


if __name__ == "__main__":
    main()
