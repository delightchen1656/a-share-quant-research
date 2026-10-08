"""Preregistered controlled-variable study; run before any results."""
from pathlib import Path
import json, hashlib, itertools
HERE=Path(__file__).resolve().parent
BASE=dict(buffer=1.5,interval=20,smooth=5,min_smooth=3,count=5,growth=0.,hysteresis=0.,
          weights=[.35,.20,.25,.20],vol_window=60,return_window=20,amount_min=1e7,vol_max=.09)
GROUPS=['buffer','interval','smooth','count','expansion','weights','windows','filters']
KEYS=dict(buffer=['buffer'],interval=['interval'],smooth=['smooth','min_smooth'],count=['count'],
          expansion=['growth','hysteresis'],weights=['weights'],windows=['vol_window','return_window'],filters=['amount_min','vol_max'])
def build():
    values={
      'buffer':[dict(buffer=n/5) for n in range(5,25)],
      'interval':[dict(interval=n) for n in [5,7,9,10,12,14,15,16,18,20,21,22,24,25,27,28,30,32,35,40]],
      'smooth':[dict(smooth=w,min_smooth=m) for w in [4,5,8,12,20] for m in [1,(w+1)//2,(3*w+3)//4,w]],
      'count':[dict(count=n) for n in range(2,22)],
      'expansion':[dict(growth=g,hysteresis=h) for g in [1.25,1.5,1.75,2.,3.] for h in [0.,.05,.1,.2]],
      'weights':[dict(weights=[a,b,.25,round(.75-a-b,8)]) for a in [.2,.3,.35,.4] for b in [.1,.15,.2,.25,.3]],
      'windows':[dict(vol_window=v,return_window=r) for v in [20,40,60,120] for r in [5,10,20,40,60]],
      'filters':[dict(amount_min=a,vol_max=v) for a in [1e7,2e7,3e7,5e7,1e8] for v in [.03,.05,.07,.09]]}
    trials=[]
    for group in GROUPS:
        assert len(values[group])==20
        assert len({json.dumps(x,sort_keys=True) for x in values[group]})==20
        for i,patch in enumerate(values[group]):
            trials.append(dict(id=f'{group}_{i+1:02}',group=group,config=dict(BASE,**patch)))
    # Twenty predetermined subsets; group winners are inserted only after group selection.
    subsets=[GROUPS]+[[g for g in GROUPS if g!=omit] for omit in GROUPS]
    subsets += [GROUPS[:n] for n in range(2,7)]
    subsets += [['weights','windows'],['weights','filters'],['interval','expansion'],['count','filters'],['smooth','weights','windows'],['expansion','weights','filters']]
    assert len(subsets)==20 and len({tuple(s) for s in subsets})==20
    return dict(base=BASE,group_keys=KEYS,groups=GROUPS,trials=trials,combined_subsets=subsets,
        initial_cash=100000,exposure=.98,expansion_cap='max(15, initial count)',
        expansion_rule='Geometric thresholds from initial 100000. Previous close equity, rebalance only. Downgrade below threshold*(1-hysteresis); minimum initial count.',
        periods=dict(training=['2019-01-01','2022-12-31'],selection=['2023-01-01','2023-12-31'],confirmation=['2024-01-01','2024-11-29'],heldout=['2025-01-01','2026-09-30']),
        selection_rule='Within each group: evaluate 20 training configurations plus original control, shortlist at most three with >=40 fills, exposure>=0.15 and DD<=original+0.02; rank by net CAGR, Sharpe, lower DD, then ID. Replay shortlist + baseline on 2023; require >=10 fills, exposure>=0.15, DD<=2023 original+0.02, choose by same order; baseline fallback. Freeze group winners. Build 20 preregistered combinations, train and shortlist three identically, choose on 2023 vs original and unique group winners; freeze all before confirmation/heldout.',
        confirmation_gate='Combined champion: positive CAGR and CAGR>=original and DD<=original+0.02 on 2024-01-01..2024-11-29. Failure reported; no alternate or retuning.',
        heldout='Evaluate only original, frozen group winners, and frozen combined champion. Do not select using 2024 or 2025+. Separate empty-start accounts. No parameters optimized against full 2020-2026 results.',
        scope='Eight existing parameter families x20; no new stop-loss/trend/volatility timing rules without scope expansion. Fixed original uploaded D11 framework, with previously exposed history. Not unseen prospective testing.')
if __name__=='__main__':
    path=HERE/'protocol.json'
    if path.exists():raise RuntimeError('Protocol already registered')
    q=build();path.write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REGISTERED',len(q['trials']), 'plus20 combinations',hashlib.sha256(path.read_bytes()).hexdigest())
