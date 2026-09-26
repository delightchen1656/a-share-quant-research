"""Diagnostic only for the pre-existing best full-period candidate; no re-selection."""
import pandas as pd
import research as r
import round09_affordability as method

def main():
    out=r.HERE/'round09_affordability/start_diagnostic.json'
    assert not out.exists(),'Preserve completed diagnostic'
    method.install();cfg=next(c for c in method.CONFIGS if c['id']=='J24')
    study=method.Study([cfg]);long=[];rolling=[]
    r.save(out.with_name('start_diagnostic_protocol.json'),dict(candidate=cfg,
        purpose='Diagnostic of prior best J24,not a new selection or completed goal validation; fullSharpe0.898alreadyfails. No stress/neighbor tests in this diagnostic.',
        starts='2020..2024eachquarter+0/5/10/15sessions,to2026-09-11;2022..2024sameoffsets with complete24months'))
    for year in range(2020,2025):
        for month in (1,4,7,10):
            base=study.cal.searchsorted(pd.Timestamp(year=year,month=month,day=1))
            for offset in (0,5,10,15):
                start=study.cal[base+offset]
                z,_,_=study.run(cfg,start,r.END);long.append(z)
                end=start+pd.DateOffset(months=24)-pd.Timedelta(days=1)
                if year>=2022 and end<=r.END:
                    z,_,_=study.run(cfg,start,end);rolling.append(z)
            print('DIAG',year,month,len(long),len(rolling),flush=True)
    assert len(long)==80 and len(rolling)==44
    result=dict(goal_achieved=False,full_gate_already_failed=True,long=r.summarize(long),rolling=r.summarize(rolling),
        cohorts={str(y):r.summarize([z for z in long if z['start'].startswith(str(y))]) for y in range(2020,2025)},
        long_windows=long,rolling_windows=rolling,
        warning='Repeated historical research; overlapping starts not independent OOS. Diagnostic does not include stress/neighbors.')
    r.save(out,result)
    print('DIAG_DONE',result['long'],result['rolling'],flush=True)

if __name__=='__main__':main()
