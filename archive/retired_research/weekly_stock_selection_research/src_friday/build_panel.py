from concurrent.futures import ThreadPoolExecutor
import json
import numpy as np
import pandas as pd
from common import BASE,AUDIT,SPEC,FACTORS,sha,dump,quote_valid


def main():
    assert json.loads((BASE/'audits/holdout_restricted/research_v1/minimum_execution_checks.json').read_text(encoding='utf-8'))['passed']
    inputs=BASE/'inputs_pre2025'
    manifest=json.loads((inputs/'kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    calendar=pd.read_parquet(inputs/'calendar_dev_v1.parquet')
    days=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
    day_array=days.to_numpy()
    schedule=[]
    skipped=[]
    index=pd.read_parquet(inputs/'sse_dev_v1.parquet').set_index('date')
    for entry_day in pd.date_range('2018-01-01','2023-12-31',freq='W-MON'):
        entry_day=entry_day-pd.Timedelta(days=3)
        tuesday=entry_day+pd.Timedelta(days=4)
        if entry_day not in days or tuesday not in days:
            skipped.append(dict(entry_day=str(entry_day.date()),reason='Friday_or_Tuesday_closed_or_outside_development'))
            continue
        mon_pos=int(days.get_loc(entry_day))
        if mon_pos==0:
            continue
        tue_pos=int(days.get_loc(tuesday))
        assert tue_pos>mon_pos and entry_day.weekday()==4 and tuesday.weekday()==1
        signal=days[mon_pos-1]
        schedule.append(dict(signal_date=str(signal.date()),entry_day=str(entry_day.date()),tuesday=str(tuesday.date()),
                             signal_pos=mon_pos-1,mon_pos=mon_pos,tue_pos=tue_pos,
                             year=int(entry_day.year),market_return=float(index.loc[tuesday,'close']/index.loc[entry_day,'open']-1)))
    plan=pd.DataFrame(schedule)
    signal_positions=plan.signal_pos.to_numpy()
    mon=plan.mon_pos.to_numpy()
    tue=plan.tue_pos.to_numpy()
    dump(AUDIT/'schedule_skips.json',skipped)
    plan.to_parquet(AUDIT/'weekly_schedule.parquet',index=False)
    def worker(item):
        if not item['rows']:
            return None
        path=inputs/'kline_dev_v1'/item['snapshot_file']
        assert sha(path)==item['snapshot_sha256']
        df=pd.read_parquet(path)
        assert df.date.le('2023-12-31').all()
        pos=np.searchsorted(day_array,df.date.to_numpy())
        assert np.array_equal(day_array[pos],df.date.to_numpy())
        frame=df.set_index('date').reindex(days)
        valid,num=quote_valid(frame)
        logret=np.log1p(num.pctChg/100).where(valid)
        chain=logret.cumsum()
        amount=num.amount.where(valid)
        volume=num.volume.where(valid)
        turn=pd.to_numeric(frame.turn,errors='coerce').where(valid)
        count=valid.astype(int).cumsum()
        coverage=valid.rolling(20,min_periods=20).mean()
        median_amount=amount.rolling(20,min_periods=18).median()
        eligible=(valid&frame.isST.astype(str).eq('0')&num.close.ge(3)&count.ge(120)&coverage.ge(.9)&median_amount.ge(2e7))
        eligible_signal=eligible.iloc[signal_positions].to_numpy()
        if not eligible_signal.any():
            return None
        factor=pd.DataFrame(index=days)
        for n in [20,60]:
            minimum=int(np.ceil(n*.9))
            factor[f'quote_momentum{n}']=np.expm1(logret.rolling(n,min_periods=minimum).sum())
            factor[f'quote_volatility{n}']=logret.rolling(n,min_periods=minimum).std()
        factor['quote_reversal5']=-np.expm1(logret.rolling(5,min_periods=5).sum())
        factor['quote_reversal1']=-np.expm1(logret)
        factor['log_median_amount20']=np.log(median_amount)
        factor['volume_ratio5_20']=volume.rolling(5,min_periods=5).mean()/volume.rolling(20,min_periods=18).mean()
        factor['turnover_mean20']=turn.rolling(20,min_periods=18).mean()
        lo=chain.rolling(20,min_periods=18).min()
        hi=chain.rolling(20,min_periods=18).max()
        factor['quote_high_position20']=((chain-lo)/(hi-lo)).where(hi.gt(lo),.5)
        factor['quote_efficiency20']=logret.rolling(20,min_periods=18).sum().abs()/logret.abs().rolling(20,min_periods=18).sum()
        factor['last_quote_change']=np.expm1(logret)
        chosen=np.flatnonzero(eligible_signal)
        result=plan.iloc[chosen][['signal_date','entry_day','tuesday','year','market_return']].reset_index(drop=True)
        result['symbol']=item['symbol']
        for column in FACTORS:
            result[column]=factor[column].iloc[signal_positions[chosen]].to_numpy()
        m=mon[chosen]
        t=tue[chosen]
        mv=valid.iloc[m].to_numpy()
        tv=valid.iloc[t].to_numpy()
        ordinary=mv&tv
        for j,(start,stop) in enumerate(zip(m,t)):
            active_path=valid.iloc[start:stop+1].to_numpy()
            references=num.preclose.iloc[start+1:stop+1].to_numpy()
            prior_closes=num.close.iloc[start:stop].to_numpy()
            ordinary[j]=bool(ordinary[j] and active_path.all() and np.all(np.abs(references-prior_closes)<=.015))
        result['label_status']=np.where(~mv,'entry_quote_unavailable',np.where(~tv,'exit_quote_unavailable',np.where(~ordinary,'corporate_reference_change','ordinary_quote_horizon')))
        gross=num.close.iloc[t].to_numpy()/num.open.iloc[m].to_numpy()-1
        result['ordinary_gross_quote_return']=np.where(ordinary,gross,np.nan)
        result['ordinary_quote_excess']=result.ordinary_gross_quote_return-result.market_return
        result['label_maturity_date']=result.tuesday
        return result
    parts=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,result in enumerate(pool.map(worker,manifest['files']),1):
            if result is not None:
                parts.append(result)
            if i%500==0:
                print(f'weekly factor construction {i}/{len(manifest["files"])}',flush=True)
    panel=pd.concat(parts,ignore_index=True).sort_values(['signal_date','symbol']).reset_index(drop=True)
    panel[FACTORS]=panel[FACTORS].replace([np.inf,-np.inf],np.nan)
    assert not panel.duplicated(['signal_date','symbol']).any()
    assert (pd.to_datetime(panel.signal_date)<pd.to_datetime(panel.entry_day)).all()
    assert panel.label_status.ne('ordinary_quote_horizon').equals(panel.ordinary_quote_excess.isna())
    panel.to_parquet(AUDIT/'weekly_factor_panel.parquet',index=False)
    stats=panel.groupby('year').agg(observations=('symbol','size'),symbols=('symbol','nunique'),dates=('signal_date','nunique'),known_ordinary_labels=('ordinary_quote_excess','count'))
    dump(AUDIT/'panel_audit.json',dict(rows=len(panel),unique_symbols=panel.symbol.nunique(),
         labels=panel.label_status.value_counts().to_dict(),factors=FACTORS,signal_precedes_entry=True,
         no_future_quality_flags_in_pool=True,ordinary_quote_target_is_not_blanket_economic_approval=True,
         snapshot_manifest_sha256=sha(inputs/'kline_dev_v1/manifest.json'),panel_sha256=sha(AUDIT/'weekly_factor_panel.parquet')))
    print(stats.to_string(),flush=True)
    print(panel.label_status.value_counts().to_string(),flush=True)


if __name__=='__main__':
    main()
