"""Local, replayable actual-broker ledger. Never infers executions from prices."""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager, closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
REVIEW_POLICY = 'cash_overwrite_first_v2'


def now():
    return datetime.now(TZ)


def add_days(value, days):
    return (datetime.fromisoformat(value) + timedelta(days=days)).date().isoformat()


def number(value, label, minimum=0):
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f'{label}不合法')
    return result


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS confirmations(day TEXT PRIMARY KEY, at TEXT NOT NULL, revision INTEGER NOT NULL, cash REAL NOT NULL, equity REAL NOT NULL)')
            if 'policy' not in {r['name'] for r in db.execute('PRAGMA table_info(confirmations)')}:
                db.execute("ALTER TABLE confirmations ADD COLUMN policy TEXT NOT NULL DEFAULT ''")
            db.execute('CREATE TABLE IF NOT EXISTS account_observations(id INTEGER PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, at TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL, cash REAL NOT NULL, equity REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS account_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO account_observations(source_key,at,day,kind,revision,cash,equity) SELECT 'legacy:'||day||':'||at,at,day,'legacy_review',revision,cash,equity FROM confirmations WHERE policy=''")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def events(self):
        with self.connect() as db:
            return [dict(r) | {'data': json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]

    def settings(self):
        with self.connect() as db:
            return {r['key']:json.loads(r['value']) for r in db.execute('SELECT key,value FROM account_settings')}

    def initial_cash(self):
        return float(self.settings().get('initial_cash',100000.0))

    def state(self, asof=None, events=None):
        day = asof or now().date().isoformat()
        cash = self.initial_cash()
        deferred = 0.0
        orders = {}
        positions = {}
        decisions = {}
        pending_cleanups = {}
        realized = 0.0
        for event in self.events() if events is None else events:
            if event['voided']:
                continue
            d, kind = event['data'], event['kind']
            if kind in ('accept', 'reject'):
                decisions[d['signal_id']] = kind
            if kind == 'accept':
                orders[d['signal_id']] = dict(d, filled=0, status='open', event_id=event['id'])
            elif kind == 'buy':
                order = orders[d['order_id']]
                if order['status'] != 'open':
                    raise ValueError('买单已结束，无法记入后续成交；请先冲正撤单记录')
                qty, price, fee = int(d['quantity']), float(d['price']), float(d['fee'])
                if qty + order['filled'] > order['quantity']:
                    raise ValueError('累计成交股数超过买单数量')
                cost = qty * price + fee
                cash -= cost
                order['filled'] += qty
                order['status'] = 'filled' if order['filled'] == order['quantity'] else 'open'
                p = positions.setdefault(order['symbol'], dict(symbol=order['symbol'], name=order.get('name',''), quantity=0, gross=0., cost=0., atr=order['atr'], entry_date=d['date'], protection=False, expiry_order=False, order_id=d['order_id']))
                if p['quantity'] <= 0:
                    p.update(quantity=0, gross=0., cost=0., entry_date=d['date'], atr=order['atr'], order_id=d['order_id'])
                if p['entry_date'] != d['date']:
                    raise ValueError('同一买单跨日分批成交将产生不同到期日，请先核对券商订单，勿合并为同一持仓')
                p['quantity'] += qty
                p['gross'] += qty * price
                p['cost'] += cost
                p['protection'] = False
                p['expiry_order'] = False
            elif kind == 'sell':
                p = positions[d['symbol']]
                qty = int(d['quantity'])
                if qty > p['quantity'] or d['date'] <= p['entry_date']:
                    raise ValueError('卖出股数超过持仓，或违反T+1')
                proceeds = qty * float(d['price']) - float(d['fee'])
                fraction = qty / p['quantity']
                realized += proceeds - p['cost'] * fraction
                p['cost'] *= 1-fraction
                p['gross'] *= 1-fraction
                p['quantity'] -= qty
                p['protection'] = False
                p['expiry_order'] = False
                if d['date'] < day:
                    cash += proceeds
                else:
                    deferred += proceeds
                pending_cleanups[d['symbol']] = True
            elif kind == 'cancel':
                if d['order_id'] not in orders:
                    raise ValueError('找不到对应买单')
                orders[d['order_id']]['status'] = 'cancelled'
            elif kind == 'protection':
                p = positions[d['symbol']]
                p['protection'] = True
            elif kind == 'expiry_order':
                positions[d['symbol']]['expiry_order'] = True
            elif kind == 'cleanup':
                pending_cleanups.pop(d['symbol'], None)
            elif kind == 'cash_adjust':
                cash += float(d['amount'])
        positions = {k:v for k,v in positions.items() if v['quantity'] > 0}
        for p in positions.values():
            p['average_price'] = p['gross'] / p['quantity']
            p['take'] = round(p['average_price'] * (1+4*p['atr']), 2)
            p['stop'] = round(p['average_price'] * (1-1.5*p['atr']), 2)
            p['deadline'] = add_days(p['entry_date'],30)
        active = {k:v for k,v in orders.items() if v['status']=='open'}
        occupied = set(positions) | {o['symbol'] for o in active.values()}
        # Conditional orders occupy slots, not cash. Only recorded fills debit cash.
        reserved = 0.0
        return dict(cash=round(cash,2), deferred=round(deferred,2), reserved=reserved, available=round(max(0,cash),2), orders=list(active.values()), all_orders=orders, positions=list(positions.values()), decisions=decisions, occupied=len(occupied), free_slots=max(0,5-len(occupied)), pending_cleanups=list(pending_cleanups), realized=round(realized,2))

    def append(self, kind, data, validate=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            events = [dict(r) | {'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
            if validate:
                validate(self.state(events=events))
            trial = dict(id=(events[-1]['id']+1 if events else 1), at=now().isoformat(), kind=kind, payload=json.dumps(data,ensure_ascii=False), data=data, voided=0)
            candidate = self.state(events=events+[trial])
            if candidate['cash'] < -0.01 or candidate['occupied'] > 5:
                raise ValueError('资金不足或超过5槽，请核对输入')
            db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',(trial['at'],kind,trial['payload']))

    def void(self, event_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            events = [dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
            target = next((e for e in events if e['id']==int(event_id)),None)
            if not target or target['voided']:
                raise ValueError('记录不存在或已冲正')
            target['voided']=1
            try:
                state=self.state(events=events)
            except (KeyError,ValueError) as exc:
                raise ValueError('存在依赖记录，请先冲正后续成交或确认记录') from exc
            if state['cash'] < -0.01 or state['occupied'] > 5:
                raise ValueError('冲正后资金或槽位不合法，请先冲正后续记录')
            db.execute('UPDATE events SET voided=1 WHERE id=?',(event_id,))

    def confirmation(self, day):
        with self.connect() as db:
            r=db.execute('SELECT * FROM confirmations WHERE day=?',(day,)).fetchone()
            return dict(r) if r else None

    def confirm(self, day, cash, equity):
        s=self.state()
        if abs(float(cash)-(s['cash']+s['deferred'])) > 0.05:
            raise ValueError(f"券商现金与账本不一致：账本为{s['cash']+s['deferred']:.2f}元。请补录成交、费用或资金调整后再核对。")
        with self.connect() as db:
            revision=db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            db.execute('INSERT OR REPLACE INTO confirmations(day,at,revision,cash,equity,policy) VALUES(?,?,?,?,?,?)',(day,now().isoformat(),revision,cash,equity,REVIEW_POLICY))

    def review_cash(self, day, cash, equity, expected_cash, expected_revision, flow_type, note):
        """Overwrite cash AND confirm atomically; never edits old financial events."""
        if flow_type not in ('external','reconciliation'):
            raise ValueError('请选择入出金或现金差额更正')
        stamp=now().isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            events=[dict(r)|{'data':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events ORDER BY id')]
            state=self.state(events=events)
            revision=events[-1]['id'] if events else 0
            current=round(state['cash']+state['deferred'],2)
            if abs(current-expected_cash)>.005 or revision!=expected_revision:
                raise ValueError('账户记录已变化，请刷新资金复核窗口后重新确认')
            amount=round(cash-current,2)
            if state['cash']+amount<-.01:
                raise ValueError('现金不能低于尚未释放的卖出款；请先核对成交和费用')
            if amount:
                payload=dict(amount=amount,date=day,note=note or '每日资金复核直接覆盖',source='daily_review',
                             previous_cash=current,target_cash=cash,flow_type=flow_type)
                cursor=db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',(stamp,'cash_adjust',json.dumps(payload,ensure_ascii=False)))
                revision=cursor.lastrowid
            db.execute('INSERT OR REPLACE INTO confirmations(day,at,revision,cash,equity,policy) VALUES(?,?,?,?,?,?)',
                       (day,stamp,revision,cash,equity,REVIEW_POLICY))

    def observe(self, key, day, kind, cash, equity):
        with self.connect() as db:
            revision=db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            db.execute('INSERT OR IGNORE INTO account_observations(source_key,at,day,kind,revision,cash,equity) VALUES(?,?,?,?,?,?,?)',
                       (key,now().isoformat(),day,kind,revision,cash,equity))

    def backup(self):
        folder=self.path.parent/'backups'
        folder.mkdir(exist_ok=True)
        target=folder/f"ledger_{now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
        with self.connect() as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        return target

    def backups(self):
        folder=self.path.parent/'backups'
        return [dict(name=p.name,bytes=p.stat().st_size) for p in sorted(folder.glob('ledger_*.sqlite3'),reverse=True)][:100]

    def restore(self,name):
        folder=(self.path.parent/'backups').resolve()
        source=(folder/name).resolve()
        if source.parent!=folder or not source.is_file() or not source.name.startswith('ledger_') or source.suffix!='.sqlite3':
            raise ValueError('备份文件不合法')
        with closing(sqlite3.connect(source)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('备份数据库损坏')
            db.execute('SELECT * FROM events LIMIT 1')
            db.execute('SELECT * FROM confirmations LIMIT 1')
        preserved=self.backup()
        with closing(sqlite3.connect(source)) as src, self.connect() as dst:
            src.backup(dst)
        return preserved
