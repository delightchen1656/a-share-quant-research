"""Causal execution-only ATR alternatives, without model inference or signal selection."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import numpy as np
import pandas as pd
from run_june2020_starts import ROOT,BASE,ARCHIVE,module
from market import digest

PROTOCOL=Path(__file__).with_name('ATR_UNIFORM_PROTOCOL.json')


def calculate(bars):
    b=bars.copy().sort_values('date').reset_index(drop=True)
    for c in ['open','high','low','close','preclose','tradestatus']:b[c]=pd.to_numeric(b[c],errors='coerce')
    def relative(frame):
        r=(frame.close/frame.preclose-1).where(frame.tradestatus.eq(1))
        chain=(1+r.fillna(0.)).cumprod();prior=chain.shift(1)
        high=chain*(frame.high/frame.close);low=chain*(frame.low/frame.close)
        tr=pd.concat([high-low,(high-prior).abs(),(low-prior).abs()],axis=1).max(axis=1)/prior
        return tr.rolling(14,min_periods=14).mean().clip(.015,.05)
    # Match the original pre-2025 model-panel truncation exactly.
    pre=b.loc[b.date.ge(pd.Timestamp('2018-01-01')) & b.date.lt(pd.Timestamp('2025-01-01'))]
    rel=relative(b)
    if len(pre):rel.loc[pre.index]=relative(pre)
    tr=pd.concat([b.high-b.low,(b.high-b.preclose).abs(),(b.low-b.preclose).abs()],axis=1).max(axis=1)
    return pd.DataFrame(dict(date=b.date,relative=rel,price=(tr.rolling(14,min_periods=14).mean()/b.close).clip(.015,.05)))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
    source=ARCHIVE/'results/holdout_restricted/seven_versions_four_extra_rows/posterior_old_new/run_audit.py'
    audit=module('uniform_atr_frozen_audit',source)
    expected=audit.validate_sources();signals=audit.candidate_signals('C04_NEW',expected['C04_NEW'])
    out=args.output or BASE/'results/holdout_restricted/uniform_atr_inputs'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    (out/'PREREGISTERED_PROTOCOL.json').write_text(PROTOCOL.read_text(encoding='utf-8'),encoding='utf-8')
    records=[];inputs={}
    root=ROOT/'sh_sz_market_research/data_pipeline/data/qfq'
    for n,(symbol,needed) in enumerate(signals.groupby('symbol',sort=True),1):
        path=root/symbol[-2:]/f'{symbol}.parquet';before=digest(path)
        bars=pd.read_parquet(path,columns=['date','open','high','low','close','preclose','tradestatus'])
        bars['date']=pd.to_datetime(bars.date);bars=bars[bars.date.le(needed.date.max())]
        assert not bars.date.duplicated().any()
        a=calculate(bars);a['symbol']=symbol
        a=needed[['date','symbol','atr_pct']].merge(a,on=['date','symbol'],validate='one_to_one',how='left')
        assert a[['relative','price']].notna().all().all(),symbol
        records.append(a);assert digest(path)==before
        inputs[str(path.relative_to(ROOT))]=before
        if n%250==0:print('ATR',n,flush=True)
    frame=pd.concat(records,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    pre=frame.date.lt(pd.Timestamp('2025-01-01'))
    # Preserve the exact original historical inputs rather than revised qfq rounding.
    # Both formula outputs were retained before the account experiments.
    revised_errors={'relative_pre2025':float((frame.loc[pre,'relative']-frame.loc[pre,'atr_pct']).abs().max())}
    frame['relative_recomputed_current_qfq']=frame.relative
    frame['price_recomputed_current_qfq']=frame.price
    cache_sources={}
    for policy,filename in [('relative','model_panel_batch002_pre2025.parquet'),('price','feature_panel_pre2025.parquet')]:
        path=ARCHIVE/'cache'/filename;original=pd.read_parquet(path,columns=['date','symbol','atr_pct'])
        original['date']=pd.to_datetime(original.date)
        values=frame.loc[pre,['date','symbol']].merge(original,on=['date','symbol'],how='left',validate='one_to_one')
        assert values.atr_pct.notna().all()
        if policy=='relative':assert np.array_equal(values.atr_pct.to_numpy(),frame.loc[pre,'atr_pct'].to_numpy())
        frame.loc[pre,policy]=values.atr_pct.to_numpy()
        cache_sources[str(path.relative_to(ROOT))]=digest(path)
    errors={'relative_pre2025':float((frame.loc[pre,'relative']-frame.loc[pre,'atr_pct']).abs().max()),
            'price_post2024':float((frame.loc[~pre,'price']-frame.loc[~pre,'atr_pct']).abs().max())}
    print('Original ATR overlap errors',errors,flush=True)
    report=dict(status='verified' if max(errors.values())<1e-10 else 'source_overlap_mismatch',
        overlap_errors=errors,revised_qfq_diagnostic=revised_errors,original_cache_hashes=cache_sources,rows=len(frame),input_hashes=inputs,protocol_sha256=digest(PROTOCOL),
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),source,audit.reopt.PANEL_PATH,expected['C04_NEW']['post']]})
    frame.to_parquet(out/'ATR_ALTERNATIVES.parquet',index=False)
    report['atr_panel_sha256']=digest(out/'ATR_ALTERNATIVES.parquet')
    (out/'VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True)
    assert report['status']=='verified',errors


if __name__=='__main__':main()
