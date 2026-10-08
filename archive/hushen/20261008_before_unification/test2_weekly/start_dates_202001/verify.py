import run as r
import ast,json,hashlib
import pandas as pd
import numpy as np
def main():
    protocol=json.loads((r.HERE/'protocol.json').read_text(encoding='utf-8'));entry=r.BASE/'supermind_test2_D11_fast_weekly.py'
    checks={'frozen_code':hashlib.sha256(entry.read_bytes()).hexdigest()==protocol['strategy_sha256']}
    old=(r.BASE/'start_date_study/study.py').read_text(encoding='utf-8')
    new=(r.HERE/'weekly_engine.py').read_text(encoding='utf-8')
    a="            if g.alpha_first or (index-1)%20==0:g.alpha_ranks=ranks[str(prev.date())]"
    b="            g.alpha_rebalance_due=m._weekly_rebalance_due(date,prev,g.alpha_first)\n            if g.alpha_rebalance_due:g.alpha_ranks=ranks[str(prev.date())]"
    checks['ledger_only_schedule_adapter_changed']=old.replace(a,b)==new
    engine=r.mod(r.HERE/'weekly_engine.py','mock');model=engine.module(entry,'check_export')
    date=pd.Timestamp('2019-12-31');calendar=pd.DatetimeIndex(pd.read_parquet(r.BASE/'start_date_study/benchmark.parquet').date);dates=calendar[calendar<=date][-5:];raw={}
    data=r.BASE.parents[1]/'sh_sz_market_research/data_pipeline/data'
    for path in sorted((data/'raw').glob('*/*.parquet')):
        x=pd.read_parquet(path);x.date=pd.to_datetime(x.date);x=x[x.date<=date].set_index('date').sort_index().tail(320)
        if x.empty:continue
        x=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'});x['is_paused']=1-pd.to_numeric(x.tradestatus);raw[path.stem]=x
    ranks,_=model.compute_signals(raw,{str(d.date()):set(raw) for d in dates},dates)
    checks['full_universe_ranking_parity']=ranks==json.loads((r.HERE/'rankings.json').read_text())['2019-12-31']
    results=json.loads((r.HERE/'results.json').read_text());q=pd.read_parquet(r.HERE/'daily_equity.parquet');t=pd.read_parquet(r.HERE/'trades.parquet')
    checks['sixteen_independent_starts']=len(results)==16 and sorted(v['start'] for v in results)==protocol['starts']
    checks['daily_rows_unique']=not q.duplicated(['start','date']).any()
    checks['no_borrowing']=q.cash.ge(-.01).all()
    checks['buy_round_lots']=t.loc[t.qty>0,'qty'].mod(100).eq(0).all()
    checks['nonempty_fills']=all(v['trades']>0 for v in results)
    checks['held_action_changes_resolved']=all(v['unresolved_actions']==0 for v in results)
    schedules=json.loads((r.HERE/'schedules.json').read_text())
    for row in results:
        start=pd.Timestamp(row['start']);z=q[q.start==start].sort_values('date');nav=z.equity.to_numpy()
        assert z.date.iloc[0]==start and str(z.date.iloc[-1].date())==protocol['end']
        assert np.isclose(nav[-1],row['final_equity'])
        assert np.isclose(-(nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]-1).min(),row['max_drawdown'])
        expected=[]
        for d in calendar[calendar>=start]:
            prev=calendar[calendar.get_loc(d)-1]
            if d==start or d-pd.Timedelta(days=d.weekday())!=prev-pd.Timedelta(days=prev.weekday()):expected.append(str(d.date()))
        assert expected==schedules[row['start']]
    checks['weekly_schedule_every_path']=True;checks['equity_and_drawdown_recomputed']=True
    checks={k:bool(v) for k,v in checks.items()};r.dump('validation.json',checks);assert all(checks.values()),checks;print('PASS',len(checks),flush=True)
if __name__=='__main__':main()
