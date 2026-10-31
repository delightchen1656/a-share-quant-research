"""Boundary-only market adapter. Does not read anything outside explicitly verified cache.
Ordinary daily limit assumptions are reported; crossing an implied lower limit blocks.
"""
from functools import lru_cache
from decimal import Decimal
import numpy as np
from account_engine import Bar,money
class CodeBars:
 def __init__(self,raw,code,exceptions):self.r=raw;self.code=code;self.exceptions=exceptions
 @lru_cache(maxsize=2048)
 def get(self,day,default=None):
  if day not in self.r.index:return default
  z=self.r.loc[day]
  if not np.isfinite(float(z.open)) or float(z.open)<=0:
   if str(z.tradestatus) in ['0','0.0']:return Bar(0,0,0,0,tradestatus=0)
   return default
  pre=float(z.preclose);st=int(float(z.isST));lim=Decimal('.05') if st else Decimal('.10')
  evidence='whitelisted_raw_preclose_isST_ordinary_limit_assumption';no_limit=False
  for x in self.exceptions:
   if x['code']==self.code and x['start']<=day<=x['end']:
    evidence=x['evidence'];no_limit=x['no_price_limit']
    if x.get('limit_rate') is not None:lim=Decimal(str(x['limit_rate']))
  lower=money(Decimal(str(pre))*(1-lim)) if pre>0 else None;upper=money(Decimal(str(pre))*(1+lim)) if pre>0 else None
  if no_limit:lower=None;upper=None
  return Bar(z.open,z.high,z.low,z.close,int(float(z.tradestatus)),z.volume,lower_limit=lower,upper_limit=upper,no_price_limit=no_limit,limit_evidence=evidence)
class CodeFactors:
 def __init__(self,raw,q):self.values=(q.close/raw.close).to_dict()
 def get(self,day,default=None):
  f=self.values.get(day)
  return float(f) if f is not None and np.isfinite(f) and f>0 else default

def build(data):
 import pathlib,json,hashlib
 base=pathlib.Path('研究尝试/方向1_超跌反弹/inputs_pre2025/execution_rules_2020_2024/market_evidence_v1');manifest=base/'MANIFEST.json'
 assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='449207aacc569ee06d4b49c578f35ab07f48589c27e66b2f48f73ee8d3d55d15'
 m=json.loads(manifest.read_text(encoding='utf-8-sig'))
 for x in m['files']:assert hashlib.sha256((base/x['path']).read_bytes()).hexdigest()==x['sha256']
 exceptions=json.loads((base/'DAILY_LIMIT_EXCEPTIONS.json').read_text(encoding='utf-8-sig'))
 bars={};factors={}
 for code,(r,q) in data.items():bars[code]=CodeBars(r,code,exceptions);factors[code]=CodeFactors(r,q)
 return bars,factors
