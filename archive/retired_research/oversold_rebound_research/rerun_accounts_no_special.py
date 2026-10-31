"""User-directed ex-post exclusion of deadline-unpriced special cases, no model refit."""
import json
import pandas as pd
import account_backtest as engine
from study import ROOT,digest

OLD=ROOT/'results_v9_accounts'
NEW=ROOT/'results_v10_accounts_no_special'


def main():
    inputs=list(engine.prepare())
    original=json.loads((OLD/'summary.json').read_text(encoding='utf8'))
    excluded=set();audit=[]
    for item in original['results']:
        t=pd.read_parquet(OLD/item['key']/'trades.parquet')
        for _,r in t.loc[t.reason.str.contains('delayed')].iterrows():
            excluded.add((r.code,r.signal_date))
    NEW.mkdir(exist_ok=True);engine.OUT=NEW
    base=inputs[0].copy()
    for iteration in range(5):
        inputs[0]=base.loc[[(r.code,r.date) not in excluded for r in base.itertuples()]].copy()
        results=[];new=set()
        for pool in ['sample','leaders']:
            for filtered in [False,True]:
                for capital,slots in [(1000000,50),(100000,5)]:
                    result=engine.run(*inputs,pool,filtered,capital,slots)
                    results.append(result)
                    trades=pd.read_parquet(NEW/result['key']/'trades.parquet')
                    for _,r in trades.loc[trades.reason.str.contains('delayed')].iterrows():new.add((r.code,r.signal_date))
        audit.append(dict(iteration=iteration,excluded=sorted(excluded),newly_exposed_specials=sorted(new)))
        if not new:break
        excluded.update(new)
    else:raise RuntimeError('Special-case exclusion did not stabilize')
    assert all(r['summary']['delayed_exits']==0 for r in results)
    final=dict(original,results=results,exclude_special_cases=True,
        excluded_specials=[dict(code=c,signal_date=d) for c,d in sorted(excluded)],
        exclusion_audit=audit,prior_summary_sha256=digest(OLD/'summary.json'),
        exclusion_caveat='User-authorized ex-post deadline-unpriced event exclusion. All accounts rerun chronologically after releasing slots; not an ex-ante deployable filter. Prior ML selector unchanged.')
    (NEW/'summary.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf8')
    checks=[]
    for r in results:
        t=pd.read_parquet(NEW/r['key']/'trades.parquet')
        ok=bool(abs(t.pnl.sum()+r['summary']['capital']-r['summary']['final_equity'])<.01)
        assert ok;checks.append(dict(scenario=r['key'],cash_pnl_reconciled=ok,delayed_exits=0))
    (NEW/'VERIFICATION.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    import report_accounts
    report_accounts.OUT=NEW;report_accounts.main()


if __name__=='__main__':main()
