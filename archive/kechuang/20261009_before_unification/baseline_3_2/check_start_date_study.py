"""Read-only result checks; writes only the study validation report."""
import hashlib
import json
import pandas as pd
from start_date_study import OUT, HERE, DATA

r=pd.read_csv(OUT/'start_date_results.csv')
c=pd.read_parquet(OUT/'daily_equity.parquet')
t=pd.read_parquet(OUT/'trades.parquet')
p=json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
assert len(r)==58 and r.start.nunique()==58
assert r.end.eq('2026-09-30').all()
assert c.cash.min()>=-.01 and c.equity.min()>0
assert c.groupby('start').date.max().eq(pd.Timestamp('2026-09-30')).all()
assert t.qty.between(1,50000).all()
assert t.loc[t.side.eq('BUY'),'qty'].ge(200).all()
for _,g in t.groupby(['start','symbol','date']):
    assert not (g.side.eq('BUY').any() and g.side.ne('BUY').any())
for s,g in t.groupby('symbol'):
    raw=pd.read_parquet(DATA/'raw'/(s+'.parquet')).set_index('date')
    for (start,date),h in g.groupby(['start','date']):
        assert h.qty.sum()<=int(raw.loc[date,'volume']*.25)
        assert str(raw.loc[date,'tradestatus'])=='1'
assert hashlib.sha256((HERE.parent/'supermind_baseline_3_2_audited_daily.py').read_text(encoding='utf-8').encode()).hexdigest()==p['strategy_sha256']
assert json.loads((OUT/'unresolved_actions.json').read_text())==[]
report={'status':'passed','starts':58,'daily_rows':len(c),'fills':len(t),
        'checks':['complete date ranges','positive NAV/nonnegative cash','50k order cap','200-share minimum buy','no same-day roundtrip','25% daily volume cap','no suspended fills','frozen platform source unchanged','no unrecorded held reference adjustment'],
        'limits':'Does not certify model out-of-sample validity or exact platform fill parity.'}
(OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
