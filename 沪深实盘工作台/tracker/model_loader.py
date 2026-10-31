"""Verified, Unicode-safe frozen LightGBM model loading on Windows."""
from pathlib import Path
import hashlib
import re


def load_verified_model(path,expected_sha256,feature_names=None):
    """Pass verified text, not a filesystem path, across the native boundary."""
    path=Path(path)
    expected=str(expected_sha256 or '').lower()
    if not re.fullmatch(r'[0-9a-f]{64}',expected):
        raise ValueError(f'{path.stem}模型哈希清单无效')
    try:
        payload=path.read_bytes()
    except OSError as exc:
        raise ValueError(f'无法读取冻结模型 {path.name}：{exc}') from exc
    if hashlib.sha256(payload).hexdigest()!=expected:
        raise ValueError(f'{path.stem}模型哈希不一致')
    try:
        text=payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path.stem}冻结模型不是有效UTF-8文本') from exc
    import lightgbm as lgb
    try:
        model=lgb.Booster(model_str=text)
    except Exception as exc:
        raise ValueError(f'{path.stem}冻结模型解析失败：{exc}') from exc
    if feature_names is not None and model.feature_name()!=list(feature_names):
        raise ValueError(f'{path.stem}模型特征顺序不一致')
    return model
