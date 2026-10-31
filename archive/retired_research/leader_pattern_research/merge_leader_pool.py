"""Deduplicate by stock code, publish a frozen pool, and relabel the existing viewer."""
from pathlib import Path
import json,re,shutil
import pandas as pd
from build_market_patterns import build,dump,sha,CURRENT
from leader_pool import CURRENT as POOL_CURRENT,membership
from refresh_mainboard_viewer import lock

HERE=Path(__file__).resolve().parent
OUT=HERE/'leader_pools/holdout_restricted/merged_20261027_v1'
MAIN=r'^(600|601|603|605|000|001|002|003)\d{3}$'

def main():
    assert not OUT.exists(),'Preserve existing union version'
    OUT.mkdir(parents=True)
    original_path=HERE/'holdout_restricted/patterns_v1/frozen_pool_185.parquet'
    ths_path=HERE/'ths_f10_leaders/holdout_restricted/snapshot_20261027/lists/all_leaders.parquet'
    original=pd.read_parquet(original_path);ths=pd.read_parquet(ths_path)
    assert original.code.is_unique and ths.code.is_unique and len(original)==185 and len(ths)==520
    oa=original.set_index('code').to_dict('index');ta=ths.set_index('code').to_dict('index')
    rows=[]
    for code in sorted(set(oa)|set(ta)):
        a=oa.get(code);b=ta.get(code);source='原龙头+同花顺' if a and b else '原龙头' if a else '同花顺F10'
        rows.append(dict(code=code,name=b['name'] if b else a['name'],
            is_original_leader=a is not None,is_ths_leader=b is not None,leader_source=source,
            is_mainboard=bool(re.fullmatch(MAIN,code)),original_name=a['name'] if a else None,
            ths_name=b['name'] if b else None,original_sector=a['screen_best_board'] if a else None,
            ths_concepts=list(b['concepts']) if b else []))
    merged=pd.DataFrame(rows);mainboard=merged[merged.is_mainboard].copy()
    assert len(merged)==687 and len(mainboard)==510
    merged.to_parquet(OUT/'all_leaders.parquet',index=False)
    mainboard.to_parquet(OUT/'mainboard_leaders.parquet',index=False)
    manifest=dict(version='original185_union_thsF10_20261027_v1',snapshot_date='2026-10-27',
        all_path=str((OUT/'all_leaders.parquet').resolve()),all_sha256=sha(OUT/'all_leaders.parquet'),
        mainboard_path=str((OUT/'mainboard_leaders.parquet').resolve()),mainboard_sha256=sha(OUT/'mainboard_leaders.parquet'),
        original=185,ths=520,overlap=18,total=687,mainboard_original=118,mainboard_ths=405,mainboard_overlap=13,mainboard_total=510,
        sources=[dict(path=str(original_path),sha256=sha(original_path)),dict(path=str(ths_path),sha256=sha(ths_path))],
        scope_rule='Union by stock code; sources preserved. Viewer uses only main-board subset.',
        temporal_caution='Current snapshot displayed retrospectively; not historical point-in-time leader membership.')
    dump(OUT/'manifest.json',manifest)
    dump(POOL_CURRENT,dict(manifest=str((OUT/'manifest.json').resolve()),manifest_sha256=sha(OUT/'manifest.json')))
    for name,frame in [('合并龙头_全市场687只.txt',merged),('合并龙头_沪深主板510只.txt',mainboard)]:
        lines=[name[:-4],'原龙头名单与同花顺F10指定列取并集，股票代码去重，采集日快照2026-10-27。',
            '来源保留：原龙头、同花顺F10、原龙头+同花顺。软件仅接入沪深主板子集；当前名单不能作为历史当时归属。','',
            '代码  名称  来源  同花顺概念']
        for r in frame.itertuples():lines.append(f"{r.code}  {r.name}  {r.leader_source}  {'、'.join(r.ths_concepts)}")
        (OUT/name).write_text('\n'.join(lines),encoding='utf-8')
    with lock('REFRESH.lock'):
        previous=json.loads(CURRENT.read_text(encoding='utf-8'));before_sha=sha(CURRENT)
        old_manifest=json.loads(Path(previous['manifest']).read_text(encoding='utf-8'))
        old_events=pd.read_parquet(previous['events']);universe=pd.read_parquet(previous['universe'])
        lookup=merged.set_index('code').to_dict('index')
        labels=pd.DataFrame([membership(c,lookup) for c in universe.code])
        for col in labels:universe[col]=labels[col].to_numpy()
        assert universe.is_leader.sum()==510 and set(mainboard.code).issubset(set(universe.code))
        base=HERE/'market_wide/holdout_restricted/mainboard_union_20261027_v1'
        base.mkdir();(base/'inputs_daily').mkdir()
        universe.to_parquet(base/'universe.parquet',index=False)
        shutil.copy2(previous['calendar'],base/'exchange_sessions.csv')
        new_manifest=dict(old_manifest,universe_sha256=sha(base/'universe.parquet'),
            leader_pool_manifest=str((OUT/'manifest.json').resolve()),leader_pool_manifest_sha256=sha(OUT/'manifest.json'),
            source_manifest_sha256=sha(previous['manifest']),quote_snapshots_reused_unchanged=True)
        dump(base/'inputs_daily/manifest.json',new_manifest)
        bundle=build(base,publish=False)
        new_events=pd.read_parquet(bundle['events'])
        unchanged=[c for c in old_events if c!='is_leader']
        pd.testing.assert_frame_equal(old_events[unchanged].reset_index(drop=True),new_events[unchanged].reset_index(drop=True),check_dtype=False)
        assert len(new_events)==1440 and set(new_events.event_id)==set(old_events.event_id)
        assert sha(CURRENT)==before_sha,'Concurrent viewer publication; re-evaluate latest input before applying union'
        dump(CURRENT,bundle)
        audit=dict(pool=manifest,viewer_generation=bundle['generation'],old_generation=previous['generation'],
            stocks=len(universe),starred_stocks=int(universe.is_leader.sum()),all_box_signals=len(new_events),
            starred_box_signals=int(new_events.is_leader.sum()),box_signals_and_all_price_metrics_unchanged=True,
            quote_sources_unchanged=True,software_scope='SH_SZ_MAIN_BOARD_ONLY')
        dump(OUT/'VIEWER_APPLY_AUDIT.json',audit)
    print(json.dumps({k:audit[k] for k in ['starred_stocks','all_box_signals','starred_box_signals','box_signals_and_all_price_metrics_unchanged']},ensure_ascii=False))

if __name__=='__main__':main()
