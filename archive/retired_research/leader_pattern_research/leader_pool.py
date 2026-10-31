"""Verified frozen union of the user's original pool and the selected THS F10 field."""
from pathlib import Path
import json,hashlib
import pandas as pd

HERE=Path(__file__).resolve().parent
CURRENT=HERE/'leader_pools/holdout_restricted/CURRENT.json'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_pool():
    pointer=json.loads(CURRENT.read_text(encoding='utf-8'))
    manifest_path=Path(pointer['manifest'])
    assert sha(manifest_path)==pointer['manifest_sha256'],'Leader membership manifest changed'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    assert sha(manifest['all_path'])==manifest['all_sha256']
    frame=pd.read_parquet(manifest['all_path'])
    assert frame.code.is_unique and frame.is_original_leader.combine(frame.is_ths_leader,lambda a,b:a or b).all()
    return frame,dict(path=str(manifest_path),sha256=pointer['manifest_sha256'],**manifest)

def membership(code,lookup):
    row=lookup.get(code)
    if row is None:return dict(is_leader=False,is_original_leader=False,is_ths_leader=False,leader_source='')
    return dict(is_leader=True,is_original_leader=bool(row['is_original_leader']),
        is_ths_leader=bool(row['is_ths_leader']),leader_source=row['leader_source'])
