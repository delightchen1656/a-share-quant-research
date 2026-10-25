from pathlib import Path
import json,socket,time
import pandas as pd
BASE=Path(__file__).resolve().parent/'data'
HERE=BASE
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))

def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8');tmp.replace(p)

class Actions:
    """Fetch only missing stock-year events actually encountered by held shares."""
    def __init__(self,end):
        self.end=end;self.cache={};self.own=HERE/'additional_actions.json';self.connected=False;self.lookup={}
        paths=set(BASE.rglob('actions_*.json'))|set(BASE.rglob('action_part_*.json'))|set(BASE.rglob('additional_actions.json'))
        for p in sorted(paths):
            # Files are response caches, never result/ranking files.
            self.cache.update(read(p))
        self.extra=read(self.own) if self.own.exists() else {}
    def ensure(self,s,date):
        key=s+'/'+str(date.year)
        if key not in self.cache:
            import baostock as bs
            socket.setdefaulttimeout(35)
            if not self.connected:
                assert bs.login().error_code=='0';self.connected=True
            for attempt in range(4):
                try:
                    result=bs.query_dividend_data(code=s[-2:].lower()+'.'+s[:6],year=str(date.year),yearType='operate')
                    rows=[]
                    while result.error_code=='0' and result.next():rows.append(result.get_row_data())
                    if result.error_code!='0':raise RuntimeError(result.error_msg)
                    records=pd.DataFrame(rows,columns=result.fields).to_dict('records');break
                except Exception:
                    if attempt==3:raise
                    time.sleep(1);bs.login()
            self.cache[key]=records;self.extra[key]=records;dump(self.own,self.extra)
            if len(self.extra)%10==0:print('ACTION_RESPONSES',len(self.extra),flush=True)
        if key not in self.lookup:
            def num(x):return float(x) if str(x).strip() else 0.
            events={}
            for r in self.cache[key]:
                if not r['dividOperateDate']:continue
                d=pd.Timestamp(r['dividOperateDate'])
                if d>self.end:continue
                events[d]=dict(cash=num(r['dividCashPsBeforeTax']),stock=num(r['dividStocksPs'])+num(r['dividReserveToStockPs']),
                    taxable_stock=num(r['dividStocksPs']),pay=pd.Timestamp(r['dividPayDate'] or r['dividOperateDate']),
                    release=pd.Timestamp(r['dividStockMarketDate'] or r['dividOperateDate']))
            self.lookup[key]=events
        return self.lookup[key].get(date)
    def close(self):
        if self.connected:
            import baostock as bs
            bs.logout();self.connected=False
