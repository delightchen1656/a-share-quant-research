from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timedelta
from pathlib import Path

from store import Ledger, now, number, add_days
import market

HERE=Path(__file__).resolve().parent
DATA=HERE/'data'


class Tracker:
    def __init__(self,folder=DATA):
        self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True)
        self.ledger=Ledger(self.folder/'ledger.sqlite3')
        self.lock=threading.RLock()
        self.running=False
        self.info=self.read_info()

    def read_info(self):
        path=self.folder/'market_status.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'waiting','message':'尚未更新，请点击更新本地数据','signals':[]}

    def save_info(self):
        path=self.folder/'market_status.json'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.info,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)

    def cycle(self):
        clock=now()
        day=clock.date()
        if clock.hour<9 or (clock.hour==9 and clock.minute<30): day-=timedelta(days=1)
        return day.isoformat()

    def sessions(self):
        return market.calendar_extended(self.folder)

    def next_session(self,day):
        return next((d for d in self.sessions() if d>day),None)

    def exit_session(self,deadline):
        sessions=self.sessions()
        if not sessions or sessions[-1]<deadline: return None
        return max((d for d in sessions if d<=deadline),default=None)

    def update(self,background=True):
        with self.lock:
            if self.running: return
            self.running=True
        def work():
            try:
                # Expire only unhandled recommendations; never cancel broker orders.
                with self.lock:
                    decisions=self.ledger.state()['decisions']
                    for sig in self.info.get('signals',[]):
                        if sig['signal_date']<self.cycle() and sig['id'] not in decisions:
                            self.ledger.append('reject',{'signal_id':sig['id'],'automatic':True})
                try: market.refresh_calendar(self.folder)
                except Exception as exc: calendar_warning=str(exc)
                else: calendar_warning=''
                h=market.health(self.folder)
                with self.lock:
                    self.info=dict(self.info,market_date=h['market_date'],audit=h['audit'])
                expected=max((d for d in h['sessions'] if d<=self.cycle()),default=None)
                if h['market_date']!=expected:
                    raise ValueError(f"行情尚未提交：需要{expected}，最近成功数据为{h['market_date']}，请等待18点行情任务完成后重试")
                cache=market.signal_cache_path(self.folder,h['market_date'])
                pipeline_id,_=market.pipeline_identity(h)
                if cache.exists():
                    frozen=json.loads(cache.read_text(encoding='utf-8'))
                    if not isinstance(frozen,dict) or frozen.get('pipeline_id')!=pipeline_id:
                        raise ValueError('当日冻结信号缺少来源或与当前行情/模型不一致，已停止；保留原件待核查，不自动覆盖')
                    if frozen.get('market_date')!=h['market_date']: raise ValueError('冻结信号日期不一致')
                    if frozen.get('signal_filter_policy')!=market.SIGNAL_FILTER_POLICY_ID: raise ValueError('冻结信号ATR筛选政策不一致')
                    signals=frozen['signals']
                    if frozen.get('signals_sha256')!=market.signals_digest(signals): raise ValueError('冻结信号内容校验失败，保留原件待核查')
                    market.validate_signals(signals,h)
                else:
                    signals=market.predict(self.folder,h)
                    market.validate_signals(signals,h)
                    frozen={'schema_version':2,'market_date':h['market_date'],'pipeline_id':pipeline_id,'signals_sha256':market.signals_digest(signals),'created_at':now().isoformat(),'signals':signals,'signal_filter_policy':market.SIGNAL_FILTER_POLICY_ID}
                    with cache.open('x',encoding='utf-8') as stream:
                        stream.write(json.dumps(frozen,ensure_ascii=False,indent=2))
                final_health=market.health(self.folder)
                if market.pipeline_identity(final_health)[0]!=pipeline_id:
                    raise ValueError('冻结后行情或模型发生变化，暂停展示待重新核验')
                with self.lock:
                    # Unhandled recommendations from older sessions expire once, preserving audit history.
                    previous=self.info.get('signals',[])
                    decisions=self.ledger.state()['decisions']
                    for s in previous:
                        if s['signal_date']<h['market_date'] and s['id'] not in decisions:
                            self.ledger.append('reject',{'signal_id':s['id'],'automatic':True})
                    self.info={'status':'ready','market_date':h['market_date'],'updated_at':now().isoformat(),'message':'行情、冻结模型与ATR≥2.5%筛选已校验，等待账户核对后开放推荐','signals':signals,'audit':h['audit'],'pipeline_id':pipeline_id,'calendar_warning':calendar_warning,'signal_filter_policy':market.SIGNAL_FILTER_POLICY_ID}
                    self.save_info()
            except Exception as exc:
                with self.lock:
                    self.info=dict(self.info,status='blocked',message=str(exc),attempted_at=now().isoformat())
                    self.save_info()
            finally:
                with self.lock: self.running=False
        if background: threading.Thread(target=work,daemon=True).start()
        else: work()

    def snapshot(self):
        with self.lock:
            state=self.ledger.state()
            cycle=self.cycle()
            clock=now();today=clock.date().isoformat()
            confirm=self.ledger.confirmation(cycle)
            sessions=self.sessions()
            expected=max((d for d in sessions if d<=cycle),default=None)
            market_ready=self.info.get('status')=='ready' and self.info.get('market_date')==expected and self.info.get('signal_filter_policy')==market.SIGNAL_FILTER_POLICY_ID
            confirmed=bool(confirm)
            following=self.next_session(cycle)
            marks=market.raw_marks([p['symbol'] for p in state['positions']],self.info.get('market_date',cycle))
            equity=state['cash']+state['deferred']
            tasks=[];manual_exit_alerts=[]
            if not confirmed: tasks.append(dict(id='review',type='review',title='核对今日账户',detail='录入国金成交后，确认挂单、持仓与现金',priority='high'))
            if not market_ready: tasks.append(dict(id='data',type='data',title='行情 / 模型待就绪',detail=self.info.get('message','等待更新'),priority='high'))
            for p in state['positions']:
                p['mark']=marks.get(p['symbol'])
                p['value']=p['quantity']*(p['mark']['price'] if p['mark'] else p['average_price'])
                p['pnl']=p['value']-p['cost']
                equity+=p['value']
                p['earliest_sell']=self.next_session(p['entry_date'])
                p['exit_session']=self.exit_session(p['deadline'])
                p['manual_exit_date']=self.next_session(p['exit_session']) if p['exit_session'] else None
                if not p['protection']: tasks.append(dict(id='protect_'+p['symbol'],type='protection',symbol=p['symbol'],title=f"{p['name']} · 设置止盈止损",detail=f"止盈 {p['take']:.2f} / 止损 {p['stop']:.2f} · {p['quantity']}股",priority='high'))
                if not p['manual_exit_date']: tasks.append(dict(id='calendar_'+p['symbol'],type='data',title='更新未来交易日历',detail=f"{p['name']}到期后下一交易日尚未被交易日历覆盖",priority='high'))
                elif cycle>=p['exit_session']:
                    due=p['manual_exit_date']
                    status='overdue' if today>due else 'today' if today==due else 'upcoming'
                    label='已到期未录清仓' if status=='overdue' else '今日开盘手动卖出' if status=='today' else '下一交易日开盘手动卖出'
                    alert=dict(symbol=p['symbol'],name=p['name'],quantity=p['quantity'],baseline_exit_session=p['exit_session'],
                        manual_exit_date=due,deadline=p['deadline'],status=status,title=label,
                        detail=f"{due}开盘 · {p['quantity']}股；先核对国金及旧卖单，实际成交后再录入，未成交股份继续保留。")
                    manual_exit_alerts.append(alert)
                    past_open=today>due or (today==due and (clock.hour,clock.minute)>=(9,30))
                    tasks.append(dict(id='manual_exit_'+p['symbol'],type='manual_exit',symbol=p['symbol'],title=f"{p['name']} · {label}",
                        detail=alert['detail'],priority='high',blocks_finish=past_open))
            for o in state['orders']:
                o['expiry']=add_days(o['signal_date'],7)
                if o['expiry']<=cycle or o['filled']>0: tasks.append(dict(id='cancel_'+o['signal_id'],type='cancel',order_id=o['signal_id'],title=f"{o.get('name',o['symbol'])} · 核对{'部分成交剩余数量' if o['filled']>0 else '到期买单'}",detail='请确认券商剩余买单状态；五档剩余撤销后应结束该单',priority='high'))
            for symbol in state['pending_cleanups']:
                tasks.append(dict(id='cleanup_'+symbol,type='cleanup',symbol=symbol,title=f'{symbol} · 清理遗留卖单',detail='卖出后核对剩余数量及旧条件单',priority='high'))
            signals=[]
            occupied={p['symbol'] for p in state['positions']}|{o['symbol'] for o in state['orders']}
            if market_ready and confirmed:
                budget=min(equity/5,(state['available']+state['deferred']))
                for s in self.info.get('signals',[]):
                    decision=state['decisions'].get(s['id'])
                    if not decision and s['atr']<market.MINIMUM_ATR: continue
                    accepted=state['all_orders'].get(s['id']) if decision=='accept' else None
                    if accepted:
                        s=dict(s,atr=accepted['atr'],atr_policy=accepted.get('atr_policy','legacy_signal_atr'),trigger=accepted['trigger'])
                    status=decision or ('duplicate' if s['symbol'] in occupied else 'pending')
                    if not decision and add_days(s['signal_date'],7)<cycle: status='expired'
                    qty=max(0,int(max(0,budget-5)/(s['trigger']*1.002)/100)*100)
                    if accepted: qty=accepted['quantity']
                    signals.append(dict(s,status=status,quantity=qty,budget=round(budget,2),expiry=add_days(s['signal_date'],7)))
                if state['free_slots']>0 and any(s['status']=='pending' for s in signals):
                    tasks.append(dict(id='signals',type='signals',title='处理新买入推荐',detail=f"剩余{state['free_slots']}槽 · 原前三中ATR≥2.5%",priority='normal'))
            done_path=self.folder/f'finished_{cycle}.json'
            events=self.ledger.events()
            history=[dict(id=e['id'],at=e['at'],kind=e['kind'],data=e['data'],voided=e['voided']) for e in events[-200:]][::-1]
            return dict(**state,equity=round(equity,2),cycle=cycle,next_session=following,confirmed=confirmed,confirmation=confirm,market=dict(self.info,signals=[]),market_ready=market_ready,signals=signals,tasks=tasks,manual_exit_alerts=manual_exit_alerts,history=history,running=self.running,finished=done_path.exists(),account_curve=self.curve(),signal_filter=market.signal_filter_configuration())

    def curve(self):
        with self.ledger.connect() as db:
            return [dict(r) for r in db.execute('SELECT day,equity FROM confirmations ORDER BY day')]

    def action(self,kind,d):
        with self.lock:
            s=self.snapshot()
            day=now().date().isoformat()
            if kind=='review':
                clock=now()
                if (clock.hour,clock.minute)>=(9,30) and clock.hour<19:
                    raise ValueError('每日账户核对在19:00后至下一交易日开盘前办理')
                if not d.get('attested'): raise ValueError('请先确认已逐项核对券商的成交、挂单与持仓')
                cash=number(d['cash'],'券商现金')
                equity=number(d['equity'],'总权益',.01)
                if equity+0.05<cash: raise ValueError('总权益不能低于券商现金')
                self.ledger.confirm(s['cycle'],cash,equity)
            elif kind=='accept':
                if not s['confirmed'] or not s['market_ready']: raise ValueError('先完成今日核对并更新行情')
                sig=next((x for x in s['signals'] if x['id']==d['signal_id']),None)
                if not sig or sig['status']!='pending': raise ValueError('该推荐已处理或不可操作')
                if s['free_slots']<1: raise ValueError('槽位已满')
                qty=int(number(d['quantity'],'挂单股数',100))
                if qty%100: raise ValueError('买入股数须为100的整数倍')
                if qty>sig['quantity']: raise ValueError('挂单数量超过可用预算')
                if not s['next_session']: raise ValueError('未来交易日历尚未就绪，不能确认新的挂单')
                payload=dict(signal_id=sig['id'],symbol=sig['symbol'],name=sig['name'],signal_date=sig['signal_date'],atr=sig['atr'],atr_policy=sig.get('atr_policy','legacy_signal_atr'),trigger=sig['trigger'],quantity=qty)
                self.ledger.append('accept',payload)
            elif kind=='reject':
                sig=next((x for x in s['signals'] if x['id']==d['signal_id']),None)
                if not sig or sig['status']!='pending': raise ValueError('推荐不存在或已处理')
                self.ledger.append('reject',{'signal_id':sig['id']})
            elif kind in ('buy','sell'):
                date=d['date']; datetime.fromisoformat(date)
                if date>day: raise ValueError('不能录入未来成交')
                if date not in self.sessions(): raise ValueError('成交日期不在已核验交易日历中')
                raw_qty=number(d['quantity'],'成交股数',1)
                if not raw_qty.is_integer(): raise ValueError('成交股数必须为整数')
                qty=int(raw_qty); price=number(d['price'],'成交均价',.001); fee=number(d.get('fee',0),'实际手续费')
                payload=dict(date=date,quantity=qty,price=price,fee=fee,reference=str(d.get('reference','')).strip())
                if payload['reference'] and any(e['kind'] in ('buy','sell') and not e['voided'] and e['data'].get('reference')==payload['reference'] for e in self.ledger.events()): raise ValueError('该券商成交编号已录入')
                if kind=='buy':
                    o=s['all_orders'].get(d['order_id'])
                    if not o: raise ValueError('先确认国金买单已设置，再录入成交')
                    if not o['signal_date']<date<=add_days(o['signal_date'],7): raise ValueError('成交日期超出该信号7自然日窗口')
                    payload['order_id']=d['order_id']
                else:
                    if not any(p['symbol']==d['symbol'] for p in s['positions']): raise ValueError('未找到持仓')
                    payload['symbol']=d['symbol']
                self.ledger.append(kind,payload)
            elif kind in ('cancel','protection','expiry_order','cleanup'):
                if kind=='expiry_order':raise ValueError('到期退出已改为下一交易日开盘手动卖出；请查看独立提示，实际成交后录入卖出，不再确认预约卖单')
                if kind=='cancel' and not any(o['signal_id']==d['order_id'] for o in s['orders']): raise ValueError('未找到有效买单')
                if kind in ('protection','expiry_order') and not any(p['symbol']==d['symbol'] for p in s['positions']): raise ValueError('未找到持仓')
                self.ledger.append(kind,d)
            elif kind=='cash_set':
                target=round(number(d['cash'],'现金余额'),2)
                current=round(s['cash']+s['deferred'],2)
                if 'expected_cash' not in d or abs(number(d['expected_cash'],'编辑前现金')-current)>.005:
                    raise ValueError('现金记录已变化，请刷新后重新编辑')
                note=str(d.get('note','')).strip()
                if not note: raise ValueError('请填写现金更正说明；买卖成交请先在成交窗口录入')
                amount=round(target-current,2)
                if s['cash']+amount<-.01: raise ValueError('修改后不能低于当日待释放卖出款，请先核对成交记录')
                if amount:
                    self.ledger.append('cash_adjust',dict(amount=amount,note=note,date=day,source='cash_window',previous_cash=current,target_cash=target),
                        validate=lambda latest: self._validate_cash_edit(latest,current))
            elif kind=='cash_adjust':
                amount=number(d['amount'],'资金调整',-1e9)
                if not str(d.get('note','')).strip(): raise ValueError('资金调整请填写说明，确保账本可追溯')
                self.ledger.append(kind,dict(amount=amount,note=str(d['note']),date=day))
            elif kind=='void': self.ledger.void(int(d['event_id']))
            elif kind=='finish':
                blockers=[t for t in s['tasks'] if t['type'] not in ('signals',) and t.get('blocks_finish',True)]
                if blockers: raise ValueError('尚有账户、数据或持仓待办未完成')
                if s['free_slots']>0 and any(x['status']=='pending' for x in s['signals']): raise ValueError('请先接受或拒绝剩余推荐')
                (self.folder/f"finished_{s['cycle']}.json").write_text(json.dumps({'at':now().isoformat()}))
            else: raise ValueError('不支持的操作')
            if kind!='finish':
                path=self.folder/f"finished_{s['cycle']}.json"
                if path.exists(): path.unlink()
            if kind in ('buy','sell','cancel','cash_adjust','cash_set','void'):
                with self.ledger.connect() as db:
                    db.execute('DELETE FROM confirmations WHERE day=?',(s['cycle'],))
            self.ledger.backup()
            return self.snapshot()

    @staticmethod
    def _validate_cash_edit(latest,expected):
        if abs(latest['cash']+latest['deferred']-expected)>.005:
            raise ValueError('现金记录已变化，请刷新后重新编辑')
