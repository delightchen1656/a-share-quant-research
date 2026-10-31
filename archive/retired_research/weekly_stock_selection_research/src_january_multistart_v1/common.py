from pathlib import Path
import json
import hashlib
from decimal import Decimal,ROUND_HALF_UP
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent
AUDIT=BASE/'audits/holdout_restricted/january_multistart_100k_v1'
SPEC=json.loads((AUDIT/'spec.json').read_text(encoding='utf-8'))
FACTORS=SPEC['factors']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p,value):
    Path(p).parent.mkdir(parents=True,exist_ok=True)
    normalized=json.loads(pd.Series([value]).to_json(orient='values',force_ascii=False,date_format='iso',double_precision=15))[0]
    Path(p).write_text(json.dumps(normalized,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def tick(x):
    return float(Decimal(str(float(x))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))


def fee(notional,side,date):
    date=pd.Timestamp(date)
    transfer=.00002 if date<pd.Timestamp('2022-04-29') else .00001
    stamp=(.001 if date<pd.Timestamp('2023-08-28') else .0005) if side=='sell' else 0.
    return max(5.,notional*.0003)+notional*(transfer+stamp)


def quote_valid(frame):
    numeric=frame[['open','high','low','close','volume','amount','preclose','pctChg']].apply(pd.to_numeric,errors='coerce')
    valid=frame.tradestatus.astype(str).eq('1')&np.isfinite(numeric).all(axis=1)&numeric.iloc[:,:7].gt(0).all(axis=1)&numeric.pctChg.gt(-100)
    return valid,numeric


def install_development_guard():
    import sys
    def audit(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,Path)):
            path=str(args[0]).replace('\\','/').lower()
            if 'restricted_audit_2025_2026' in path or 'posterior_review' in path:
                raise PermissionError('Account development cannot open posterior results')
    sys.addaudithook(audit)
