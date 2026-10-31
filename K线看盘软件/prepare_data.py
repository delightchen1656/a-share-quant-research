"""Copy only validated chart prices/metadata; never import legacy research."""

import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
from pathlib import Path
import hashlib,json,shutil
import pandas as pd
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    pointer=ROOT/'archive/retired_research/leader_pattern_research/market_wide/holdout_restricted/CURRENT.json'
    old=json.loads(pointer.read_text(encoding='utf8'));source=resolve_recorded_path(old['manifest'])
    assert old['status']=='ok' and old['scope']=='SH_SZ_MAIN_BOARD_ONLY'
    assert sha(source)==old['manifest_sha256']
    ufile=resolve_recorded_path(old['universe']);assert sha(ufile)==old['universe_sha256']
    u=pd.read_parquet(ufile)
    assert u.code.is_unique and u.code.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
    data=HERE/'data';(data/'qfq').mkdir(parents=True,exist_ok=True)
    u[['code','name','is_leader','leader_source']].sort_values('code').to_parquet(data/'stocks.parquet',index=False)
    m=json.loads(source.read_text(encoding='utf8'));items=[]
    for item in m['files']:
        if item['mode']!='qfq':continue
        src=resolve_recorded_path(item['path']);target=data/'qfq'/(item['code']+'.parquet')
        assert item.get('ok',True) and sha(src)==item['snapshot_sha256']
        if not target.exists():shutil.copy2(src,target)
        assert sha(target)==item['snapshot_sha256']
        items.append(dict(code=item['code'],path='qfq/'+target.name,sha256=sha(target)))
    assert len(items)==len(u)
    out=dict(app='hushen-basic-kline-viewer',cutoff=old['cutoff'],scope='SH_SZ_MAIN_BOARD_ONLY',stocks=len(u),price_basis='前复权',volume_source_unit='股',
        stocks_sha256=sha(data/'stocks.parquet'),files=items,source_manifest_sha256=old['manifest_sha256'],
        leader_note='★为原龙头与同花顺F10合并名单的快照标记，不是历史时点归属',automatic_refresh=False)
    (data/'MANIFEST.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(stocks=len(u),cutoff=old['cutoff'],independent_data=True),ensure_ascii=False))
if __name__=='__main__':main()
