"""Fixed rule on Hengyin, independent 2019 flat start; no parameter search."""
from pathlib import Path
import json,shutil
import numpy as np
import pandas as pd
from run_woer_fixed import CFG,sha,save,metrics,targets
from scan_leaders_fixed import simulate

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
OUT=Path(__file__).resolve().parent/'holdout_restricted'/'hengyin_2019_20261031'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    audit=ROOT/'K线数据/更新备份与审计/20261030/audit.json';a=json.loads(audit.read_text(encoding='utf8'));assert a['status']=='ok'
    save(OUT/'RULE.json',dict(code='603106',name='恒银科技',parameters=CFG,start='2019-01-01',cutoff='2026-10-30',start_flat=True,execution='next quoted-day open after completed close signal; ideal fill',price_basis='qfq gross fractional price observation, no fees or cash corporate-action ledger',cooldown='exit signal i -> next entry check close i+5, earliest fill open i+6',parameter_search=False,not_blind=True))
    inputs=[];frames=[]
    commit=json.loads((audit.parent/'commit_manifest.json').read_text(encoding='utf8'))
    for kind in ['qfq','raw']:
        src=ROOT/f'K线数据/沪深/{kind}/SH/603106.SH.parquet';p=OUT/f'{kind}.parquet';h=sha(src)
        assert any(x['destination']==str(src.relative_to(ROOT)).replace('\\','/') for x in commit['files'])
        shutil.copyfile(src,p);assert h==sha(src)==sha(p);inputs.append(dict(source=str(src),snapshot=str(p),sha256=h))
        q=pd.read_parquet(p);q['date']=pd.to_datetime(q.date).dt.strftime('%Y-%m-%d')
        for c in ['open','high','low','close','preclose','tradestatus','volume','isST']:q[c]=pd.to_numeric(q[c],errors='raise')
        assert q.date.is_unique and q.date.is_monotonic_increasing and q.date.max()=='2026-10-30'
        frames.append(q)
    q,r=frames;assert q.date.tolist()==r.date.tolist()
    result,d,trades,flags=simulate(q,r,'2019-01-01');result.pop('full_period_comparable')
    annual=[];base=1.;bh=1.
    for y,g in d.groupby(d.date.str[:4]):
        st=metrics(g.nav,g.date,base);b=metrics(g.buyhold_nav,g.date,bh)
        annual.append(dict(year=int(y),strategy_return_pct=st['total_return_pct'],strategy_mdd_pct=st['max_drawdown_pct'],buyhold_return_pct=b['total_return_pct'],buyhold_mdd_pct=b['max_drawdown_pct']))
        base=float(g.nav.iloc[-1]);bh=float(g.buyhold_nav.iloc[-1])
    # Reconcile every day's wealth using an independent cash / adjusted-unit ledger.
    g=q[q.tradestatus.eq(1)&q.volume.gt(0)&q[['open','high','low','close']].gt(0).all(axis=1)].reset_index(drop=True)
    start=int(g.date.lt('2019-01-01').sum());s=targets(g.close,start)
    n=int(g.date.le('2024-12-31').sum());pd.testing.assert_frame_equal(s.iloc[:n],targets(g.close.iloc[:n],start))
    cash=1.;units=0.;nav=[]
    for i in range(start,len(g)):
        if i>start and s.iloc[i-1].signal=='buy':units=cash/g.open.iloc[i];cash=0.
        elif i>start and s.iloc[i-1].signal=='sell':cash=units*g.open.iloc[i];units=0.
        nav.append(cash+units*g.close.iloc[i])
    assert np.allclose(nav,d.nav,atol=1e-11,rtol=1e-11)
    t=pd.DataFrame(trades);result.update(code='603106',name='恒银科技',annual=annual,worst_trade_pct=float(t.return_pct.min()),best_trade_pct=float(t.return_pct.max()),limit_flags=flags,last_close_signal=str(s.iloc[-1].signal),price_observation_only=True)
    d.to_csv(OUT/'daily_nav.csv',index=False,encoding='utf-8-sig');t.to_csv(OUT/'trades.csv',index=False,encoding='utf-8-sig');pd.DataFrame(annual).to_csv(OUT/'annual.csv',index=False,encoding='utf-8-sig');save(OUT/'RESULT.json',result)
    save(OUT/'VALIDATION.json',dict(passed=True,independent_daily_cash_ledger_reconciliation=True,signal_prefix_invariance=True,next_quoted_day_execution=True,source_snapshots_verified=True))
    save(OUT/'MANIFEST.json',dict(inputs=inputs,audit_sha256=sha(audit),rule_sha256=sha(OUT/'RULE.json'),script_sha256=sha(Path(__file__)),engine_sha256=sha(Path(__file__).with_name('scan_leaders_fixed.py')),outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.json','.csv'] and p.name!='MANIFEST.json'}))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
