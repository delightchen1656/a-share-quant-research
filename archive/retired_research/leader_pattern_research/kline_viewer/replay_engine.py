"""Server-side, forward-only manual price replay. Never send unrevealed bars."""
from pathlib import Path
import datetime,hashlib,json,re,secrets,threading,uuid

TZ=datetime.timezone(datetime.timedelta(hours=8))
FIELDS=['date','open','high','low','close','volume','ma5','ma10','ma20','ma60','change','phase']

class ReplayError(ValueError):pass

def dump(path,value):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8');temp.replace(path)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def number(x):
    import math
    return float(x) if x is not None and math.isfinite(float(x)) else None

class ReplayService:
    def __init__(self,root):self.root=Path(root);self.lock=threading.RLock()
    def folder(self,session_id):
        if not re.fullmatch(r'[0-9a-f]{32}',str(session_id)):raise ReplayError('练习编号无效')
        path=self.root/str(session_id)
        if not path.exists():raise ReplayError('未找到已保存的练习')
        return path
    def candidates(self,store,filters):
        selected=[];scope=filters.get('scope','leaders');year=filters.get('year','');query=filters.get('q','').strip().lower()
        direction=str(filters.get('direction','1'))
        all_rows=(store.direction_signals() if hasattr(store,'direction_signals') else store.signals(include_gaps=False))['signals']
        for s in all_rows:
            if not s['peak_complete60'] or s['entry_open'] is None:continue
            if scope=='leaders' and not s['is_leader']:continue
            if year and str(s['year'])!=str(year):continue
            if query and query not in f"{s['code']} {s['name']} {s['date']}".lower():continue
            if direction=='2' and not s.get('direction2',False):continue
            selected.append(dict(id=s['id'],code=s['code'],name=s['name'],date=s['date'],is_leader=s['is_leader'],direction=direction))
        selected.sort(key=lambda s:(s['date'],s['code']))
        return dict(rows=selected,total=len(selected),years=sorted({s['year'] for s in all_rows}),generation=store.generation,
            cutoff=store.cutoff.strftime('%Y-%m-%d'),availability='仅列D+1至D+60完整有效行情；不按未来涨跌筛选')
    def create(self,store,ids,title='',mode='manual',filters=None,rounds=10):
        if mode not in ['manual','random10','random']:raise ReplayError('练习模式无效')
        if mode=='random' and (type(rounds) is not int or rounds not in [5,10,20]):raise ReplayError('轮数只能选择5、10或20')
        count=rounds if mode=='random' else 10
        if mode in ['random10','random']:
            if not isinstance(filters,dict):raise ReplayError('请提供当前筛选条件')
            pool=self.candidates(store,filters)['rows']
            if mode=='random':
                pool=[s for s in pool if store.dates.get_loc(__import__('pandas').Timestamp(s['date']))+61<len(store.dates)]
            if len(pool)<count:raise ReplayError(f'当前筛选不足{count}个完整信号，请放宽条件')
            ids=[s['id'] for s in secrets.SystemRandom().sample(pool,count)]
        if not isinstance(ids,list) or not 1<=len(ids)<=200 or len(ids)!=len(set(ids)):raise ReplayError('请选择1至200个不同的信号')
        lookup={s['id']:s for s in self.candidates(store,dict(scope='all',tag=''))['rows']}
        if not all(i in lookup for i in ids):raise ReplayError('所选信号缺少完整60日有效行情，请重新筛选')
        if mode=='manual':ids=sorted(ids,key=lambda i:(lookup[i]['date'],lookup[i]['code']))
        frozen=[]
        for event_id in ids:
            e=store.events[event_id];f=store.stock(e['code']);t=store.dates.get_loc(__import__('pandas').Timestamp(e['signal_date']))
            required=61 if mode=='random' else 60
            if t+required>=len(f) or not f.valid.iloc[t+1:t+required+1].all():raise ReplayError('所选信号缺少完整买卖行情，请重新筛选或开始')
            past=f.iloc[max(0,t-251):t+1];future=f.iloc[t+1:min(t+(120 if mode=='random' else 60)+1,len(f))]
            cols=['open','high','low','close','volume','ma5','ma10','ma20','ma60','change']
            def bars(frame):
                result=[]
                for date,row in frame[frame.valid].iterrows():
                    phase='decline' if store.dates[t-35]<=date<store.dates[t-15] else 'base' if store.dates[t-15]<=date<store.dates[t] else 'spike' if date==store.dates[t] else None
                    result.append([date.strftime('%Y-%m-%d')]+[number(row[c]) for c in cols]+[phase])
                return result
            frozen.append(dict(meta=dict(lookup[event_id],box_low=e['box_low'],box_high=e['box_high']),past=bars(past),days=bars(future),review_complete120=t+120<len(f) and bool(f.valid.iloc[t+1:t+121].all())))
        session_id=uuid.uuid4().hex;folder=self.root/session_id;folder.mkdir(parents=True)
        dump(folder/'quotes.json',dict(generation=store.generation,fields=FIELDS,rounds=frozen))
        now=datetime.datetime.now(TZ).isoformat()
        weight=1. if mode in ['random10','random'] else .5
        state=dict(id=session_id,title=str(title or (f'随机{count}轮全仓测试' if mode in ['random10','random'] else '逐日半仓练习'))[:60],created_at=now,updated_at=now,revision=0,index=0,
            stage='signal',day=0,entry=None,exit=None,round_start_nav=1.,realized_nav=1.,weight=weight,initial_capital=100000.,
            mode=mode,selection_filters=filters if mode in ['random10','random'] else None,total_rounds=len(frozen),
            outcomes=[],operations=[],curve=[dict(round=0,day=0,nav=1.)],quote_sha256=sha(folder/'quotes.json'),review=False,
            basis=f"前复权价格练习；{f'全仓·随机{count}轮' if mode in ['random10','random'] else '半仓'}；不含税费、真实股数及分红现金记账；按练习轮次复利，非真实日历账户")
        if mode=='random':self.enter(state,frozen[0])
        dump(folder/'state.json',state)
        return self.public(state,self.quotes(folder,state))
    def quotes(self,folder,state):
        path=folder/'quotes.json'
        if sha(path)!=state['quote_sha256']:raise ReplayError('练习行情快照校验失败，保留已有操作记录')
        return json.loads(path.read_text(encoding='utf-8'))
    def nav(self,state,price):
        return state['round_start_nav']*(1-state['weight']+state['weight']*price/state['entry'])
    def enter(self,state,round_):
        state.update(entry=round_['days'][0][1],day=1,stage='holding')
        self.mark(state,self.nav(state,round_['days'][0][4]))
        state['operations'].append(dict(action='auto_buy',round=state['index']+1,day=1,price=state['entry']))
    def mark(self,state,value,day=None):state['curve'].append(dict(round=state['index']+1,day=state['day'] if day is None else day,nav=value))
    def finish(self,state,round_,price,date,reason):
        result=self.nav(state,price);stock_return=price/state['entry']-1
        execution_day=state['day']+1 if reason in ['点击后次日开盘卖出','D60到期次日开盘平仓'] else state['day']
        state['exit']=dict(price=price,date=date,reason=reason,day=execution_day)
        state['outcomes'].append(dict(round=state['index']+1,id=round_['meta']['id'],code=round_['meta']['code'],name=round_['meta']['name'],
            signal_date=round_['meta']['date'],buy_date=round_['days'][0][0],buy_price=state['entry'],sell_date=date,sell_price=price,
            exit_reason=reason,stock_return=stock_return,nav_before=state['round_start_nav'],nav_after=result,account_return=result/state['round_start_nav']-1))
        state['realized_nav']=result;state['stage']='closed';self.mark(state,result,execution_day)
        if state.get('mode')=='random':state['review']=True
    def action(self,session_id,action,revision):
        with self.lock:
            folder=self.folder(session_id);state=json.loads((folder/'state.json').read_text(encoding='utf-8'));quotes=self.quotes(folder,state)
            if revision!=state['revision']:raise ReplayError('进度已更新，本次重复点击未执行，请刷新练习')
            round_=quotes['rounds'][state['index']];stage=state['stage'];day=state['day']
            if action=='buy' and stage=='signal':
                state['entry']=round_['days'][0][1];state['day']=1;state['stage']='holding';self.mark(state,self.nav(state,round_['days'][0][4]))
            elif action=='advance' and stage=='holding':
                if day>=60:raise ReplayError('第60日已结束')
                state['day']+=1;bar=round_['days'][state['day']-1]
                if state['day']==60:
                    if state.get('mode')=='random':
                        self.mark(state,self.nav(state,bar[4]));exit_bar=round_['days'][60]
                        self.finish(state,round_,exit_bar[1],exit_bar[0],'D60到期次日开盘平仓')
                    else:self.finish(state,round_,bar[4],bar[0],'D60收盘强制结束')
                else:self.mark(state,self.nav(state,bar[4]))
            elif action=='sell' and stage=='holding':
                if day>=60:raise ReplayError('第60日已强制结束，不能延后至D61')
                bar=round_['days'][day];self.finish(state,round_,bar[1],bar[0],'点击后次日开盘卖出')
            elif action=='skip' and stage=='signal':
                if state.get('mode') in ['random10','random']:raise ReplayError('随机测试需逐轮结算，不支持跳过')
                state['stage']='skipped'
            elif action=='review' and stage=='closed':state['review']=True
            elif action=='next' and stage in ['closed','skipped']:
                if state['index']+1>=len(quotes['rounds']):raise ReplayError('全部所选信号已练习完毕')
                state.update(index=state['index']+1,stage='signal',day=0,entry=None,exit=None,round_start_nav=state['realized_nav'],review=False)
                if state.get('mode')=='random':self.enter(state,quotes['rounds'][state['index']])
            else:raise ReplayError('当前阶段不能执行此操作')
            state['revision']+=1;state['updated_at']=datetime.datetime.now(TZ).isoformat()
            state['operations'].append(dict(action=action,revision=state['revision'],round=state['index']+1,day=state['day'],at=state['updated_at']))
            dump(folder/'state.json',state)
            return self.public(state,quotes)
    def public(self,state,quotes):
        round_=quotes['rounds'][state['index']];bars=list(round_['past']);day=state['day'];stage=state['stage']
        if state['review']:bars+=round_['days']
        else:
            bars+=round_['days'][:day]
            if stage=='closed' and state['exit']['reason']=='点击后次日开盘卖出':
                next_bar=round_['days'][day]
                # At execution time only OPEN is known. Never synthesize a full future candle.
                bars.append([next_bar[0],next_bar[1],None,None,None,None,None,None,None,None,None,'exit_open'])
        nav=state['realized_nav'] if stage!='holding' else self.nav(state,round_['days'][day-1][4])
        values=[p['nav'] for p in state['curve']];peak=values[0];drawdown=0.
        for value in values:peak=max(peak,value);drawdown=min(drawdown,value/peak-1)
        return dict(id=state['id'],title=state['title'],revision=state['revision'],stage=stage,day=day,round=state['index']+1,total_rounds=len(quotes['rounds']),
            generation=quotes['generation'],mode=state.get('mode','manual'),selection_filters=state.get('selection_filters'),review_complete120=round_.get('review_complete120',False),signal=round_['meta'],bars=bars,fields=FIELDS,entry=state['entry'],exit=state['exit'],nav=nav,
            realized_nav=state['realized_nav'],round_start_nav=state['round_start_nav'],weight=state['weight'],
            equity=state['initial_capital']*nav,max_drawdown=drawdown,completed=len(state['outcomes']),outcomes=state['outcomes'],curve=state['curve'],
            basis=state['basis'],review=state['review'],has_next=state['index']+1<len(quotes['rounds']),
            visible_through=bars[-1][0],created_at=state['created_at'])
    def get(self,session_id):
        with self.lock:
            folder=self.folder(session_id);state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
            return self.public(state,self.quotes(folder,state))
    def round_review(self,session_id,round_number):
        with self.lock:
            folder=self.folder(session_id);state=json.loads((folder/'state.json').read_text(encoding='utf-8'));quotes=self.quotes(folder,state)
            result=next((o for o in state['outcomes'] if o['round']==round_number),None)
            if not result:raise ReplayError('只能复盘已结算的轮次')
            exit_day=next(i+1 for i,b in enumerate(quotes['rounds'][round_number-1]['days']) if b[0]==result['sell_date'])
            state.update(index=round_number-1,stage='closed',day=60,entry=result['buy_price'],realized_nav=result['nav_after'],round_start_nav=result['nav_before'],review=True,
                exit=dict(price=result['sell_price'],date=result['sell_date'],reason=result['exit_reason'],day=exit_day))
            state['outcomes']=[o for o in state['outcomes'] if o['round']<=round_number]
            state['curve']=[p for p in state['curve'] if p['round']<=round_number]
            public=self.public(state,quotes);public.update(read_only=True,has_next=False)
            return public
    def sessions(self,page=None,page_size=10):
        with self.lock:
            if not self.root.exists():return [] if page is None else dict(rows=[],total=0,page=1,pages=1)
            rows=[]
            for p in self.root.glob('*/state.json'):
                try:
                    s=json.loads(p.read_text(encoding='utf-8'));row={k:s[k] for k in ['id','title','updated_at','stage','realized_nav']}
                    total=s.get('total_rounds')
                    if total is None:total=len(json.loads((p.parent/'quotes.json').read_text(encoding='utf-8'))['rounds'])
                    row.update(created_at=s['created_at'],round=s['index']+1,total_rounds=total,completed=len(s['outcomes']),weight=s['weight'],mode=s.get('mode','manual'),selection_filters=s.get('selection_filters'),finished=s['index']+1==total and s['stage'] in ['closed','skipped'])
                    rows.append(row)
                except (OSError,ValueError,KeyError):continue
            rows.sort(key=lambda s:s['updated_at'],reverse=True)
            if page is None:return rows[:30]
            pages=max(1,(len(rows)+page_size-1)//page_size);page=max(1,min(page,pages))
            return dict(rows=rows[(page-1)*page_size:page*page_size],total=len(rows),page=page,pages=pages)
