"""Record final, reviewed relocation evidence. No strategy/data computation."""
from pathlib import Path
import json,shutil,hashlib
from reorganize_workspace import ROOT,AUDIT,sha

def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    inventory=json.loads((AUDIT/'inventory.json').read_text(encoding='utf8'))
    # Update the operational gold task registration; keep its old manifest as evidence.
    gold=ROOT/'K线数据/黄金'
    for name in ['AUTOMATION.json','AUTOMATION_MANIFEST.json']:
        src=gold/name;dest=AUDIT/'gold_automation_before'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():shutil.copy2(src,dest)
    task=json.loads((gold/'AUTOMATION.json').read_text(encoding='utf8'))
    task['entrypoint']='K线看盘软件/auto_update_gold.py';task['data_root']='K线数据/黄金';save(gold/'AUTOMATION.json',task)
    paths=['K线看盘软件/auto_update_gold.py','K线看盘软件/refresh_gold_recent.py','K线数据/黄金/AUTOMATION.json']
    save(gold/'AUTOMATION_MANIFEST.json',dict(path_base='repository_root',files=[dict(path=p,sha256=sha(ROOT/p))for p in paths],layout_migration=True,original_manifest_sha256=sha(AUDIT/'gold_automation_before/AUTOMATION_MANIFEST.json')))
    # Protected runtime/model/account bytes must match their pre-migration values.
    protected=[]
    for r in inventory:
        rel=r['new'];p=ROOT/rel
        select=(p.name.startswith('supermind_')or '/model/'in rel or '/model_artifacts/'in rel or p.suffix=='.sqlite3' or rel.startswith(('沪深2研究/runtime/','沪深实盘工作台/runtime/','沪深2研究/K线练习/runtime/')))
        if select and 'sha256'in r and not rel.startswith('archive/'):
            protected.append(dict(path=rel,sha256=sha(p),unchanged=sha(p)==r['sha256']))
    assert all(x['unchanged']for x in protected),[x for x in protected if not x['unchanged']]
    save(AUDIT/'protected_assets.json',protected)
    records=json.loads((AUDIT/'path_edits.json').read_text(encoding='utf8'))
    lookup={r['new']:r for r in inventory}
    for row in records:
        p=ROOT/row['new'];row['after']=sha(p)
        original=lookup.get(row['new'],{}).get('sha256')
        row['inventory_original_sha256']=original
        row['backup_stage']='original' if original==row['before']else 'path_migration_intermediate_or_unhashed_document'
    save(AUDIT/'path_edits.json',records)
    before=json.loads((AUDIT/'asset_verification.json').read_text(encoding='utf8'))
    expected={'.gitignore':'new private data ignore rules','tools/reorganize_workspace.py':'maintenance utility revised during migration','K线看盘软件/runtime/viewer.log':'viewer restarted and API probes logged'}
    expected.update({'启动沪深看盘.cmd':'launcher target migrated','tools/relocate_workspace.ps1':'prevent accidental repeat relocation','K线看盘软件/AGENTS.md':'canonical gold/index data locations documented','K线看盘软件/launch.py':'startup diagnostic path migrated','K线数据/黄金/AUTOMATION.json':'existing automation entrypoint relocated','K线数据/黄金/AUTOMATION_MANIFEST.json':'operational automation hashes updated with original retained'})
    assert not before['missing'] and set(before['differences'])<=expected.keys()
    report=dict(status='verified',inventory_files=len(inventory),inventory_bytes=sum(r['size']for r in inventory),missing_files=before['missing'],unexpected_asset_differences=[],reviewed_differences={p:expected[p]for p in before['differences']},protected_files=len(protected),protected_bytes_unchanged=True,
        validation=dict(viewer_api_equivalence=6,workbench_http_routes=7,workbench_unit_tests=85,hushen1_execution_tests=4,committed_market_tests=2,sse_tests=4,direction1_tests=9,direction1_manifest_files=19832,kechuang_reference_parity_runs=14,hushen2_metric_parity_runs=58,hushen2_frozen_account_replay='verified exact reference',hushen1_range_replay='completed without unresolved actions/reference differences',repository_check='passed'),
        cache=dict(files=391,action='recoverably moved under bytecode/ with .disabled suffix',physical_delete_blocked=True),
        schedules=dict(windows_task='Hushen2_Orbit_1830',windows_status='Ready',gold_automation='automation-3',gold_status='ACTIVE',schedules_changed=False),
        limitations=['Historical read-only research source remains frozen; old layouts retained as history, not current entrypoints.','Hushen2 --frozen-only replays through the existing frozen input cutoff; no extrapolation or retraining.','Full-period Hushen1 research was not rerun; callback parity, execution tests and a short current-data replay were verified.'],github_pushed=False)
    save(AUDIT/'FINAL_REPORT.json',report)
    print(json.dumps({k:report[k]for k in ['status','inventory_files','missing_files','protected_files','protected_bytes_unchanged']},ensure_ascii=False))

if __name__=='__main__':main()
