"""Select the transaction that produced the current market metadata."""
from pathlib import Path
import json

MATCH_FIELDS=('status','target','updated_at','datasets','validation')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def select_commit(data, updates):
    data,updates=Path(data),Path(updates)
    if any(updates.glob('*/staging')):
        raise ValueError('发现行情暂存事务，请等待完整提交')
    refreshes=sorted((data/'metadata').glob('refresh_*.json'),reverse=True)
    if not refreshes:raise ValueError('缺少行情元数据刷新审计')
    refresh_path=refreshes[0];metadata=read(refresh_path)
    if metadata.get('status')!='ok':raise ValueError('当前行情元数据尚未成功提交')
    matches=[]
    for path in updates.glob('*/audit.json'):
        audit=read(path)
        if not all(audit.get(k)==metadata.get(k)for k in MATCH_FIELDS):continue
        if not audit.get('committed_files') or not audit.get('validation',{}).get('transactional_staging'):continue
        commit=path.parent/'commit_manifest.json'
        if not commit.is_file():continue
        manifest=read(commit)
        if manifest.get('target')!=metadata['target'] or len(manifest.get('files',[]))!=audit['committed_files']:continue
        matches.append((path,audit))
    if not matches:raise ValueError('未找到与当前行情元数据一致的正式事务提交审计')
    matches.sort(key=lambda item:str(item[0]))
    return matches[-1][0],matches[-1][1],refresh_path
