"""Export an explicitly hash-pinned full-period catalog and quote generation."""
from pathlib import Path
import argparse,hashlib,json,shutil
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def atomic(p,obj):
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8');temp.replace(p)
def main():
    p=argparse.ArgumentParser();p.add_argument('--inputs',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--signals',required=True);p.add_argument('--signals-sha256',required=True);a=p.parse_args()
    root=Path(a.inputs).resolve();source=Path(a.signals).resolve();assert sha(root/'MANIFEST.json')==a.manifest_sha256 and sha(source)==a.signals_sha256
    m=read(root/'MANIFEST.json');allowed={x['path']:x['sha256'] for x in m['files']}
    def checked(relative):
        q=root/relative;assert sha(q)==allowed[relative];return q
    u=pd.read_parquet(checked(m['universe']));leaders=set(pd.read_parquet(checked(m['leader_classification'])).code)
    u['is_leader']=u.code.isin(leaders);assert u.code.is_unique
    data=HERE/'data';generation=data/('full_history_'+m['cutoff'].replace('-',''));generation.mkdir(exist_ok=True)
    stocks=u[['code','name','is_leader']].copy();stockpath=generation/'stocks.parquet';stocks.to_parquet(stockpath,index=False);names=stocks.set_index('code')
    quotes=read(checked(m['quote_manifest']));lookup={x['code']:x for x in quotes['files'] if x['mode']=='qfq'}
    files=[]
    for code in u.code:
        item=lookup[code];q=checked(item['path']);target=generation/'qfq'/f'{code}.parquet';target.parent.mkdir(exist_ok=True)
        if not target.exists() or sha(target)!=item['sha256']:shutil.copyfile(q,target)
        assert sha(target)==item['sha256'];files.append(dict(code=code,path=target.relative_to(data).as_posix(),sha256=item['sha256']))
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(checked(m['calendar'])).date)).sort_values().unique()
    cohort=pd.read_csv(source,dtype={'code':str});assert not cohort.duplicated(['code','signal_date']).any();output=[]
    for code,f in cohort.groupby('code',sort=True):
        q=pd.read_parquet(root/lookup[code]['path']);q['date']=pd.to_datetime(q.date);q=q.set_index('date').reindex(dates)
        for r in f.itertuples(index=False):
            entry=pd.Timestamp(r.entry_date) if pd.notna(r.entry_date) else None
            valid_entry=entry is not None and entry in dates and r.next_valid_open in [True,'True',1]
            i=dates.get_loc(entry) if valid_entry else 0;anchor=float(q.at[entry,'open']) if valid_entry else np.nan
            valid_entry=valid_entry and np.isfinite(anchor) and anchor>0;w=q.iloc[i:i+60] if valid_entry else q.iloc[:0]
            status=pd.to_numeric(w.tradestatus,errors='coerce');vol=pd.to_numeric(w.volume,errors='coerce');active=status.eq(1)&vol.gt(0)
            good=active&w[['high','low']].gt(0).all(axis=1)&np.isfinite(w[['high','low']]).all(axis=1)
            unknown=~status.isin([0,1])|(status.eq(1)&(vol.isna()|vol.lt(0)))|(active&~good)
            complete=bool(valid_entry and len(w)==60 and not unknown.any() and good.any())
            high=float(w.loc[good,'high'].max()/anchor-1) if complete else None;low=float(w.loc[good,'low'].min()/anchor-1) if complete else None
            day=str(r.signal_date)[:10]
            output.append(dict(id=f'd1_{code}_{day}',direction='d1',code=code,name=str(names.at[code,'name']),is_leader=bool(names.at[code,'is_leader']),signal_date=day,entry_date=entry.strftime('%Y-%m-%d') if entry is not None else None,next_valid_open=bool(valid_entry),next_state=str(r.next_state),max_up=high,max_down=low,window_complete=complete,window_sessions=len(w),entry_basis='信号次一正式交易日开盘',observation='D0—D+59复权价格触及；非含费交易收益'))
    output.sort(key=lambda x:(x['signal_date'],x['code']));assert len(output)==len(cohort)
    signalmeta=dict(schema=3,display_scope='historical_mainboard_full_history',universe_codes=len(u),signal_start=m['first_quote'],signal_cutoff=m['cutoff'],post_boundary_scan=True,authorization='用户明确要求全部信号覆盖现有全期；仅展示与固定规则审计，不反馈研发',window='D0—D+59，60个正式交易日，未完整窗口不参与涨跌排序',leader_note='软件当前龙头快照回看标记，非历史时点归属',directions=[dict(id='d1',label='方向1 · 超跌反弹 v3 · 全期',count=len(output),leader_count=sum(x['is_leader'] for x in output))],signals=output,sources=[dict(path=str(source),sha256=a.signals_sha256),dict(path=str(root/'MANIFEST.json'),sha256=a.manifest_sha256)])
    signalpath=generation/'signals.json';atomic(signalpath,signalmeta)
    meta=dict(app='hushen-basic-kline-viewer',cutoff=m['cutoff'],scope='SH_SZ_MAIN_BOARD_ONLY',stocks=len(u),price_basis='前复权',volume_source_unit='股',stocks_path=stockpath.relative_to(data).as_posix(),stocks_sha256=sha(stockpath),signals_path=signalpath.relative_to(data).as_posix(),signals_sha256=sha(signalpath),files=files,source_manifest_sha256=a.manifest_sha256,leader_note=signalmeta['leader_note'],automatic_refresh=False,historical_names_included=True,not_current_active_only=True)
    atomic(data/'MANIFEST.json',meta)
    print(json.dumps(dict(cutoff=m['cutoff'],stocks=len(u),signals=len(output),leaders=sum(x['is_leader'] for x in output),by_year=pd.Series([x['signal_date'][:4] for x in output]).value_counts().sort_index().to_dict()),ensure_ascii=False))
if __name__=='__main__':main()
