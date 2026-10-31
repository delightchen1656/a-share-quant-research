"""One-time production backup/registration; never rewrites account events."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,shutil,sqlite3

BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def backup():
    out=ROOT/'archive/hushen_2/production_baseline_backups'/datetime.now().strftime('before_p12_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    paths=[BASE/'CURRENT_SELECTION.json',BASE/'README.md',ROOT/'AGENTS.md']
    for folder in ['runtime','model','tracker']:
        paths.extend(p for p in (BASE/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ['.py','.pyw','.json','.js','.css','.html','.txt','.md'])
    paths.append(BASE/'backtest/replay_selected_price_atr.py')
    hashes={}
    for p in paths:
        relative=p.relative_to(ROOT);destination=out/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,destination);assert digest(destination)==digest(p);hashes[str(relative)]=digest(p)
    database=BASE/'tracker/data/ledger.sqlite3';destination=out/'strategies/hushen_2/tracker/data/ledger.sqlite3'
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(destination) as dst:
        src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        account={table:[list(r) for r in src.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in ['events','confirmations','account_settings']}
    save(out/'ACCOUNT_BEFORE.json',account)
    save(out/'BACKUP_MANIFEST.json',dict(created=datetime.now().isoformat(),files=hashes,database_integrity='ok',
        restore_warning='Code/model/config backup; do not restore the old ledger over later real trading records without explicit authorization.'))
    print(out)


def register(backup_path):
    backup_path=backup_path.resolve()
    assert (backup_path/'BACKUP_MANIFEST.json').exists()
    source=BASE/'results/holdout_restricted/pair_filters_pre2025/attempt_20261022_184427/TOP5.json'
    p12=next(r['config'] for r in json.loads(source.read_text(encoding='utf-8'))['top5'] if r['config']['id']=='P12')
    import sys
    sys.path.insert(0,str(BASE/'runtime'))
    from signal_policy import configuration,MINIMUM_SIZE_PROXY,MINIMUM_VOL60
    assert {c['factor']:c['threshold'] for c in p12['conditions']}==dict(size_proxy=MINIMUM_SIZE_PROXY,vol60=MINIMUM_VOL60)
    path=BASE/'CURRENT_SELECTION.json';s=json.loads(path.read_text(encoding='utf-8'))
    s['selection']['baseline_id']='C04_NEW_P12_ATR_GE025_20261022'
    s['selection']['research_candidate_id']='P12';s['selection']['signal_filter']=configuration()
    s['hashes_sha256']['signal_policy_py']=digest(BASE/'runtime/signal_policy.py').upper()
    s['maintenance']['strategy_logic_changed']=True;s['maintenance']['factor_builder_logic_changed']=False
    s['model_runtime']['historical_signal_equivalence_scope']='Original unfiltered C04_NEW builder; P12 is a separate post-top3 filter, not a model retraining'
    s['operational_overrides']['signal_filter']=dict(authorized_on='2026-10-22',policy=configuration()['policy'],
        scope='New recommendations only; preserve accepted orders, positions, cash, account records and frozen protection terms',
        research_candidate='P12',model_features_and_weights_changed=False,other_execution_rules_changed=False,
        previous_baseline_backup=str(backup_path.relative_to(ROOT)).replace('\\','/'),
        frozen_definition=str(source.relative_to(BASE)).replace('\\','/'),frozen_definition_sha256=digest(source),
        development_end='2024-12-31',posterior_comparison='results/holdout_restricted/retained_four_post2024/attempt_20261022_191355/SUMMARY.json',
        selected_backtest_entry='backtest/replay_selected_price_atr.py',production_verification='tracker/data/p12_deployment_verification.json',
        selection_is_post2024_informed=True,blind_test_status='Frozen pre2025 conditions; production choice made after viewing posterior results')
    s['evidence']['latest_baseline_selection_date']='2026-10-22';s['evidence']['latest_baseline_evaluation_end']='2026-10-21'
    s['evidence'].setdefault('legacy_risk_population',s['evidence'].get('risk_population'))
    s['evidence']['risk_population']='P12: all 58 Q1-2020 starts through 2026-10-21; legacy mixed-ATR risk files remain historical, not P12 metrics'
    s['evidence']['latest_baseline_results']='results/holdout_restricted/retained_four_post2024/attempt_20261022_191355/SUMMARY.json'
    s['evidence']['latest_baseline_results_version']='P12'
    save(path,s)
    print(json.dumps(dict(status='registered',baseline_id=s['selection']['baseline_id'],signal_filter=configuration()),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['backup','register']);p.add_argument('--backup',type=Path);a=p.parse_args()
    if a.mode=='backup':backup()
    else:register(a.backup)
