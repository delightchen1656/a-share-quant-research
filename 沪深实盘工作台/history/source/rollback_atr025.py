"""User-authorized ATR-only rollback and today's unexecuted workflow reset."""
import hashlib,json,sqlite3,shutil,sys
from pathlib import Path
from datetime import datetime
BASE=Path(__file__).resolve().parents[1];ROOT=BASE.parents[1]
BACKUP=ROOT/'archive/hushen_2/production_baseline_backups/before_p12_20261023_001422'
DATA=BASE/'tracker/data'
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    # Original code/config was copied before edits; complete short-path ledger backup.
    assert (BACKUP/'strategies/hushen_2/CURRENT_SELECTION.json').exists()
    with sqlite3.connect(DATA/'ledger.sqlite3') as db,sqlite3.connect(BACKUP/'ledger.sqlite3') as dst:
        db.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    for name in ['market_status.json','finished_2026-10-22.json']:
        if (DATA/name).exists():shutil.copy2(DATA/name,BACKUP/name)
    sys.path.insert(0,str(BASE/'runtime'));sys.path.insert(0,str(BASE/'tracker'))
    from signal_policy import configuration
    from service import Tracker
    tracker=Tracker();cycle=tracker.cycle();before=tracker.ledger.state()
    day=tracker.info['market_date'];assert day==cycle,(day,cycle)
    events=tracker.ledger.events()
    accepted=[e for e in events if not e['voided'] and e['kind']=='accept' and e['data'].get('signal_date')==day]
    executed=[e for e in events if not e['voided'] and e['kind']=='buy' and e['data'].get('order_id','').startswith(day+'_')]
    assert not executed,'Today has recorded fills; manual review required'
    # User explicitly confirms these recommendations were NOT submitted to broker.
    reset_ids={e['id'] for e in events if not e['voided'] and e['kind'] in ('accept','reject') and e['data'].get('signal_id','').startswith(day+'_')}
    with tracker.ledger.connect() as db:
        for eid in sorted(reset_ids):db.execute('UPDATE events SET voided=1 WHERE id=?',(eid,))
        old_review=[dict(r) for r in db.execute('SELECT * FROM confirmations WHERE day=?',(cycle,))]
        db.execute('DELETE FROM confirmations WHERE day=?',(cycle,))
    finish=DATA/f'finished_{cycle}.json'
    if finish.exists():finish.unlink()
    selection=BASE/'CURRENT_SELECTION.json';s=json.loads(selection.read_text(encoding='utf-8'))
    save(BACKUP/'P12_REGISTRATION.json',s)
    s['baseline_registered_on']='2026-10-23'
    s['selection']['baseline_id']='C04_NEW_ATR_GE025_ROLLBACK_20261023'
    s['selection'].pop('research_candidate_id',None);s['selection']['signal_filter']=configuration()
    s['hashes_sha256']['signal_policy_py']=digest(BASE/'runtime/signal_policy.py').upper()
    s['model_runtime']['historical_signal_equivalence_scope']='Original unfiltered C04_NEW builder; ATR025-only post-top3 filter, no retraining'
    s['operational_overrides']['signal_filter']=dict(authorized_on='2026-10-23',policy=configuration()['policy'],scope='New recommendations only; today unsubmitted recommendations explicitly reset; historical accepted orders, positions and cash preserved',previous_baseline_backup=str(BACKUP.relative_to(ROOT)).replace('\\','/'),model_features_and_weights_changed=False,other_execution_rules_changed=False,selection_is_post2024_informed=True,production_verification='tracker/data/atr025_rollback_verification.json')
    s['evidence'].update(latest_baseline_selection_date='2026-10-23',latest_baseline_evaluation_end='2026-10-22',latest_baseline_results='results/holdout_restricted/previous_baselines_2015/attempt_20261022_235142/atr025/SUMMARY.json',latest_baseline_results_version='ATR025',risk_population='ATR025 same-snapshot 2015 Q1 starts; retain legacy risk files as history')
    save(selection,s)
    after=tracker.ledger.state()
    assert before['cash']==after['cash'] and before['deferred']==after['deferred'] and before['positions']==after['positions']
    tracker.info.update(status='awaiting_review',signals=[],message='第一步：复核资金；已回退仅ATR≥2.5%，确认后生成今日新推荐',signal_filter_policy=configuration()['policy'])
    tracker.save_info()
    save(DATA/'atr025_rollback_verification.json',dict(status='workflow_reset_awaiting_user_review',at=datetime.now().isoformat(),cycle=cycle,backup=str(BACKUP),voided_today_decisions=sorted(reset_ids),old_review=old_review,cash=after['cash'],positions_unchanged=True,model_hashes={p.name:digest(p) for p in (BASE/'model').glob('*.txt')},policy=configuration()))
    print(json.dumps(dict(cycle=cycle,cash=after['cash'],voided_decisions=sorted(reset_ids),accepted_reset=len(accepted),policy=configuration()),ensure_ascii=False))
if __name__=='__main__':main()
