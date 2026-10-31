"""Independent Hushen1 manual account. Never submits orders or infers fills."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import math
import sqlite3
import sys
import threading
import types
import uuid
import time
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import market
from store import now
from hushen1_performance import build as build_performance

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
SOURCE=ROOT/'沪深1研究/supermind_hushen_1.py'
ENTRY_SHA='a573941eb69f850536288ba5ce4333d943c2eb4862e7f3a518e46dd55cc653fd'
DEFAULT=HERE/'hushen1_data'


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(p)
def number(v,minimum=0):
    x=float(v)
    if not math.isfinite(x) or x<minimum:raise ValueError('金额或价格不合法')
    return x


class Desk:
    def __init__(self,folder=DEFAULT):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.path=self.folder/'ledger.sqlite3';self.lock=threading.RLock()
        self.running=False;self.progress='等待计算';self.error=''
        self._performance_cache=None
        self.config_path=self.folder/'config.json'
        if not self.config_path.exists():
            save(self.config_path,dict(strategy='沪深1',initial_cash=10000,created_date='2026-10-28',
                not_before='2026-10-29',entry_sha256=ENTRY_SHA,count=5,exposure=.98,interval=20,buffer=1.5,
                slippage_reference=.002,sale_cash='same_day',manual_execution=True,live_orders=False))
        self.config=read(self.config_path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,voided INTEGER NOT NULL DEFAULT 0)')
        # Copy the official future-calendar receipt, never another account's state.
        calendar=HERE/'data/calendar.json'
        if calendar.exists() and not (self.folder/'calendar.json').exists():
            (self.folder/'calendar.json').write_bytes(calendar.read_bytes())

    def connect(self):return sqlite3.connect(self.path,timeout=20)
    def events(self):
        with closing(self.connect()) as db:
            return [dict(id=r[0],at=r[1],kind=r[2],data=json.loads(r[3]),voided=bool(r[4]))
                for r in db.execute('SELECT id,at,kind,payload,voided FROM events ORDER BY id')]

    def account(self,events=None):
        cash=float(self.config['initial_cash']);positions={};realized=0.;fees=0.;flows=0.
        events=self.events() if events is None else events
        active=[x for x in events if not x['voided']]
        active.sort(key=lambda x:(x['data'].get('date',self.config['created_date']),x['id']))
        for ev in active:
            d=ev['data'];kind=ev['kind']
            if kind=='cash_adjust':cash+=d['amount'];flows+=d['amount']
            elif kind in ('buy','sell'):
                s=d['symbol'];q=d['quantity'];value=round(q*d['price'],4);fee=d['fee'];fees+=fee
                if kind=='buy':
                    if value+fee>cash+.005:raise ValueError('沪深1可用资金不足；请先录入真实卖出成交')
                    cash-=value+fee
                    p=positions.setdefault(s,dict(symbol=s,quantity=0,cost=0.,lots=[]))
                    p['quantity']+=q;p['cost']+=value+fee;p['lots'].append(dict(q=q,date=d['date']))
                else:
                    p=positions.get(s)
                    if not p or q>p['quantity']:raise ValueError('卖出超过沪深1持仓')
                    available=sum(l['q'] for l in p['lots'] if l['date']<d['date'] or l.get('available_on','9999')<=d['date'])
                    if q>available:raise ValueError('当天买入股份不能当天卖出（T+1）')
                    cost=p['cost']*q/p['quantity'];p['cost']-=cost;p['quantity']-=q
                    left=q
                    for lot in p['lots']:
                        if lot['date']>=d['date'] and lot.get('available_on','9999')>d['date']:continue
                        used=min(left,lot['q']);lot['q']-=used;left-=used
                    p['lots']=[l for l in p['lots'] if l['q']]
                    cash+=value-fee;realized+=value-fee-cost
                    if not p['quantity']:positions.pop(s)
            elif kind=='corporate':
                cash+=d['cash'];realized+=d['cash']
                if d['shares']:
                    p=positions.get(d['symbol'])
                    if not p:raise ValueError('股份调整缺少对应持仓')
                    p['quantity']+=d['shares'];p['lots'].append(dict(q=d['shares'],date=d['date'],available_on=d['date']))
            if cash<-.005:raise ValueError('重放后现金为负，不能保存该操作')
        return dict(cash=round(cash,4),positions=list(positions.values()),realized=round(realized,4),fees=round(fees,4),flows=round(flows,4))

    def backup(self):
        folder=self.folder/'backups';folder.mkdir(exist_ok=True)
        path=folder/(now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        with closing(self.connect()) as src,closing(sqlite3.connect(path)) as dst:src.backup(dst)
        return str(path)

    def signal(self):
        p=self.folder/'latest.json'
        if not p.exists():return None
        return read(self.folder/'signals'/read(p)['file'])

    def update(self):
        with self.lock:
            if self.running:return
            self.running=True;self.error='';self.progress='核验已提交行情'
        threading.Thread(target=self._update,daemon=True).start()

    def _update(self):
        try:
            h=market.health(self.folder);day=h['market_date']
            if day!=now().date().isoformat() and now().date().isoformat() in h['sessions'] and now().hour>=15:
                raise ValueError('今日交易行情尚未成功提交，不能生成今日收盘计划')
            if digest(SOURCE)!=self.config['entry_sha256']:raise ValueError('沪深1代码指纹改变，请核验后再使用')
            following=next((d for d in h['sessions'] if d>day),None)
            if not following:raise ValueError('缺少已核验的下一交易日')
            path=self.folder/'signals'/(day+'.json')
            if path.exists():
                old=read(path)
                if old['entry_sha256']!=digest(SOURCE) or old['audit_sha256']!=h['audit_sha256']:
                    raise ValueError('该日信号已冻结，输入指纹发生变化，禁止覆盖')
                save(self.folder/'latest.json',dict(file=path.name));self.progress='已复用当天冻结排名';return
            inventory=market.input_inventory()
            sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
            spec=importlib.util.spec_from_file_location('hushen1_manual_frozen',SOURCE)
            source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
            dates=pd.DatetimeIndex(pd.to_datetime([d for d in h['sessions'] if d<=day]))[-5:]
            meta=pd.read_csv(market.DATA/'metadata/historical_mainboard_universe.csv').set_index('symbol')
            members={str(d.date()):set(meta.index[(pd.to_datetime(meta.ipoDate)<=d)&(meta.outDate.isna()|(pd.to_datetime(meta.outDate)>d))]) for d in dates}
            wanted=set().union(*members.values());raw={};quotes={};inputs=[]
            files=sorted((market.DATA/'raw').glob('*/*.parquet'))
            for i,p in enumerate(files):
                if p.stem not in wanted or not source.mainboard(p.stem):continue
                x=pd.read_parquet(p);x.date=pd.to_datetime(x.date)
                if x.date.duplicated().any():raise ValueError('行情日期重复：'+p.stem)
                x=x.loc[x.date<=day].set_index('date').sort_index().tail(320)
                if x.empty:continue
                y=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'}).copy()
                y['is_paused']=1-pd.to_numeric(y.tradestatus)
                raw[p.stem]=y[source.FIELDS].astype(float)
                if day in x.index:
                    z=x.loc[day]
                    volume20=float(x.volume.astype(float).rolling(20).mean().iloc[-1])
                    quotes[p.stem]=dict(close=float(z.close),volume20=volume20 if math.isfinite(volume20) else 0.,
                        name=str(meta.loc[p.stem,'code_name']),is_st=bool(int(float(z.isST))),paused=int(z.tradestatus)!=1)
                inputs.append(dict(symbol=p.stem,sha256=digest(p)))
                if i%300==0:self.progress=f'沪深1行情 {i+1}/{len(files)}'
            self.progress='原四因子排名与5日平滑'
            ranks,info=source.compute_signals(raw,members,dates)
            if not ranks:raise ValueError('原规则无有效排名')
            if inventory!=market.input_inventory() or market._updater_running():raise ValueError('计算期间行情发生更新，信号未提交')
            signal=dict(asof=day,valid_for=following,entry_sha256=digest(SOURCE),audit_sha256=h['audit_sha256'],
                ranks=ranks,quotes=quotes,input_hashes=inputs,created_at=now().isoformat(),
                meaning='冻结排名，晚间股数仅按收盘价预估；开盘价格未知，不代表成交')
            save(path,signal);save(self.folder/'latest.json',dict(file=path.name));self.progress='沪深1次日计划已就绪'
        except Exception as ex:self.error=str(ex);self.progress='计算失败：'+str(ex)
        finally:self.running=False

    def plan(self,account,signal,prices=None):
        if not signal:return dict(rows=[],selected=[],due=False,message='请先计算沪深1排名')
        sessions=market.calendar_extended(self.folder);day=signal['valid_for']
        completed=[d for d in sessions if '2018-01-01'<=d<day]
        accepted=[e for e in self.events() if e['kind']=='plan' and not e['voided'] and e['data']['date']<=day]
        first=not accepted and not any(e['kind']=='buy' and not e['voided'] for e in self.events())
        due=first or (len(completed)-1)%20==0
        due=due and day>=self.config['not_before']
        positions={p['symbol']:p for p in account['positions']};quotes=signal['quotes']
        prices=prices or {}
        def price(s):return float(prices.get(s,quotes.get(s,{}).get('close',0)))
        nav=account['cash']+sum(p['quantity']*price(s) for s,p in positions.items())
        budget=nav*.98/5
        def cost(q,op):
            unit=math.ceil(op*1.002*100-1e-8)/100;value=q*unit
            return value+max(5,value*.0003)
        def selectable(s):
            q=quotes.get(s,{})
            return price(s)>0 and not q.get('is_st',True) and not q.get('paused',True) and cost(100,price(s))<=budget
        selected=[s for s in signal['ranks'] if s in positions and s in signal['ranks'][:7] and selectable(s)][:5]
        for s in signal['ranks']:
            if len(selected)==5:break
            if s not in selected and selectable(s):selected.append(s)
        targets={s:0 for s in positions if s not in selected}
        if accepted and accepted[-1]['data']['date']==day:
            targets=accepted[-1]['data']['targets']
            selected=[s for s,q in targets.items() if q>0]
        elif due:targets.update({s:int(budget/price(s)//100)*100 for s in selected})
        else:
            # Unfilled targets stay immutable until the next rebalance.
            targets=accepted[-1]['data']['targets'] if accepted else {s:p['quantity'] for s,p in positions.items()}
        rows=[];cash_budget=account['cash']
        for s in sorted(targets,key=lambda s:(targets[s]-positions.get(s,{}).get('quantity',0)>=0,s)):
            current=positions.get(s,{}).get('quantity',0);delta=targets[s]-current
            op=price(s);volume=quotes.get(s,{}).get('volume20',0)
            cap=int(volume*.005//100)*100 if math.isfinite(volume) else 0
            quantity=min(abs(delta),cap,1000000)
            if delta>0:
                quantity=int(quantity//100)*100
                while quantity>0 and cost(quantity,op)>cash_budget:quantity-=100
                if quantity:cash_budget-=cost(quantity,op)
            else:
                available=sum(l['q'] for l in positions.get(s,{}).get('lots',[]) if l['date']<day or l.get('available_on','9999')<=day)
                quantity=min(quantity,available)
                if quantity!=current:quantity=int(quantity//100)*100
            rows.append(dict(symbol=s,name=quotes.get(s,{}).get('name',s),side='买入' if delta>0 else '卖出' if delta<0 else '持有',
                current=current,target=targets[s],quantity=quantity,reference_price=op,
                limit_reference=round(math.ceil(op*1.002*100-1e-8)/100 if delta>0 else math.floor(op*.998*100+1e-8)/100,2),
                reference_amount=round(quantity*op,2)))
        return dict(date=day,due=due,first=first,rows=rows,selected=selected,targets=targets,nav=round(nav,2),budget=round(budget,2),
            message='调仓 / 首次建仓：先卖出确认到账，再买入；股数须按实际开盘价复核' if due else '非调仓日：只处理已保存目标的未完成部分',
            is_opening_plan=bool(prices),cash=account['cash'])

    def performance(self):
        # Polls never read a market transaction in progress. Health and price
        # stats are rechecked periodically; fills/corrections invalidate at once.
        events=self.events();revision=tuple((e['id'],e['voided']) for e in events)
        cached=self._performance_cache
        if cached and cached[0]==revision and time.monotonic()-cached[1]<30:return cached[2]
        try:
            h=market.health(self.folder)
            inventory=market.input_inventory()
            end=h['market_date'];clock=now()
            if end>=clock.date().isoformat() and clock.hour<15:
                end=max((d for d in h['sessions'] if d<clock.date().isoformat()),default=self.config['created_date'])
            result=build_performance(self,h['sessions'],end,market.DATA,clock.date().isoformat())
            if market._updater_running() or inventory!=market.input_inventory():raise ValueError('收盘估值期间行情正在更新，请稍后重试')
        except Exception as ex:
            result=dict(daily=[],curve=[],asof=None,today=now().date().isoformat(),calendar_sessions=[],unknown_cash_adjustments=[],error=str(ex))
        self._performance_cache=(revision,time.monotonic(),result)
        return result

    def snapshot(self):
        with self.lock:
            a=self.account();sig=self.signal();quotes=sig['quotes'] if sig else {}
            for p in a['positions']:
                q=quotes.get(p['symbol']);p['name']=q['name'] if q else p['symbol']
                p['close']=q['close'] if q else None;p['average_cost']=p['cost']/p['quantity']
                p['market_value']=p['quantity']*p['close'] if p['close'] is not None else None
                p['unrealized']=p['market_value']-p['cost'] if p['market_value'] is not None else None
            valued=all(p['market_value'] is not None for p in a['positions'])
            equity=a['cash']+sum(p['market_value'] for p in a['positions']) if valued else None
            plan=self.plan(a,sig)
            a.update(config=self.config,equity=equity,signal_date=sig['asof'] if sig else None,
                plan=plan,events=list(reversed(self.events())),running=self.running,progress=self.progress,error=self.error,
                candidates=[dict(symbol=s,rank=i+1,**sig['quotes'].get(s,{})) for i,s in enumerate(sig['ranks'])] if sig else [],
                today=now().date().isoformat(),account_id='hushen1',source_verified=digest(SOURCE)==self.config['entry_sha256'])
            a['performance']=self.performance()
            closing=a['performance']['daily'][-1] if a['performance']['daily'] else None
            if closing:
                for p in a['positions']:
                    mark=closing['marks'].get(p['symbol'])
                    if mark is not None:
                        p.update(close=mark,market_value=p['quantity']*mark,unrealized=p['quantity']*mark-p['cost'],valuation_date=closing['day'])
                    elif closing['day']>=(sig['asof'] if sig else ''):
                        p.update(close=None,market_value=None,unrealized=None,valuation_date=closing['day'])
                a['equity']=a['cash']+sum(p['market_value'] for p in a['positions']) if all(p['market_value'] is not None for p in a['positions']) else None
            a['revision']=max([e['id'] for e in a['events']]+[0])
            for row in a['plan'].get('rows',[]):
                row['rank']=sig['ranks'].index(row['symbol'])+1 if sig and row['symbol'] in sig['ranks'] else None
            if sig:
                for p in a['positions']:
                    if p['symbol'] not in sig['ranks']:
                        a['candidates'].append(dict(symbol=p['symbol'],rank='已有持仓',**quotes.get(p['symbol'],{})))
            return a

    def batch_preview(self,d):
        """Only actual-price entry; quantities default to the visible plan.

        Acknowledgement of these quantities is required before committing.
        Prices are actual fills: no additional slippage is charged here.
        """
        events=self.events();revision=max([e['id'] for e in events]+[0])
        if int(d.get('revision',-1))!=revision:raise ValueError('账户记录已变化，请刷新后重新预览')
        sig=self.signal();account=self.account(events);plan=self.plan(account,sig)
        date=d.get('date',now().date().isoformat())
        if not sig or date!=plan.get('date'):raise ValueError('简易录入只对应当前计划执行日；补录旧成交请用完整录入')
        if date<self.config['not_before'] or date>now().date().isoformat():raise ValueError('尚未到计划执行日，不能提前记成交')
        if date not in market.calendar_extended(self.folder):raise ValueError('该日不是已核验交易日')
        fills=d.get('fills',[])
        if not fills:raise ValueError('至少填写一只已实际成交股票的价格')
        if len(fills)>20:raise ValueError('单次记录过多')
        if len({f['symbol'] for f in fills})!=len(fills):raise ValueError('同一股票不能重复填写')
        rows={r['symbol']:r for r in plan['rows']}
        if any(f['symbol'] not in rows for f in fills):raise ValueError('所填股票不属于当前目标；实际计划外成交请完整录入')
        fills=sorted(fills,key=lambda f:(rows[f['symbol']]['side']!='卖出',f['symbol']))
        virtual=list(events);pending=[];preview=[]
        next_id=revision
        accepted=any(e['kind']=='plan' and not e['voided'] and e['data']['date']==date for e in events)
        if not accepted:
            next_id+=1
            ev=dict(id=next_id,at=now().isoformat(),kind='plan',voided=False,
                data=dict(date=date,targets=plan['targets'],signal_date=sig['asof'],
                    quantity_basis='existing_visible_reference_plan',
                    reference_prices={r['symbol']:r['reference_price'] for r in plan['rows']}))
            pending.append(ev);virtual.append(ev)
        for f in fills:
            s=f['symbol'];r=rows[s];side=r['side']
            if side not in ('买入','卖出'):raise ValueError('该股票当前没有待完成买卖数量')
            price=number(f['price'],.001)
            q=min(abs(r['target']-r['current']),1000000)
            volume=sig['quotes'].get(s,{}).get('volume20',0)
            q=min(q,int(volume*.005//100)*100)
            current=self.account(virtual)
            held=next((p for p in current['positions'] if p['symbol']==s),None)
            if side=='卖出':
                available=sum(l['q'] for l in (held or {}).get('lots',[]) if l['date']<date or l.get('available_on','9999')<=date)
                q=min(q,available)
                if q!=(held or {}).get('quantity',0):q=int(q//100)*100
            else:q=int(q//100)*100
            def estimate(qty):
                value=round(qty*price,2)
                return round(max(5,value*.0003),2)+(round(value*.001,2) if side=='卖出' else 0.)
            override_qty=f.get('quantity') not in (None,'')
            if override_qty:
                actual=number(f['quantity'],1)
                if not actual.is_integer() or actual>q:raise ValueError(s+'实际股数超过待完成目标或成交量上限，请核对')
                q=int(actual)
                if side=='买入' and q%100:raise ValueError('买入必须是100股整数手')
                if side=='卖出' and q%100 and q!=(held or {}).get('quantity'):raise ValueError('非清仓卖出须为整手')
            override_fee=f.get('fee') not in (None,'')
            while side=='买入' and q>0:
                fee=number(f['fee']) if override_fee else estimate(q)
                if round(q*price,4)+fee<=current['cash']+.005:break
                if override_qty:raise ValueError(s+'所填实际成交超出本账户现金，请先核对现金或记录卖出')
                q-=100
            if q<=0:raise ValueError(s+'当前可用现金或可卖股数不足，不能确认成交')
            fee=number(f['fee']) if override_fee else estimate(q)
            next_id+=1
            ev=dict(id=next_id,at=now().isoformat(),kind='buy' if side=='买入' else 'sell',voided=False,
                data=dict(date=date,symbol=s,quantity=q,price=price,fee=fee,
                    reference=str(f.get('reference','')).strip(),fee_source='broker_actual' if override_fee else 'estimated_policy',
                    quantity_source='user_override' if override_qty else 'plan_confirmed_by_user'))
            ref=ev['data']['reference']
            if ref and any(e['data'].get('reference')==ref and not e['voided'] for e in virtual):raise ValueError('券商成交编号已录入')
            self.account(virtual+[ev]);pending.append(ev);virtual.append(ev)
            preview.append(dict(symbol=s,name=r['name'],side=side,quantity=q,price=price,
                amount=round(q*price,2),fee=fee,fee_estimated=not override_fee))
        final=self.account(virtual)
        signature=hashlib.sha256(json.dumps(dict(revision=revision,date=date,targets=plan['targets'],rows=preview),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        return dict(revision=revision,date=date,rows=preview,cash_after=final['cash'],signature=signature,
            pending_events=pending,quantity_note='默认股数来自当前可见目标计划；若未提供实际开盘价，它仍是收盘价预案。须确认与券商已成交股数一致。',
            fee_note='未填写实际费用时使用佣金万三最低5元、卖出印花税0.1%的估算；成交价不再叠加滑点。')

    def action(self,kind,d):
        with self.lock:
            if kind in ('batch_preview','batch_fill'):
                preview=self.batch_preview(d)
                if kind=='batch_preview':return {k:v for k,v in preview.items() if k!='pending_events'}
                if not d.get('attested'):raise ValueError('请确认实际成交股数与预览一致；部分成交请修改股数')
                if d.get('signature')!=preview['signature']:raise ValueError('预览已变化，请重新核对股数后确认')
                # Validate every fill first; commit the target and all fills atomically.
                self.backup()
                with self.connect() as db:
                    for ev in preview['pending_events']:
                        db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',(ev['at'],ev['kind'],json.dumps(ev['data'],ensure_ascii=False)))
                return self.snapshot()
            if kind=='backup':return dict(path=self.backup())
            if kind=='preview':
                prices={s:number(v,.001) for s,v in d.get('prices',{}).items() if v not in ('',None)}
                return self.plan(self.account(),self.signal(),prices)
            events=self.events();today=now().date().isoformat()
            if kind=='void':
                event_id=int(d['id']);new=[dict(e,voided=True) if e['id']==event_id else e for e in events]
                if new==events:raise ValueError('记录不存在或已冲正')
                self.account(new);self.backup()
                with self.connect() as db:db.execute('UPDATE events SET voided=1 WHERE id=?',(event_id,))
                return self.snapshot()
            date=d.get('date',today)
            if date<self.config['not_before'] or date>today:raise ValueError('只能录入开始日期起、今天及以前的实际记录')
            if date not in market.calendar_extended(self.folder):raise ValueError('该日不是已核验交易日')
            if kind in ('buy','sell'):
                s=d['symbol'];sig=self.signal()
                if not sig or s not in sig['quotes']:raise ValueError('股票缺少已核验行情')
                q=number(d['quantity'],1)
                if not q.is_integer():raise ValueError('股数必须为整数')
                q=int(q)
                if kind=='buy' and q%100:raise ValueError('买入必须是100股整数手')
                holdings={p['symbol']:p for p in self.account()['positions']}
                if kind=='sell' and q%100 and q!=holdings.get(s,{}).get('quantity'):raise ValueError('非清仓卖出须为整手')
                ref=str(d.get('reference','')).strip()
                if ref and any(e['data'].get('reference')==ref and not e['voided'] for e in events):raise ValueError('该成交编号已录入')
                d=dict(date=date,symbol=s,quantity=q,price=number(d['price'],.001),fee=number(d.get('fee',0)),reference=ref,fee_source='broker_actual')
            elif kind=='cash_adjust':
                amount=float(d['amount'])
                if not math.isfinite(amount) or not str(d.get('note','')).strip():raise ValueError('请填写有效金额和说明')
                flow_type=d.get('flow_type','unknown')
                if flow_type not in ('external','reconciliation','unknown'):raise ValueError('资金调整归属无效')
                d=dict(date=date,amount=amount,note=d['note'],flow_type=flow_type)
            elif kind=='classify_cash':
                event_id=int(d['event_id']);flow_type=d['flow_type']
                if flow_type not in ('external','reconciliation'):raise ValueError('资金调整归属无效')
                if not any(e['id']==event_id and e['kind']=='cash_adjust' and not e['voided'] for e in events):raise ValueError('资金记录不存在')
                d=dict(date=date,event_id=event_id,flow_type=flow_type)
            elif kind=='corporate':
                shares=number(d.get('shares',0))
                if not shares.is_integer():raise ValueError('到账股份必须是整数')
                if not str(d.get('note','')).strip():raise ValueError('请填写券商到账或股份调整说明')
                d=dict(date=date,symbol=d['symbol'],cash=number(d.get('cash',0)),shares=int(shares),note=d['note'])
            elif kind=='plan':
                sig=self.signal()
                if not sig or date!=sig['valid_for']:raise ValueError('只能确认当前冻结信号的执行日计划')
                p=self.action('preview',d)
                if not p['is_opening_plan']:raise ValueError('请录入实际开盘价再确认目标')
                needed=set(p['selected'])|{x['symbol'] for x in self.account()['positions']}
                if not needed.issubset(d['prices']):raise ValueError('请填齐目标股和已有持仓的实际开盘价')
                if any(e['kind']=='plan' and e['data']['date']==date and not e['voided'] for e in events):raise ValueError('该执行日目标已冻结，不能重复确认')
                d=dict(date=date,targets=p['targets'],prices=d['prices'],signal_date=sig['asof'])
            else:raise ValueError('未知沪深1操作')
            candidate=dict(id=max([e['id'] for e in events]+[0])+1,at=now().isoformat(),kind=kind,data=d,voided=False)
            self.account(events+[candidate]);self.backup()
            with self.connect() as db:db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',(candidate['at'],kind,json.dumps(d,ensure_ascii=False)))
            return self.snapshot()
