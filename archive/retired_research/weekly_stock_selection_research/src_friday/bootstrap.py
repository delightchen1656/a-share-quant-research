"""Register the user-requested Friday-open variant; retain Monday study unchanged."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent.parent
SOURCE=BASE/'src'
DEST=BASE/'src_friday'
OUT=BASE/'audits/holdout_restricted/friday_open_v2'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'registration.json').exists(), 'Do not overwrite a frozen variant'
    spec=json.loads((BASE/'audits/holdout_restricted/research_v1/spec.json').read_text(encoding='utf-8'))
    spec['id']='weekly_previous_friday_open_tuesday_close_v2'
    spec['authorization']='User restricts entries to previous Friday open or Monday open and exits to Tuesday close. Compare two separate accounts, never double capital or mix the entry schedules.'
    spec['independence']='Extension of this new independent weekly study; same local raw whitelist, same local company cache and ten registered screening methods. Prior Monday results retained unchanged.'
    spec['known_posterior_context']+=' Monday comparison already observed before this user-requested Friday comparison; no blind validation claim.'
    spec['timing']='Previous calendar Friday open to following Tuesday close; use last actual market close strictly before Friday, usually Thursday. Both endpoints must be open, otherwise skip without shifting. Monday closure does not invalidate an otherwise valid Friday/Tuesday pair. No Friday-close information in selection. Keep Monday-open variant as separate reference.'
    spec['label_admission']='Ordinary quote-excess proxy only when every market-session bar from Friday through Tuesday is active and each subsequent preclose matches the previous actual close within0.015. Any reference break or missing quote means unknown target, never a pre-entry pool exclusion.'
    spec['trial_budget']='Same10methods and12factors, same holdings/costs, no hyperparameter/weekday/seed search. Add only the explicitly requested Friday-open entry alternative.'
    (OUT/'spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    files=['common.py','execution.py','build_panel.py','fit_methods.py','portfolio.py','probe_portfolios.py','company_data.py','run_comparison.py']
    for name in files:
        text=(SOURCE/name).read_text(encoding='utf-8')
        if name=='common.py':
            text=text.replace("audits/holdout_restricted/research_v1","audits/holdout_restricted/friday_open_v2")
        else:
            # 'entry_day' is the Friday schedule column, distinct from actual fill entry_date.
            text=text.replace('monday','entry_day').replace('Monday','Friday')
        if name=='build_panel.py':
            text=text.replace("    assert json.loads((AUDIT/'minimum_execution_checks.json').read_text(encoding='utf-8'))['passed']", "    assert json.loads((BASE/'audits/holdout_restricted/research_v1/minimum_execution_checks.json').read_text(encoding='utf-8'))['passed']")
            text=text.replace("tuesday=entry_day+pd.Timedelta(days=1)","entry_day=entry_day-pd.Timedelta(days=3)\n        tuesday=entry_day+pd.Timedelta(days=4)")
            text=text.replace('assert tue_pos==mon_pos+1','assert tue_pos>mon_pos and entry_day.weekday()==4 and tuesday.weekday()==1')
            text=text.replace("        ordinary=mv&tv&(np.abs(num.preclose.iloc[t].to_numpy()-num.close.iloc[m].to_numpy())<=.015)", "        ordinary=mv&tv\n        for j,(start,stop) in enumerate(zip(m,t)):\n            active_path=valid.iloc[start:stop+1].to_numpy()\n            references=num.preclose.iloc[start+1:stop+1].to_numpy()\n            prior_closes=num.close.iloc[start:stop].to_numpy()\n            ordinary[j]=bool(ordinary[j] and active_path.all() and np.all(np.abs(references-prior_closes)<=.015))")
        if name=='run_comparison.py':
            text=text.replace("codefiles=[BASE/'src'/f", "codefiles=[BASE/'src_friday'/f")
        (DEST/name).write_text(text,encoding='utf-8')
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    registration=dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),spec_sha256=digest(OUT/'spec.json'),
        before_new_Friday_scores_and_outcomes=True,Monday_outputs_retained=True,
        code=[dict(path=p.name,sha256=digest(p)) for p in sorted(DEST.glob('*.py'))],
        inherited_Monday_spec_sha256=digest(BASE/'audits/holdout_restricted/research_v1/spec.json'))
    (OUT/'registration.json').write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Friday protocol and code registered:',OUT,flush=True)


if __name__=='__main__':
    main()
