from __future__ import annotations

import json
import math
import threading
import re
import time
import uuid
import os
import tempfile
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from store import Ledger, now, number, add_days, REVIEW_POLICY
import market
from performance import tracking

HERE=Path(__file__).resolve().parent
DATA=HERE/'data'
CALCULATION_STAGES=[('check','行情与账户核验'),('features','历史特征计算'),('models','冻结模型评分'),
                    ('ranking','因子排名与ATR筛选'),('freeze','冻结信号校验'),('publish','发布次日推荐')]


def save_model_result(path,result,replace=True):
    """Publish a complete JSON file atomically, never a partial calculation."""
    path=Path(path)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        if replace: os.replace(temporary,path)
        else: os.link(temporary,path)  # Immutable daily cache: fails if it exists.
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()


class Tracker:
    def __init__(self,folder=DATA):
        self.folder=Path(folder); self.folder.mkdir(parents=True,exist_ok=True)
        self.ledger=Ledger(self.folder/'ledger.sqlite3')
        self.lock=threading.RLock()
        self.running=False
        self.update_progress=''
        self.update_started_at=None
        self.update_stage='check'
        self.update_clock=None
        self.update_finished_clock=None
        self.stage_clock=None
        self.progress_clock=None
        self.progress_history=[]
        self.last_calculation=None
        self.full_model_run=False
        self.cache_reused=False
        self.work_fraction=0.
        self.work_completed=None
        self.work_total=None
        timing=self.folder/'calculation_timing.json'
        try: self.last_calculation=json.loads(timing.read_text(encoding='utf-8'))
        except (OSError,ValueError): pass
        self.info=self.read_info()
        self._tracking_cache=None

    def read_info(self):
        path=self.folder/'market_status.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status':'waiting','message':'尚未更新，请点击更新本地数据','signals':[]}

    def save_info(self):
        path=self.folder/'market_status.json'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.info,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)

    def progress(self,message):
        with self.lock:
            stage=self.update_stage
            if 'feature files' in message or '历史特征' in message: stage='features'
            elif '冻结模型' in message and ('加载' in message or '预测中' in message): stage='models'
            elif '因子排序' in message: stage='ranking'
            elif '冻结信号' in message: stage='freeze'
            elif '发布次日推荐' in message: stage='publish'
            elif '历史横截面排名' in message: stage='models'
            clock=time.monotonic()
            if stage!=self.update_stage:
                self.update_stage=stage
                self.stage_clock=clock
                self.work_fraction=0.
                self.work_completed=self.work_total=None
            files=re.search(r'feature files (\d+)/(\d+)',message)
            model=re.search(r'冻结模型 (utility|pen025|pen100).*rows (\d+)/(\d+)',message)
            if files:
                completed,total=map(int,files.groups())
                self.work_completed,self.work_total=completed,total
                self.work_fraction=completed/max(total,1)*.95
            elif model:
                name,completed,total=model.groups();completed,total=int(completed),int(total)
                self.work_completed,self.work_total=completed,total
                self.work_fraction=(('utility','pen025','pen100').index(name)+completed/max(total,1))/3*.95
            elif '历史特征合并' in message: self.work_fraction=.95
            elif '历史横截面排名' in message: self.work_fraction=.95
            self.update_progress=message
            self.progress_clock=clock
            self.progress_history.append(dict(at=now().isoformat(),stage=stage,message=message))
            self.progress_history=self.progress_history[-12:]

    def calculation_state(self):
        clock=self.update_finished_clock if not self.running and self.update_finished_clock is not None else time.monotonic()
        elapsed=max(0,int(clock-self.update_clock)) if self.update_clock is not None else 0
        extra=dict(elapsed_seconds=elapsed,stage_elapsed_seconds=max(0,int(clock-self.stage_clock)) if self.stage_clock is not None else 0,
                   seconds_since_progress=max(0,int(clock-self.progress_clock)) if self.progress_clock is not None else 0,
                   stages=[dict(id=k,label=v) for k,v in CALCULATION_STAGES],stage=self.update_stage,
                   stage_index=next(i+1 for i,(k,_) in enumerate(CALCULATION_STAGES) if k==self.update_stage),
                   history=list(self.progress_history),last_full_model_seconds=(self.last_calculation or {}).get('seconds'))
        # Work-unit weighting: the slow file pass and model predictions carry most
        # of the bar; publication is the only point that can reach 100%.
        weights=[0,3,68,94,97,99,100]
        index=extra['stage_index']-1
        extra.update(work_completed=self.work_completed,work_total=self.work_total,
                     stage_fraction=self.work_fraction,
                     progress_percent=min(99,weights[index]+(weights[index+1]-weights[index])*self.work_fraction))
        if not self.running and self.info.get('status')=='ready': extra['progress_percent']=100
        extra['cache_reused']=self.cache_reused
        extra['full_model_run']=self.full_model_run
        if self.full_model_run and extra['last_full_model_seconds'] is not None:
            extra['estimated_remaining_seconds']=max(0,int(extra['last_full_model_seconds']-elapsed))
        if self.running:
            stage_label=dict(CALCULATION_STAGES)[self.update_stage]
            return dict(code='running',label=f"{extra['stage_index']}/{len(CALCULATION_STAGES)} · {stage_label}",detail=self.update_progress or '正在核验',started_at=self.update_started_at,**extra)
        code=self.info.get('status','waiting')
        labels={'ready':'已完成','blocked':'失败（已停止）','awaiting_review':'等待资金复核','awaiting_buy_results':'等待买单结果','waiting':'等待更新'}
        return dict(code=code,label=labels.get(code,'待处理'),detail=self.info.get('message',''),started_at=self.update_started_at,**extra)

    def cycle(self):
        clock=now()
        day=clock.date()
        if clock.hour<9 or (clock.hour==9 and clock.minute<30): day-=timedelta(days=1)
        cutoff=day.isoformat()
        return max((d for d in self.sessions() if d<=cutoff),default=cutoff)

    def review_window_open(self,clock):
        # Rest days belong to the preparation window before the next opening.
        return (clock.date().isoformat() not in self.sessions()
                or (clock.hour,clock.minute)<(9,30) or clock.hour>=19)

    def sessions(self):
        return market.calendar_extended(self.folder)

    def next_session(self,day):
        return next((d for d in self.sessions() if d>day),None)

    def exit_session(self,deadline):
        sessions=self.sessions()
        if not sessions or sessions[-1]<deadline: return None
        return max((d for d in sessions if d<=deadline),default=None)

    def buy_result_tasks(self,state,cycle,sessions,events):
        """Explicit broker-result check for existing orders, never infer a fill."""
        session=max((d for d in sessions if d<=cycle),default=None)
        checked={}
        for event in events:
            if not event['voided'] and event['kind']=='buy_review':
                d=event['data']
                if d.get('day')==session: checked[d['order_id']]=d
        tasks=[]
        for order in state['orders']:
            expiry=add_days(order['signal_date'],7)
            if expiry<=cycle or order['filled']>0:
                tasks.append(dict(id='cancel_'+order['signal_id'],type='cancel',order_id=order['signal_id'],
                    title=f"{order.get('name',order['symbol'])} · 核对{'部分成交剩余数量' if order['filled'] else '到期买单'}",
                    detail='先补录已有成交，再核对国金剩余买单是否已撤销；确认后进入资金复核',priority='high'))
            elif session and order['signal_date']<session:
                review=checked.get(order['signal_id'])
                if review and review.get('filled_at_review')==order['filled'] and review.get('order_event_id')==order['event_id']:
                    continue
                tasks.append(dict(id='buy_result_'+order['signal_id'],type='buy_result',order_id=order['signal_id'],
                    title=f"{order.get('name',order['symbol'])} · 更新买入结果",
                    detail=f"{session}：买入成功（填写股数）／今日未成交；剩余{order['quantity']-order['filled']}股，核对后再进行下一步",priority='high'))
        return session,tasks

    def update(self,background=True):
        with self.lock:
            if self.running: return
            self.running=True
            self.update_started_at=now().isoformat()
            self.update_clock=self.stage_clock=self.progress_clock=time.monotonic()
            self.update_finished_clock=None
            self.update_stage='check'
            self.progress_history=[]
            self.full_model_run=False
            self.cache_reused=False
            self.work_fraction=0.
            self.work_completed=self.work_total=None
            self.update_progress='核验交易日历、本地行情与账户状态'
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
                    prior_settlement=self.info.get('settlement_date',self.info.get('market_date'))
                    self.info=dict(self.info,market_date=h['market_date'],audit=h['audit'],settlement_date=prior_settlement)
                expected=max((d for d in h['sessions'] if d<=self.cycle()),default=None)
                if h['market_date']!=expected:
                    raise ValueError(f"行情尚未提交：需要{expected}，最近成功数据为{h['market_date']}，请等待18点行情任务完成后重试")
                clock=now()
                close_window=(h['market_date']<clock.date().isoformat()
                              or clock.hour>=19 or (clock.hour,clock.minute)<(9,30))
                if close_window:
                    with self.lock:
                        positions=self.ledger.state()['positions']
                        close_marks=market.raw_marks([p['symbol'] for p in positions],h['market_date'])
                        missing=[p['symbol'] for p in positions if close_marks.get(p['symbol'],{}).get('date')!=h['market_date']]
                        if missing:raise ValueError('19点收盘估值缺少当日原始收盘价：'+','.join(missing))
                        self.info.update(settlement_date=h['market_date'],settled_at=clock.isoformat())
                        self._tracking_cache=None
                        close_snapshot=self.snapshot()
                        key=f"close:{h['market_date']}:{close_snapshot['revision']}:{close_snapshot['equity']}:{close_snapshot['cash']}"
                        self.ledger.observe(key,h['market_date'],'market_close',close_snapshot['cash']+close_snapshot['deferred'],close_snapshot['equity'])
                        self._tracking_cache=None
                with self.lock:
                    events=self.ledger.events()
                    state=self.ledger.state(events=events)
                    _,buy_tasks=self.buy_result_tasks(state,self.cycle(),h['sessions'],events)
                    if buy_tasks:
                        self.info=dict(self.info,status='awaiting_buy_results',signals=[],prepared=True,
                            message='先更新现有买单的成交／未成交结果，再复核资金并生成新推荐',calendar_warning=calendar_warning)
                        self.save_info()
                        return
                review=self.ledger.confirmation(self.cycle())
                if not review or review.get('policy')!=REVIEW_POLICY:
                    with self.lock:
                        self.info=dict(self.info,status='awaiting_review',signals=[],prepared=True,
                            message='第一步：复核并覆盖券商现金，确认后才能生成新推荐',calendar_warning=calendar_warning)
                        self.save_info()
                    return
                cache=market.signal_cache_path(self.folder,h['market_date'])
                latest_cache=self.folder/'latest_model_result.json'
                # The fixed file is independent of account cash/decisions. An
                # accepted or rejected order never forces a model recalculation.
                if latest_cache.exists():
                    latest=json.loads(latest_cache.read_text(encoding='utf-8'))
                    if latest.get('market_date')==h['market_date']: cache=latest_cache
                pipeline_id,pipeline_inputs=market.pipeline_identity(h)
                if cache.exists():
                    self.cache_reused=True
                    self.progress('校验并复用当日冻结信号')
                    frozen=json.loads(cache.read_text(encoding='utf-8'))
                    # This exact prior source differs only by observable progress
                    # and row-independent prediction batching. All market/model/
                    # policy hashes still have to match; retain the original cache.
                    legacy_inputs=json.loads(json.dumps(pipeline_inputs))
                    source_key=str(Path(market.__file__).relative_to(market.ROOT)).replace('\\','/')
                    legacy_id=None
                    if source_key in legacy_inputs.get('files',{}):
                        legacy_inputs['files'][source_key]='81861877a969bb0d32f5892d2058a48f2905035719519bbb85a7d3fa652b63e7'
                        legacy_id=hashlib.sha256(json.dumps(legacy_inputs,sort_keys=True).encode()).hexdigest()
                    valid_ids={pipeline_id}
                    if legacy_id is not None: valid_ids.add(legacy_id)
                    if not isinstance(frozen,dict) or frozen.get('pipeline_id') not in valid_ids:
                        raise ValueError('当日冻结信号缺少来源或与当前行情/模型不一致，已停止；保留原件待核查，不自动覆盖')
                    if frozen.get('market_date')!=h['market_date']: raise ValueError('冻结信号日期不一致')
                    if frozen.get('signal_filter_policy')!=market.SIGNAL_FILTER_POLICY_ID: raise ValueError('冻结信号ATR筛选政策不一致')
                    signals=frozen['signals']
                    if frozen.get('signals_sha256')!=market.signals_digest(signals): raise ValueError('冻结信号内容校验失败，保留原件待核查')
                    market.validate_signals(signals,h)
                else:
                    self.full_model_run=True
                    signals=market.predict(self.folder,h,progress=self.progress)
                    market.validate_signals(signals,h)
                    self.progress('保存并校验当日冻结信号')
                    frozen={'schema_version':2,'market_date':h['market_date'],'pipeline_id':pipeline_id,'signals_sha256':market.signals_digest(signals),'created_at':now().isoformat(),'signals':signals,'signal_filter_policy':market.SIGNAL_FILTER_POLICY_ID,
                            'model_seconds':round(time.monotonic()-self.update_clock,2)}
                final_health=market.health(self.folder)
                if market.pipeline_identity(final_health)[0]!=pipeline_id:
                    raise ValueError('冻结后行情或模型发生变化，暂停展示待重新核验')
                if self.full_model_run: save_model_result(cache,frozen,replace=False)
                save_model_result(latest_cache,frozen)
                self.progress('发布次日推荐')
                with self.lock:
                    latest_review=self.ledger.confirmation(self.cycle())
                    if not latest_review or latest_review['at']!=review['at']:
                        raise ValueError('计算期间账户已变化，请重新复核资金后生成推荐')
                    # Unhandled recommendations from older sessions expire once, preserving audit history.
                    previous=self.info.get('signals',[])
                    decisions=self.ledger.state()['decisions']
                    for s in previous:
                        if s['signal_date']<h['market_date'] and s['id'] not in decisions:
                            self.ledger.append('reject',{'signal_id':s['id'],'automatic':True})
                    self.info=dict(self.info,status='ready',market_date=h['market_date'],updated_at=now().isoformat(),message='沪深2 ATR≥2.5%：收盘行情与冻结模型已校验',signals=signals,audit=h['audit'],pipeline_id=pipeline_id,calendar_warning=calendar_warning,signal_filter_policy=market.SIGNAL_FILTER_POLICY_ID)
                    self.save_info()
                    self._tracking_cache=None
            except Exception as exc:
                with self.lock:
                    self.info=dict(self.info,status='blocked',message=str(exc),attempted_at=now().isoformat())
                    self.save_info()
            finally:
                with self.lock:
                    self.update_finished_clock=time.monotonic()
                    if self.full_model_run and self.info.get('status')=='ready':
                        self.last_calculation=dict(seconds=round(time.monotonic()-self.update_clock,2),completed_at=now().isoformat(),market_date=self.info.get('market_date'))
                        timing=self.folder/'calculation_timing.json'
                        try:
                            temp=timing.with_suffix('.tmp')
                            temp.write_text(json.dumps(self.last_calculation,ensure_ascii=False,indent=2),encoding='utf-8')
                            temp.replace(timing)
                        except OSError: pass
                    self.running=False
                    self.update_progress=''
        if background: threading.Thread(target=work,daemon=True).start()
        else: work()

    def snapshot(self):
        with self.lock:
            events=self.ledger.events()
            state=self.ledger.state(events=events)
            cycle=self.cycle()
            clock=now();today=clock.date().isoformat()
            confirm=self.ledger.confirmation(cycle)
            sessions=self.sessions()
            expected=max((d for d in sessions if d<=cycle),default=None)
            market_ready=not self.running and self.info.get('status')=='ready' and self.info.get('market_date')==expected and self.info.get('signal_filter_policy')==market.SIGNAL_FILTER_POLICY_ID
            buy_review_session,buy_tasks=self.buy_result_tasks(state,cycle,sessions,events)
            confirmed=bool(confirm and confirm.get('policy')==REVIEW_POLICY and not buy_tasks)
            following=self.next_session(cycle)
            settlement_date=self.info.get('settlement_date',self.info.get('market_date'))
            marks=market.raw_marks([p['symbol'] for p in state['positions']],settlement_date or cycle)
            equity=state['cash']+state['deferred']
            tasks=list(buy_tasks);manual_exit_alerts=[]
            if not confirmed: tasks.append(dict(id='review',type='review',title='下一步 · 复核资金' if buy_tasks else '复核资金',
                detail='先完成上方买单结果，再覆盖券商现金' if buy_tasks else '直接覆盖券商现金；确认后生成新推荐',priority='high',blocked=bool(buy_tasks)))
            if not market_ready and self.info.get('status') not in ('awaiting_review','awaiting_buy_results'): tasks.append(dict(id='data',type='data',title='行情 / 模型待就绪',detail=self.info.get('message','等待更新'),priority='high'))
            for p in state['positions']:
                p['mark']=marks.get(p['symbol'])
                p['valuation_date']=settlement_date
                p['valuation_ready']=bool(p['mark'] and p['mark']['date']==settlement_date)
                p['value']=p['quantity']*(p['mark']['price'] if p['mark'] else p['average_price'])
                p['pnl']=round(p['value']-p['cost'],2) if p['valuation_ready'] else None
                equity+=p['value']
                p['earliest_sell']=self.next_session(p['entry_date'])
                p['exit_session']=self.exit_session(p['deadline'])
                p['manual_exit_date']=self.next_session(p['exit_session']) if p['exit_session'] else None
                if not p['protection']: tasks.append(dict(id='protect_'+p['symbol'],type='protection',symbol=p['symbol'],title=f"{p['name']} · {'重新核对' if p['protection_needs_review'] else '设置'}止盈止损",detail=f"相对成交均价：止盈 {p['take_delta']:+.4f}元（目标{p['take']:.2f}） / 止损 {p['stop_delta']:+.4f}元（目标{p['stop']:.2f}） · {p['quantity']}股",priority='high'))
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
                o['needs_daily_result']=any(t['order_id']==o['signal_id'] for t in buy_tasks)
            signals=[]
            occupied={p['symbol'] for p in state['positions']}|{o['symbol'] for o in state['orders']}
            if market_ready and confirmed:
                budget=min(equity/5,(state['available']+state['deferred']))
                for s in self.info.get('signals',[]):
                    decision=state['decisions'].get(s['id'])
                    if not decision and not market.eligible(s['atr']): continue
                    accepted=state['all_orders'].get(s['id']) if decision=='accept' else None
                    if accepted:
                        s=dict(s,atr=accepted['atr'],atr_policy=accepted.get('atr_policy','legacy_signal_atr'),trigger=accepted['trigger'])
                    status=decision or ('duplicate' if s['symbol'] in occupied else 'pending')
                    if not decision and add_days(s['signal_date'],7)<cycle: status='expired'
                    qty=max(0,int(max(0,budget-5)/(s['trigger']*1.002)/100)*100)
                    if accepted: qty=accepted['quantity']
                    signals.append(dict(s,status=status,quantity=qty,budget=round(budget,2),expiry=add_days(s['signal_date'],7)))
                if state['free_slots']>0 and any(s['status']=='pending' for s in signals):
                    tasks.append(dict(id='signals',type='signals',title='处理新买入推荐',detail=f"剩余{state['free_slots']}槽 · ATR≥2.5%，不递补",priority='normal'))
            done_path=self.folder/f'finished_{cycle}.json'
            tracking_key=(tuple((e['id'],e['voided']) for e in events),tuple((x['day'],x['at']) for x in self.curve()),settlement_date,today)
            if self._tracking_cache is None or self._tracking_cache[0]!=tracking_key:
                self._tracking_cache=(tracking_key,tracking(self.ledger,sessions,settlement_date,market.DATA,today))
            performance=self._tracking_cache[1]
            history=[dict(id=e['id'],at=e['at'],kind=e['kind'],data=e['data'],voided=e['voided']) for e in events[-200:]][::-1]
            finished=bool(done_path.exists() and confirmed and market_ready and not any(t.get('blocks_finish',True) for t in tasks))
            return dict(**state,equity=round(equity,2),cycle=cycle,next_session=following,confirmed=confirmed,confirmation=confirm,
                buy_review_session=buy_review_session,buy_result_tasks=buy_tasks,
                market=dict(self.info,signals=[]),market_ready=market_ready,signals=signals,tasks=tasks,manual_exit_alerts=manual_exit_alerts,history=history,running=self.running,
                calculation_status=self.calculation_state(),update_progress=self.update_progress,
                finished=finished,account_curve=performance['curve'],performance=performance,signal_filter=market.signal_filter_configuration(),revision=events[-1]['id'] if events else 0,review_policy=REVIEW_POLICY)

    def curve(self):
        with self.ledger.connect() as db:
            return [dict(r) for r in db.execute('SELECT day,at,equity FROM confirmations ORDER BY day')]

    def action(self,kind,d):
        with self.lock:
            s=self.snapshot()
            day=now().date().isoformat()
            if kind=='review':
                if s['buy_result_tasks']: raise ValueError('请先更新现有买单的成交／未成交结果，再复核资金')
                clock=now()
                if not self.review_window_open(clock):
                    raise ValueError('每日账户核对在19:00后至下一交易日开盘前办理')
                if not d.get('attested'): raise ValueError('请先确认已逐项核对券商的成交、挂单与持仓')
                cash=number(d['cash'],'券商现金')
                equity=number(d['equity'],'总权益',.01)
                if equity+0.05<cash: raise ValueError('总权益不能低于券商现金')
                current=round(s['cash']+s['deferred'],2)
                if 'expected_cash' in d:
                    self.ledger.review_cash(s['cycle'],round(cash,2),round(equity,2),number(d['expected_cash'],'编辑前现金'),
                        int(d.get('expected_revision',-1)),d.get('flow_type','reconciliation'),str(d.get('note','')).strip())
                else:
                    # Backward-compatible exact-cash callers; never silently overwrite.
                    self.ledger.confirm(s['cycle'],cash,equity)
            elif kind=='buy_review':
                clock=now()
                if not self.review_window_open(clock):
                    raise ValueError('今日未成交核对在19:00后至下一交易日开盘前办理；实际成交可随时补录')
                if not d.get('attested'): raise ValueError('请先核对国金，确认该买单今日没有成交')
                order=next((o for o in s['orders'] if o['signal_id']==d.get('order_id')),None)
                if not order or not any(t['type']=='buy_result' and t['order_id']==order['signal_id'] for t in s['buy_result_tasks']):
                    raise ValueError('该买单无需核对、已处理或已变化，请刷新后重试')
                if d.get('day')!=s['buy_review_session'] or int(d.get('filled_at_review',-1))!=order['filled'] or int(d.get('order_event_id',-1))!=order['event_id']:
                    raise ValueError('买单日期或数量已变化，请刷新核对窗口')
                self.ledger.append('buy_review',dict(order_id=order['signal_id'],symbol=order['symbol'],day=s['buy_review_session'],
                    filled_at_review=order['filled'],order_event_id=order['event_id'],result='unfilled',note='今日未成交，保留原7自然日买单'))
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
                if s['buy_result_tasks']: raise ValueError('请先更新现有买单的成交／未成交结果')
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
                if kind=='protection':
                    position=next(p for p in s['positions'] if p['symbol']==d['symbol'])
                    d=dict(d,take=position['take'],stop=position['stop'],average_price=position['average_price'],model_base_price=position['model_base_price'],policy='actual_fill_anchor_v1')
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
                    flow_type=d.get('flow_type','reconciliation')
                    if flow_type not in ('external','reconciliation'):raise ValueError('资金调整类型不合法')
                    self.ledger.append('cash_adjust',dict(amount=amount,note=note,date=day,source='cash_window',previous_cash=current,target_cash=target,flow_type=flow_type),
                        validate=lambda latest: self._validate_cash_edit(latest,current))
            elif kind=='cash_adjust':
                amount=number(d['amount'],'资金调整',-1e9)
                if not str(d.get('note','')).strip(): raise ValueError('资金调整请填写说明，确保账本可追溯')
                flow_type=d.get('flow_type','external')
                if flow_type not in ('external','reconciliation'):raise ValueError('资金调整类型不合法')
                self.ledger.append(kind,dict(amount=amount,note=str(d['note']),date=day,flow_type=flow_type))
            elif kind=='classify_cash':
                event_id=int(d['event_id']);flow_type=d['flow_type']
                if flow_type not in ('external','reconciliation'):raise ValueError('资金调整类型不合法')
                if not any(e['id']==event_id and e['kind']=='cash_adjust' and not e['voided'] for e in self.ledger.events()):raise ValueError('未找到有效资金调整')
                self.ledger.append(kind,dict(event_id=event_id,flow_type=flow_type))
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
            if kind in ('buy','sell','cancel','buy_review','cash_adjust','cash_set','void'):
                with self.ledger.connect() as db:
                    db.execute('DELETE FROM confirmations WHERE day=?',(s['cycle'],))
            self._tracking_cache=None
            snap=self.snapshot()
            observed_equity=round(number(d['equity'],'总权益'),2) if kind=='review' else snap['equity']
            self.ledger.observe(uuid.uuid4().hex,snap['cycle'],kind,snap['cash']+snap['deferred'],observed_equity)
            self.ledger.backup()
            self._tracking_cache=None
            if kind=='review' and 'expected_cash' in d:self.update(background=True)
            return self.snapshot()

    @staticmethod
    def _validate_cash_edit(latest,expected):
        if abs(latest['cash']+latest['deferred']-expected)>.005:
            raise ValueError('现金记录已变化，请刷新后重新编辑')
