"""Read-only SSE chart export and close-only10% reversal classification."""
from pathlib import Path
import hashlib
import json
import math
from functools import lru_cache

ROOT=Path(__file__).resolve().parent.parent/'K线数据/指数/上证看盘'


def reversals(bars,threshold=.10):
    mode=None;low=high=None;low_day=high_day=None;events=[]
    for b in bars:
        day,close=b['date'],float(b['close'])
        if not math.isfinite(close) or close<=0:raise ValueError('Invalid SSE close')
        if mode is None:
            if low is None or close<low:low=close;low_day=day
            if high is None or close>high:high=close;high_day=day
            if close>=low*(1+threshold)-1e-9:
                mode='bull';events.append(dict(mode=mode,confirmed=day,pivot=low_day,pivot_close=low,confirm_close=close));high=close;high_day=day
            elif close<=high*(1-threshold)+1e-9:
                mode='bear';events.append(dict(mode=mode,confirmed=day,pivot=high_day,pivot_close=high,confirm_close=close));low=close;low_day=day
        elif mode=='bull':
            if close>high:high=close;high_day=day
            if close<=high*(1-threshold)+1e-9:
                mode='bear';events.append(dict(mode=mode,confirmed=day,pivot=high_day,pivot_close=high,confirm_close=close));low=close;low_day=day
        else:
            if close<low:low=close;low_day=day
            if close>=low*(1+threshold)-1e-9:
                mode='bull';events.append(dict(mode=mode,confirmed=day,pivot=low_day,pivot_close=low,confirm_close=close));high=close;high_day=day
    return events


@lru_cache(maxsize=2)
def _load(relative,expected):
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('Invalid SSE export path')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('上证导出指纹不一致')
    result=json.loads(raw)
    if result['code']!='000001.SH' or result['threshold']!=.10:raise ValueError('上证标注规则不一致')
    return result


def history():
    pointer=ROOT/'CURRENT.json'
    if not pointer.exists():raise ValueError('上证牛熊数据尚未导出')
    meta=json.loads(pointer.read_text(encoding='utf-8'))
    return _load(meta['path'],meta['sha256'])
