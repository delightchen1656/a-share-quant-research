"""Reproduce the one current direction; posterior access requires an explicit flag."""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def number(x):return float(str(x).strip() or 0)

def prepare(period):
    area=HERE/'inputs_pre2025' if period=='development' else HERE/'holdout_restricted/inputs'
    manifest=read(area/'MANIFEST.json')
    if period=='development':
        dates=pd.to_datetime(pd.read_parquet(area/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist()
    else:
        calendar=pd.read_csv(area/'trade_calendar.csv',dtype=str)
        dates=calendar.loc[calendar.is_trading_day=='1','calendar_date'].tolist()
    raw=pd.read_parquet(area/'signals.parquet')
    pending=raw.loc[raw.entry_pending].copy() if 'entry_pending' in raw else raw.iloc[:0]
    d=raw.loc[~raw.entry_pending].copy() if 'entry_pending' in raw else raw.copy()
    lookup={(r['code'],r['mode']):r for r in manifest['files']}
    quotes={};factors={};allraw={}
    for code in d.code.unique():
        frames=[]
        for mode in ['raw','qfq']:
            info=lookup[(code,mode)];path=HERE/info['path'];assert sha(path)==info['sha256']
            z=pd.read_parquet(path).set_index('date');z.index=pd.to_datetime(z.index).strftime('%Y-%m-%d')
            assert z.index.max()<=manifest['cutoff'];frames.append(z)
        r,q=frames;assert r.index.equals(q.index)
        valid=(pd.to_numeric(r.tradestatus)==1)&r.volume.gt(0)&r.open.gt(0)
        allraw[code]=r;rv=r.loc[valid]
        quotes[code]={row.date:row for row in rv.rename_axis('date').reset_index().itertuples(index=False)}
        factors[code]=(q.loc[valid].close/rv.close).to_dict()
    records=read(area/'company_actions.json');actions={}
    start='2021-01-01' if period=='development' else '2025-01-01'
    if period=='development':assert all(int(k.split('/')[-1])<=2024 for k in records)
    for key,rows in records.items():
        code=key[:6]
        if code not in quotes:continue
        grouped={}
        for record in rows:
            day=record.get('dividOperateDate')
            if day and start<=day<=manifest['cutoff']:grouped.setdefault(day,[]).append(record)
        for day,candidates in grouped.items():
            before=[s for s in quotes[code] if s<day]
            if not before:continue
            previous=float(quotes[code][before[-1]].close)
            ref=float(allraw[code].loc[day,'preclose']) if day in allraw[code].index else None
            def error(row):
                stock=number(row.get('dividStocksPs',''))+number(row.get('dividReserveToStockPs',''))
                return 0. if ref is None else abs((previous-number(row.get('dividCashPsBeforeTax','')))/(1+stock)-ref)
            row=min(candidates,key=error)
            actions[(code,day)]=dict(cash=number(row.get('dividCashPsBeforeTax','')),
                stock=number(row.get('dividStocksPs',''))+number(row.get('dividReserveToStockPs','')),
                taxable_stock=number(row.get('dividStocksPs','')),pay=row.get('dividPayDate') or day,
                release=row.get('dividStockMarketDate') or day,reference_error=error(row))
    for e in d.itertuples():assert e.entry_date in quotes[e.code],f'Missing frozen entry {e.code} {e.entry_date}'
    return d,dates,{s:i for i,s in enumerate(dates)},quotes,factors,actions,pending

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--period',choices=['development','posterior'],default='development');args=parser.parse_args()
    if args.period=='development':
        def guard(event,values):
            if event=='open' and not isinstance(values[0],int) and 'holdout_restricted' in Path(values[0]).parts:
                raise PermissionError('Development cannot open posterior data')
        sys.addaudithook(guard)
        import engine
        output=HERE/'generated/development';gold=read(HERE/'results/development/RESULT.json')
    else:
        path=HERE/'holdout_restricted/audit_engine.py';spec=importlib.util.spec_from_file_location('direction1_audit_engine',path)
        engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)
        output=HERE/'holdout_restricted/generated';gold=read(HERE/'holdout_restricted/audit/AUDIT_RESULT.json')
    output.mkdir(parents=True,exist_ok=True);engine.OUT=output
    d,dates,pos,quotes,factors,actions,pending=prepare(args.period)
    rule=read(HERE/'RULE.json');account=rule['account'];ids=set(zip(d.code,d.date))
    result=engine.run(d,{'sample':ids},dates,pos,quotes,factors,actions,'sample',True,
        account['capital'],account['slots'],forced_day=account['forced_close_buy_offset'],
        take_profit=account['take_profit'],stop_loss=account['stop_loss'],quiet=True)
    assert not result['specials'],'Unexpected frozen-data delayed exit'
    expected=gold['summary']
    assert abs(result['summary']['final_equity']-expected['final_equity'])<.01
    assert abs(result['summary']['max_drawdown']-expected['max_drawdown'])<1e-9
    reference=gold['yearly'] if args.period=='development' else gold['annual']
    for actual,old in zip(result['yearly'],reference):
        assert actual['year']==old['year']
        assert abs(actual['return_pct']-old['return_pct'])<1e-9
        assert abs(actual['max_drawdown']-old['max_drawdown'])<1e-9
    if args.period=='posterior':
        for h in result['open_positions']:
            if h['due_date']=='9999-12-31':h['due_date']=None;h['due_beyond_snapshot']=True
    record=dict(direction='方向1',period=args.period,matched_frozen_results=True,result=result,pending_count=len(pending))
    (output/'REPRODUCTION.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(direction='方向1',period=args.period,reproduction='passed',final_equity=result['summary']['final_equity']),ensure_ascii=False))

if __name__=='__main__':main()
