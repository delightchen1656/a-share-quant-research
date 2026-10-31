"""科创基准1：2020年第一季度逐交易日起点敏感性回放。"""
from pathlib import Path
import inspect, json
import pandas as pd
import data_helpers as p
import engine as e

HERE=Path(__file__).resolve().parent
STAR=HERE.parent
OUT=STAR/'results/start_dates_2020q1_to_20260930'
END='2026-09-30'
INITIAL_CASH=500000.0
WINDOW_START='2020-01-01'
WINDOW_END='2020-03-31'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    source=STAR/'supermind_kechuang_1.py'
    provenance=json.loads((STAR/'research/provenance.json').read_text(encoding='utf-8'))
    assert p.sha(source)==provenance['platform_sha256'],'Platform source changed'
    snap=HERE/'data/snapshot_20260930'
    manifest=json.loads((snap/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(snap/f)==v['sha256'] for f,v in manifest.items()),'Snapshot hash mismatch'

    ns=p.namespace(source.read_text(encoding='utf-8-sig'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k]))))
            for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    ds,panels,meta=p.dataset(snap,'2020-01-01',END)
    ds=ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy())
    ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy())
    ds['score']=ds.p-.22*ds.stop
    eligible=ds[(ds.p>=.63)&(ds.stop<=.50)].sort_values(
        ['date','score','symbol'],ascending=[True,False,True])
    candidates={d:list(g.head(8).symbol) for d,g in eligible.groupby('date')}

    p.save(OUT/'corporate_actions.json',json.loads(
        (HERE/'data/corporate_actions.json').read_text(encoding='utf-8')))
    old_out=e.OUT;e.OUT=OUT
    try: action_map=e.actions([])
    finally: e.OUT=old_out
    calendar=pd.read_csv(p.DATA/'metadata/trade_calendar_20261004.csv')
    dates=pd.DatetimeIndex(pd.to_datetime(
        calendar.loc[calendar.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>='2019-12-20')&(dates<=END)]
    expected=dates[(dates>=WINDOW_START)&(dates<=WINDOW_END)]
    assert len(expected)>0

    ns['_exit_action']=e.old_exit
    models[0]['max_positions']=14
    source_code=inspect.getsource(e.run_starts)
    source_code=source_code.replace(
        "starts=dates[dates>=pd.Timestamp(requested_start)][:1]",
        f"starts=dates[(dates>=pd.Timestamp(requested_start))&(dates<=pd.Timestamp('{WINDOW_END}'))]")
    source_code=source_code.replace(
        "return results[0],all_curves[0],pd.DataFrame(all_trades),reference_differences",
        "return results,pd.concat(all_curves,ignore_index=True),pd.DataFrame(all_trades),reference_differences")
    env=dict(e.__dict__);env.update(END=pd.Timestamp(END),CASH=INITIAL_CASH,OUT=OUT)
    exec(source_code,env)
    results,curves,trades,diffs=env['run_starts'](
        (ns,models,dates,panels,candidates,meta,set()),action_map,WINDOW_START)
    assert len(results)==len(expected),(len(results),len(expected))
    frame=pd.DataFrame(results)
    fees=trades.groupby('start').fee.sum() if not trades.empty else pd.Series(dtype=float)
    frame['fees']=frame.start.map(fees).fillna(0.0)
    frame['drawdown_magnitude']=-frame.max_drawdown
    assert frame.start.tolist()==[str(d.date()) for d in expected]
    assert curves.groupby('start').cash.min().min()>=-.01
    assert trades.loc[trades.side.eq('BUY'),'qty'].ge(200).all()

    fields=['final_asset','total_return','cagr','drawdown_magnitude','sharpe_rf0',
            'avg_exposure','fills','fees']
    stats={}
    for field in fields:
        s=frame[field].astype(float)
        stats[field]={'mean':float(s.mean()),'min':float(s.min()),'max':float(s.max()),
                      'median':float(s.median()),'p25':float(s.quantile(.25)),
                      'p75':float(s.quantile(.75)),
                      'min_start':frame.loc[s.idxmin(),'start'],
                      'max_start':frame.loc[s.idxmax(),'start']}
    summary={'strategy':'科创基准1','initial_cash':INITIAL_CASH,'end':END,
             'start_window':[WINDOW_START,WINDOW_END],
             'actual_start_count':len(frame),'models_retrained':False,
             'platform_sha256':p.sha(source),'snapshot_verified':True,'statistics':stats}
    p.save(OUT/'summary.json',summary)
    p.save(OUT/'all_starts.json',frame.to_dict('records'))
    frame.to_parquet(OUT/'all_starts.parquet',index=False)
    curves.to_parquet(OUT/'daily_equity_all_starts.parquet',index=False)
    trades.to_parquet(OUT/'trades_all_starts.parquet',index=False)
    p.save(OUT/'reference_price_differences.json',diffs)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
