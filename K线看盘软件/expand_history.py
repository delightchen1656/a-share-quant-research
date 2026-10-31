"""Add historical mainboard names to the independent read-only chart snapshot."""
from pathlib import Path
import json,hashlib,shutil
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    data=HERE/'data';mp=data/'MANIFEST.json';meta=json.loads(mp.read_text(encoding='utf8'))
    backup=HERE/'runtime/before_full_scope';backup.mkdir(exist_ok=True)
    for name in ['MANIFEST.json','stocks.parquet','signals.json']:
        if not (backup/name).exists():shutil.copy2(data/name,backup/name)
    source=ROOT/'K线数据/沪深'
    registry=source/'metadata/historical_mainboard_universe.csv';before=sha(registry)
    u=pd.read_csv(registry,dtype=str)
    assert u.number.is_unique and u.number.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
    old=pd.read_parquet(data/'stocks.parquet').set_index('code')
    leaders=pd.read_parquet(ROOT/'研究尝试/方向1_超跌反弹/holdout_restricted/leader_classification/mainboard_leaders.parquet')
    leaders['code']=leaders.code.astype(str).str.zfill(6);leader_codes=set(leaders.code)
    items={x['code']:x for x in meta['files']};rows=[];added=[]
    for r in u.itertuples():
        code=r.number
        if code not in items:
            src=source/'qfq'/r.exchange/(r.symbol+'.parquet');h=sha(src);q=pd.read_parquet(src);q['date']=pd.to_datetime(q.date)
            q=q.loc[q.date.le(meta['cutoff'])].sort_values('date');assert not q.date.duplicated().any() and sha(src)==h
            target=data/'qfq'/(code+'.parquet');q.to_parquet(target,index=False)
            items[code]=dict(code=code,path='qfq/'+target.name,sha256=sha(target));added.append(code)
        rows.append(dict(code=code,name=old.at[code,'name'] if code in old.index else r.code_name,is_leader=code in leader_codes,leader_source='保留合并名单' if code in leader_codes else ''))
    assert sha(registry)==before
    pd.DataFrame(rows).sort_values('code').to_parquet(data/'stocks.parquet',index=False)
    meta.update(stocks=len(rows),stocks_sha256=sha(data/'stocks.parquet'),files=list(items.values()),historical_names_included=True,not_current_active_only=True)
    temp=mp.with_suffix('.tmp');temp.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(mp)
    (HERE/'runtime/HISTORICAL_SCOPE_AUDIT.json').write_text(json.dumps(dict(historical_registry=len(u),added_to_chart=len(added),added_codes=added,scope='SH_SZ_MAIN_BOARD_ONLY',cutoff=meta['cutoff'],classification_is_current_snapshot=True),ensure_ascii=False,indent=2),encoding='utf8')
    print('chart_names',len(rows),'historical_added',len(added))

if __name__=='__main__':main()
