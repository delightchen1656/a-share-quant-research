"""Finalize pre2024 diagnostics only; never touch the one-way audit result directory."""
import json
import sys
import datetime
import numpy as np
import pandas as pd
from settings import BASE,OLD,OUT,sha,dump


def main():
    sys.path.insert(0,str(BASE/'src'))
    from portfolio import Quotes
    from common import tick
    top=pd.read_parquet(OUT/'selected_signal_labels.parquet')
    top=top.loc[top.year.ge(2021)].copy()
    q=Quotes()
    flags={}
    for row in top[['symbol','monday','tuesday']].drop_duplicates().itertuples():
        b=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.monday)))
        e=q.bar(row.symbol,q.days.get_loc(pd.Timestamp(row.tuesday)))
        flags[(row.symbol,row.monday)]=(bool(b['active'] and not b['st'] and b['open']<tick(b['preclose']*1.1)-.004),
            bool(e['active'] and e['close']>tick(e['preclose']*(.95 if e['st'] else .9))+.004))
    diagnostics=[]
    for variant,g in top.groupby('variant'):
        f=np.array([flags[(r.symbol,r.monday)] for r in g.itertuples()])
        diagnostics.append(dict(variant=variant,total_signals=len(g),opening_quote_cannot_buy=int((~f[:,0]).sum()),
              Tuesday_quote_cannot_exit=int((~f[:,1]).sum()),signals_never_removed=True))
    dump(OUT/'development_execution_flags.json',diagnostics)
    report=OUT/'DEVELOPMENT_REPORT.txt'
    text=report.read_text(encoding='utf-8')
    heading='\n开发期全部信号的报价可执行性诊断（不删除信号，不改收益标签）\n'
    assert heading not in text
    text+=heading
    for d in diagnostics:
        text+=f"{d['variant']} | 信号{d['total_signals']} | 开盘不可买{d['opening_quote_cannot_buy']} | 周二收盘不可卖{d['Tuesday_quote_cannot_exit']}\n"
    report.write_text(text,encoding='utf-8')
    original=json.loads((OLD/'artifact_registration.json').read_text(encoding='utf-8'))
    for row in original['files']:
        assert sha(BASE/row['path'])==row['sha256'],row['path']
    freeze=OUT/'frozen_candidate_v1'
    manifest=json.loads((freeze/'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        assert sha(freeze/row['path'])==row['sha256'],row['path']
    # Explicitly enumerate only developer-controlled files. Do not traverse any
    # audit output, even to hash it: the parent must not read future results.
    artifacts=[p for p in OUT.iterdir() if p.is_file() and p.name!='DEVELOPMENT_ARTIFACTS.json']
    artifacts+=list((BASE/'src_factor_v4').glob('*.py'))
    artifacts+=list(freeze.iterdir())
    dump(OUT/'DEVELOPMENT_ARTIFACTS.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         optimizer_closed_after_freeze=True,future_audit_not_opened_by_parent=True,
         original53hashes_verified=True,frozen_package_unchanged=True,
         files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(artifacts) if p.is_file()]))
    print('Pre2024diagnostics and developer artifact hashes finalized. No audit directory read.',flush=True)


if __name__=='__main__':
    main()
