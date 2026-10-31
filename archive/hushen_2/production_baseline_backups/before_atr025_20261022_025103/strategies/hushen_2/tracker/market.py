"""Read committed local market data and freeze nightly signals."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[1]
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'
RUNTIME=BASE/'runtime'
sys.path.insert(0,str(RUNTIME))
from strategy import build_signals
from signal_policy import (POLICY_ID as SIGNAL_FILTER_POLICY_ID, MINIMUM_ATR,
                           configuration as signal_filter_configuration,
                           filter_frame as filter_signal_frame,
                           filter_payloads as filter_signal_payloads)

FEATURES=['f_ret1','f_ret5','f_ret20','f_ret60','f_vol20','f_ma20','f_amount_ratio5','f_log_amount','f_log_price','f_turn','f_range','f_downside20','f_ohlc_rsi14','f_ohlc_atr_compress5_20']
FEATURE_START='2018-01-01'
SIGNAL_START='2020-01-01'
PIPELINE_VERSION='hushen2-original-intersection-price-atr-ge025-v3'
EXECUTION_ATR_POLICY='price_tr_sma14_over_signal_close_clip015_050_v1'


def signal_cache_path(folder,day):
    # Preserve the old policy's immutable signals; accepted orders keep their ledger ATR.
    return Path(folder)/f'signals_{day}_{EXECUTION_ATR_POLICY}_{SIGNAL_FILTER_POLICY_ID}.json'


def build_recommendations(component_panel):
    """Original frozen ranking/top3 first, then the registered ATR-only filter."""
    return filter_signal_frame(build_signals(component_panel))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_inventory():
    """Stat guard: updater is detected before/after computation, not read concurrently."""
    return [(str(p.relative_to(DATA)).replace('\\','/'),p.stat().st_size,p.stat().st_mtime_ns)
            for kind in ('qfq','raw') for p in sorted((DATA/kind).glob('*/*.parquet'))]


def _updater_running():
    if os.name!='nt': return False
    command="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -match 'daily_market_update\\.py' } | Select-Object -ExpandProperty ProcessId"
    r=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=20,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    return bool(r.stdout.strip())


def read_calendar():
    paths=sorted((DATA/'metadata').glob('trade_calendar_*.csv'))
    if not paths:
        raise ValueError('本地交易日历缺失')
    f=pd.read_csv(paths[-1],dtype=str)
    days=f.loc[f.is_trading_day.eq('1'),'calendar_date'].tolist()
    return days,str(f.calendar_date.max())


def calendar_extended(folder):
    local,last=read_calendar()
    path=Path(folder)/'calendar.json'
    if path.exists():
        local=sorted(set(local)|set(json.loads(path.read_text())['sessions']))
    return local


def refresh_calendar(folder):
    import baostock as bs
    today=datetime.now().date()
    cached=calendar_extended(folder)
    if cached and pd.Timestamp(cached[-1])>=pd.Timestamp(today)+pd.Timedelta(days=45):
        return
    response=bs.login()
    if response.error_code!='0':
        raise ValueError('交易日历服务连接失败')
    try:
        response=bs.query_trade_dates(start_date=f'{today.year}-01-01',end_date=f'{today.year+1}-12-31')
        rows=[]
        while response.error_code=='0' and response.next():
            rows.append(response.get_row_data())
        if response.error_code!='0' or not rows:
            raise ValueError('交易日历未返回有效结果')
        f=pd.DataFrame(rows,columns=response.fields)
        sessions=f.loc[f.is_trading_day.eq('1'),'calendar_date'].tolist()
        path=Path(folder)/'calendar.json'
        path.write_text(json.dumps({'sessions':sessions,'fetched_at':datetime.now().isoformat()}),encoding='utf-8')
    finally:
        bs.logout()


def health(folder):
    if _updater_running():
        raise ValueError('18点行情更新进程仍在运行，禁止读取更新中的行情')
    audits=[]
    for p in sorted((ROOT/'data_updates').glob('*/audit.json'),reverse=True):
        a=json.loads(p.read_text(encoding='utf-8'))
        if a.get('status')=='ok':
            audits.append((p,a))
            break
    if not audits:
        raise ValueError('未找到成功提交的行情审计')
    path,a=audits[0]
    date=a['target']
    # The updater stages the transaction under a date-specific directory.
    for stage in (ROOT/'data_updates').glob('*/staging'):
        audit=stage.parent/'audit.json'
        raise ValueError('发现行情暂存事务，请等待完整提交并清除暂存区')
    if not a.get('committed_files') or not a.get('validation',{}).get('transactional_staging'):
        raise ValueError('行情审计尚未完成事务提交')
    if a.get('validation',{}).get('active_symbol_latest_date')!=date:
        raise ValueError('活跃证券行情截止日审计不一致')
    refresh=DATA/'metadata'/f"refresh_{date.replace('-','')}.json"
    if not refresh.exists(): raise ValueError('缺少沪深行情metadata refresh审计')
    metadata=json.loads(refresh.read_text(encoding='utf-8'))
    if any(metadata.get(k)!=a.get(k) for k in ('status','target','updated_at','datasets','validation')):
        raise ValueError('行情审计与metadata refresh不一致')
    commit=path.parent/'commit_manifest.json'
    if not commit.exists(): raise ValueError('缺少行情事务提交清单')
    cm=json.loads(commit.read_text(encoding='utf-8'))
    if cm.get('target')!=date or len(cm.get('files',[]))!=a['committed_files']:
        raise ValueError('行情提交清单数量或日期不一致')
    missing=[f'{name}.txt' for name in ('utility','pen025') if not (BASE/'model'/f'{name}.txt').exists()]
    sessions=calendar_extended(folder)
    if date not in sessions: raise ValueError('行情审计日期不在真实交易日历中')
    return {'market_date':date,'audit':str(path),'audit_sha256':digest(path),
            'refresh_sha256':digest(refresh),'updated_at':a.get('updated_at'),'missing_models':missing,'sessions':sessions}


def pipeline_identity(h):
    selection=json.loads((BASE/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    if selection.get('selection',{}).get('signal_filter')!=signal_filter_configuration():
        raise ValueError('沪深2登记的ATR筛选规则与当前代码不一致')
    if digest(RUNTIME/'signal_policy.py').upper()!=selection.get('hashes_sha256',{}).get('signal_policy_py'):
        raise ValueError('ATR筛选模块哈希与登记不一致')
    files=[Path(__file__),RUNTIME/'strategy.py',RUNTIME/'frozen_builder.py',RUNTIME/'signal_policy.py',BASE/'model/manifest.json',
           DATA/'metadata/historical_mainboard_universe.csv']+[BASE/'model'/f'{n}.txt' for n in ('utility','pen025','pen100')]
    payload={'version':PIPELINE_VERSION,'market_date':h['market_date'],'audit_sha256':h['audit_sha256'],
             'refresh_sha256':h['refresh_sha256'],'files':{str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in files},
             'inventory_sha256':hashlib.sha256(json.dumps(input_inventory()).encode()).hexdigest(),
             'signal_filter':signal_filter_configuration()}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),payload


def signals_digest(signals):
    return hashlib.sha256(json.dumps(signals,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def validate_signals(signals,h):
    if not isinstance(signals,list) or len(signals)>3: raise ValueError('信号数量或格式错误')
    day=h['market_date'];following=next((d for d in h['sessions'] if d>day),None)
    if not following: raise ValueError('缺少已核验的下一交易日')
    symbols=[];previous_rank=0
    for s in signals:
        if not isinstance(s['rank'],int) or not previous_rank<s['rank']<=3 or s['id']!=f"{day}_{s['symbol']}" or s['signal_date']!=day or s['valid_from']!=following:
            raise ValueError('信号排名、代码日期或适用日不一致')
        if not np.isfinite(s['trigger']) or s['trigger']<=0 or not MINIMUM_ATR<=s['atr']<=.05 or not np.isfinite(s['score']):
            raise ValueError('信号价格、ATR或分数无效')
        symbols.append(s['symbol'])
        previous_rank=s['rank']
    if len(set(symbols))!=len(symbols): raise ValueError('信号代码重复')


def model_features(b):
    """Batch002 model features intersected with all original Batch001 valid features."""
    r=(b.close/b.preclose-1).where(b.tradestatus.eq(1))
    rr=r.fillna(0.)
    chain=(1+rr).cumprod()
    prior=chain.shift(1)
    ah=chain*(b.high/b.close)
    al=chain*(b.low/b.close)
    tr=pd.concat([ah-al,(ah-prior).abs(),(al-prior).abs()],axis=1).max(axis=1)/prior
    f=pd.DataFrame(index=b.index)
    for k in (1,5,20,60): f[f'f_ret{k}']=chain/chain.shift(k)-1
    f['f_vol20']=r.rolling(20,min_periods=3).std()
    f['f_ma20']=chain/chain.rolling(20,min_periods=3).mean()-1
    f['f_amount_ratio5']=b.amount/b.amount.rolling(5,min_periods=3).mean()
    f['f_log_amount']=np.log1p(b.amount)
    f['f_log_price']=np.log(b.close)
    f['f_turn']=b.turn
    f['f_range']=(b.high-b.low)/b.preclose
    f['f_downside20']=r.clip(upper=0).pow(2).rolling(20,min_periods=3).mean().pow(.5)
    f['f_ohlc_rsi14']=rr.clip(lower=0).rolling(14,min_periods=3).sum()/rr.abs().rolling(14,min_periods=3).sum()
    f['f_ohlc_atr_compress5_20']=tr.rolling(5,min_periods=3).mean()/tr.rolling(20,min_periods=3).mean()
    f['atr_pct']=tr.rolling(14,min_periods=14).mean().clip(.015,.05)
    for key in ('date','symbol','close'): f[key]=b[key]
    f['vol60']=b.close.pct_change(fill_method=None).rolling(60,min_periods=60).std(ddof=0)
    f['overnight20']=(b.open/b.preclose-1).rolling(20,min_periods=20).mean()
    f['intraday20']=(b.close/b.open-1).rolling(20,min_periods=20).mean()
    f['turn20']=b.turn.rolling(20,min_periods=20).mean()
    f['mom60']=b.close/b.close.shift(60)-1.
    f['mom20']=b.close/b.close.shift(20)-1.
    f['vol20']=b.close.pct_change(fill_method=None).rolling(20,min_periods=20).std(ddof=0)
    f['ret5']=b.close/b.close.shift(5)-1.
    f['mom120']=b.close/b.close.shift(120)-1.
    f['close_to_high60']=b.close/b.close.rolling(60,min_periods=60).max()-1.
    tr_tech=pd.concat([b.high-b.low,(b.high-b.preclose).abs(),(b.low-b.preclose).abs()],axis=1).max(axis=1)
    f['_atr_tech']=(tr_tech.rolling(14,min_periods=14).mean()/b.close).clip(.015,.05)
    # User-approved execution-only override: match the former post-2024 account replay.
    # Do NOT alter tr or f_ohlc_atr_compress5_20, which belong to frozen model features.
    f['atr_pct']=f['_atr_tech']
    eligible=(b.index>=119)&b.close.between(2,80)&b.amount.ge(20e6)&b.amount.rolling(20,min_periods=20).median().ge(30e6)&b.isST.eq(0)&b.tradestatus.eq(1)
    # Both source builders drop their complete feature sets before their inner join.
    return f[eligible & b.date.ge(pd.Timestamp(SIGNAL_START))].replace([np.inf,-np.inf],np.nan).dropna().drop(columns='_atr_tech')


def feature_panel(day,progress=None):
    universe=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv',dtype=str)
    paths=sorted((DATA/'qfq').glob('*/*.parquet'))
    if {p.stem for p in paths}!=set(universe.symbol): raise ValueError('沪深历史股票池与qfq文件清单不一致')
    active=set(universe.loc[universe.status.eq('1'),'symbol'])
    rows=[]
    for i,path in enumerate(paths,1):
        b=pd.read_parquet(path)
        b['date']=pd.to_datetime(b.date)
        b=b[b.date.between(FEATURE_START,day)].sort_values('date').reset_index(drop=True)
        if b.date.duplicated().any(): raise ValueError(f'{path.stem}行情日期重复')
        if path.stem in active and (b.empty or b.date.max()!=pd.Timestamp(day)):
            raise ValueError(f'{path.stem}活跃证券缺少{day}行情，不能生成不完整排名')
        if len(b)<120: continue
        if set(b.symbol.astype(str))!={path.stem}: raise ValueError(f'{path.stem}行情代码不匹配')
        for c in ['open','high','low','close','preclose','amount','turn','tradestatus','isST']:
            b[c]=pd.to_numeric(b[c],errors='coerce')
        f=model_features(b)
        if not f.empty: rows.append(f)
        if progress and i%500==0: progress(f'feature files {i}/{len(paths)}')
    if not rows: raise ValueError('合格股票特征为空')
    p=pd.concat(rows,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    if p.duplicated(['date','symbol']).any(): raise ValueError('特征面板日期代码重复')
    return p


def score_panel(p):
    import lightgbm as lgb
    hashes=json.loads((BASE/'model/manifest.json').read_text(encoding='utf-8'))
    p=p.copy()
    for name in ('utility','pen025','pen100'):
        path=BASE/'model'/f'{name}.txt'
        if digest(path)!=hashes.get(name): raise ValueError(f'{name}模型哈希不一致')
        model=lgb.Booster(model_file=str(path))
        if model.feature_name()!=FEATURES: raise ValueError('模型特征顺序不一致')
        p[name]=model.predict(p[FEATURES],num_threads=4)
    cap=p.f_log_amount-np.log(p.f_turn.clip(lower=1e-6))
    ranks=p.assign(_cap=cap).groupby('date')[['_cap','vol60','overnight20','intraday20','mom120','close_to_high60','mom20']].rank(pct=True,method='average')-.5
    p['h_size_neg']=-ranks['_cap'];p['h_vol60_neg']=-ranks.vol60
    p['h_overnight_pos']=ranks.overnight20;p['h_intraday_neg']=-ranks.intraday20
    p['t_mom120_pos']=ranks.mom120;p['t_high60_pos']=ranks.close_to_high60
    p['t_mom20_pos']=ranks.mom20;p['t_vol60_neg']=-ranks.vol60
    return p


def predict(folder,h):
    import lightgbm as lgb
    import subprocess
    if h['missing_models']:
        raise ValueError('缺少沪深2冻结模型：'+', '.join(h['missing_models'])+'。原模型未恢复前不生成推荐。')
    manifest=BASE/'model/manifest.json'
    if not manifest.exists():
        raise ValueError('冻结模型来源与哈希清单缺失，无法核验是否为原版本')
    hashes=json.loads(manifest.read_text(encoding='utf-8'))
    for name in ('utility','pen025'):
        path=BASE/'model'/f'{name}.txt'
        if hashlib.sha256(path.read_bytes()).hexdigest().lower()!=hashes.get(name,'').lower():
            raise ValueError(f'{name}模型哈希不一致')
    subprocess.run([sys.executable,'-B',str(RUNTIME/'verify.py')],check=True,capture_output=True)
    day=h['market_date']
    before=health(folder)
    if before['audit_sha256']!=h['audit_sha256']: raise ValueError('预测前行情审计已变化，请重试')
    identity,inputs=pipeline_identity(before)
    # Full eligible history is essential: H uses last five eligible observations, not calendar days.
    p=score_panel(feature_panel(day))
    output=build_signals(p)
    output=output[output.date.eq(pd.Timestamp(day))].copy()
    names=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv',dtype=str).set_index('symbol').code_name.to_dict()
    result=[]
    for rank,r in enumerate(output.itertuples(),1):
        raw=pd.read_parquet(DATA/'raw'/r.symbol[-2:]/f'{r.symbol}.parquet')
        record=raw[pd.to_datetime(raw.date).eq(pd.Timestamp(day))]
        if len(record)!=1: raise ValueError(f'{r.symbol}原始收盘价缺失')
        if int(record.tradestatus.iloc[0])!=1: raise ValueError(f'{r.symbol}原始行情并非可交易状态')
        next_day=next((d for d in h['sessions'] if d>day),None)
        if not next_day: raise ValueError('下一交易日尚未被交易日历覆盖')
        result.append({'id':f'{day}_{r.symbol}','symbol':r.symbol,'name':names.get(r.symbol,r.symbol),'rank':rank,'signal_date':day,'valid_from':next_day,'trigger':float(record.close.iloc[0]),'atr':float(r.atr_pct),'atr_policy':EXECUTION_ATR_POLICY,'score':float(r.score)})
    original_candidates=result
    result=filter_signal_payloads(original_candidates)
    validate_signals(result,h)
    after=health(folder)
    after_identity,_=pipeline_identity(after)
    if after_identity!=identity: raise ValueError('预测过程中行情、代码或模型发生变化，本次结果作废')
    evidence={'pipeline_id':identity,'inputs':inputs,'feature_rows':len(p),'latest_eligible_symbols':int(p.date.eq(pd.Timestamp(day)).sum()),
              'signal_count':len(result),'signal_filter':signal_filter_configuration(),
              'original_top3':original_candidates,'removed_by_atr':[s for s in original_candidates if s['atr']<MINIMUM_ATR]}
    audit_folder=Path(folder)/'pipeline_audits';audit_folder.mkdir(parents=True,exist_ok=True)
    destination=audit_folder/f'{day}_{identity}.json'
    destination.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def raw_marks(symbols,day):
    result={}
    for symbol in symbols:
        path=DATA/'raw'/symbol[-2:]/f'{symbol}.parquet'
        if path.exists():
            f=pd.read_parquet(path,columns=['date','close'])
            f=f[pd.to_datetime(f.date).le(pd.Timestamp(day))].sort_values('date')
            if len(f): result[symbol]={'price':float(f.close.iloc[-1]),'date':str(pd.Timestamp(f.date.iloc[-1]).date())}
    return result
