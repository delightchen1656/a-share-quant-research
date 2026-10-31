import json,tempfile,unittest,threading,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import app
from replay_engine import ReplayService,ReplayError

class FakeStore:
    def __init__(self):
        self.dates=pd.bdate_range('2020-01-01',periods=400);self.cutoff=self.dates[-1];self.generation='frozen_test';self.events={};self.rows=[];self.frames={}
        for code,t,next_open in [('000001',300,13.),('000002',320,9.)]:
            f=pd.DataFrame(index=self.dates)
            for col,value in [('open',10.),('high',12.),('low',8.),('close',10.),('volume',100.)]:f[col]=value
            for n in [5,10,20,60]:f['ma'+str(n)]=10.
            f['change']=0.;f['valid']=True
            f.iloc[t+1,f.columns.get_loc('close')]=11. if code=='000001' else 10.
            f.iloc[t+2,f.columns.get_loc('open')]=next_open
            f.iloc[t+2,f.columns.get_loc('high')]=9876543.
            event_id='e'+code;date=self.dates[t].strftime('%Y-%m-%d')
            self.events[event_id]=dict(code=code,signal_date=date,box_low=8.,box_high=12.)
            self.rows.append(dict(id=event_id,code=code,name='测试'+code,date=date,year=self.dates[t].year,is_leader=True,
                peak_complete60=True,entry_open=10.,peak_return60=9876543.,gap_count=0,gap_up_count=0,gap_down_count=0,gap_unfilled_count=0))
            self.frames[code]=f
    def signals(self,include_gaps=False):return dict(signals=self.rows)
    def stock(self,code):return self.frames[code]

class ReplayChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.service=ReplayService(self.root);self.store=FakeStore()
    def tearDown(self):self.temp.cleanup()
    def create(self,two=False):return self.service.create(self.store,['e000001','e000002'] if two else ['e000001'])
    def action(self,s,action):return self.service.action(s['id'],action,s['revision'])
    def test_candidates_and_initial_state_never_include_future_prices(self):
        candidates=self.service.candidates(self.store,{})
        self.assertNotIn('9876543',json.dumps(candidates))
        state=self.create();self.assertEqual(state['stage'],'signal');self.assertIsNone(state['entry'])
        self.assertTrue(all(b[0]<=state['signal']['date'] for b in state['bars']))
        self.assertNotIn('9876543',json.dumps(state));self.assertEqual(state['nav'],1)
    def test_buy_is_d1_open_and_sale_is_d2_open_only(self):
        state=self.action(self.create(),'buy');self.assertEqual(state['entry'],10);self.assertEqual(state['day'],1)
        self.assertAlmostEqual(state['nav'],1.05);self.assertNotIn('9876543',json.dumps(state))
        state=self.action(state,'sell');self.assertEqual(state['exit']['price'],13);self.assertEqual(state['exit']['day'],2)
        self.assertAlmostEqual(state['nav'],1.15);self.assertEqual(state['bars'][-1][1],13)
        self.assertTrue(all(v is None for v in state['bars'][-1][2:11]));self.assertEqual(state['bars'][-1][-1],'exit_open')
        self.assertNotIn('9876543',json.dumps(state))
    def test_two_round_half_weight_compounds_not_averages(self):
        s=self.action(self.action(self.create(two=True),'buy'),'sell');s=self.action(s,'next');self.assertAlmostEqual(s['nav'],1.15)
        s=self.action(self.action(s,'buy'),'sell');self.assertAlmostEqual(s['nav'],1.15*.95)
        self.assertEqual(s['completed'],2);self.assertAlmostEqual(s['max_drawdown'],-.05)
    def test_auto_close_exact_d60_no_d61(self):
        s=self.action(self.create(),'buy')
        for _ in range(59):s=self.action(s,'advance')
        self.assertEqual(s['day'],60);self.assertEqual(s['stage'],'closed')
        self.assertEqual(s['exit']['reason'],'D60收盘强制结束');self.assertEqual(s['exit']['price'],10)
        self.assertAlmostEqual(s['nav'],1)
        with self.assertRaises(ReplayError):self.action(s,'advance')
        with self.assertRaises(ReplayError):self.action(s,'sell')
    def test_d59_sale_uses_d60_open(self):
        s=self.action(self.create(),'buy')
        for _ in range(58):s=self.action(s,'advance')
        s=self.action(s,'sell');self.assertEqual(s['exit']['day'],60)
        self.assertEqual(s['exit']['date'],self.store.dates[360].strftime('%Y-%m-%d'));self.assertEqual(s['bars'][-1][4],None)
    def test_duplicate_revision_cannot_reveal_two_days(self):
        s=self.create();old=s['revision'];s=self.action(s,'buy')
        with self.assertRaises(ReplayError):self.service.action(s['id'],'advance',old)
        self.assertEqual(self.service.get(s['id'])['day'],1)
    def test_resume_uses_saved_snapshot_and_same_progress(self):
        s=self.action(self.create(),'buy');restored=ReplayService(self.root).get(s['id']);self.assertEqual(restored,s)
        self.store.frames['000001'].loc[:,'close']=999
        self.assertEqual(self.service.get(s['id']),s)
    def test_review_allowed_only_after_settlement_never_changes_nav(self):
        s=self.create()
        with self.assertRaises(ReplayError):self.action(s,'review')
        s=self.action(self.action(s,'buy'),'sell');before=s['nav'];curve=s['curve']
        s=self.action(s,'review');self.assertEqual(s['nav'],before);self.assertEqual(s['curve'],curve)
        self.assertIn('9876543',json.dumps(s));self.assertTrue(s['review'])
        with self.assertRaises(ReplayError):self.action(s,'buy')
    def test_skip_keeps_nav_and_ids_are_validated(self):
        s=self.action(self.create(two=True),'skip');self.assertEqual(s['nav'],1);s=self.action(s,'next');self.assertEqual(s['completed'],0)
        for ids in [[],['unknown'],['e000001','e000001']]:
            with self.assertRaises(ReplayError):self.service.create(self.store,ids)
        with self.assertRaises(ReplayError):self.service.get('../state')
    def test_snapshot_tamper_fails_closed(self):
        s=self.create();(self.root/s['id']/'quotes.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ReplayError):self.service.get(s['id'])
    def random_store(self,count=12):
        store=FakeStore();source=store.rows[0];event=store.events[source['id']];frame=store.frames[source['code']]
        store.rows=[];store.events={};store.frames={}
        for i in range(count):
            code=f'{i:06d}';event_id='random'+code
            store.rows.append(dict(source,id=event_id,code=code,is_leader=i<11))
            store.events[event_id]=dict(event,code=code);store.frames[code]=frame
        return store
    def test_new_random_auto_buy_5_10_20_rounds_and_review120(self):
        store=self.random_store(25)
        for row in store.rows:
            row.update(is_leader=True,date=store.dates[200].strftime('%Y-%m-%d'))
            store.events[row['id']]['signal_date']=row['date']
        for count in [5,10,20]:
            s=self.service.create(store,None,mode='random',rounds=count,filters={'scope':'leaders'})
            self.assertEqual(s['total_rounds'],count);self.assertEqual(s['stage'],'holding');self.assertEqual(s['day'],1)
            self.assertEqual(s['weight'],1);self.assertFalse(s['review']);self.assertEqual(s['bars'][-1][0],store.dates[201].strftime('%Y-%m-%d'))
            with self.assertRaises(ReplayError):self.service.round_review(s['id'],1)
            with self.assertRaises(ReplayError):self.action(s,'buy')
            s=self.action(s,'sell');self.assertTrue(s['review']);self.assertTrue(s['review_complete120'])
            self.assertEqual(s['bars'][-1][0],store.dates[320].strftime('%Y-%m-%d'))
            before=self.service.get(s['id']);review=self.service.round_review(s['id'],1)
            self.assertTrue(review['read_only']);self.assertFalse(review['has_next']);self.assertEqual(self.service.get(s['id']),before)
            s=self.action(s,'next');self.assertEqual(s['stage'],'holding');self.assertEqual(s['day'],1);self.assertFalse(s['review'])
            self.assertEqual(s['bars'][-1][0],store.dates[201].strftime('%Y-%m-%d'))
    def test_new_random_d60_exits_d61_open_and_stops_at_last_round(self):
        store=self.random_store();frame=next(iter(store.frames.values()))
        frame.iloc[361,frame.columns.get_loc('open')]=7
        s=self.service.create(store,None,mode='random',rounds=5,filters={})
        for r in range(5):
            for _ in range(59):s=self.action(s,'advance')
            self.assertEqual(s['day'],60);self.assertEqual(s['exit']['day'],61);self.assertEqual(s['exit']['price'],7)
            self.assertEqual(s['exit']['reason'],'D60到期次日开盘平仓');self.assertAlmostEqual(s['nav'],.7**(r+1))
            self.assertTrue(s['review']);self.assertFalse(s['review_complete120']);self.assertEqual(s['has_next'],r<4)
            if r<4:s=self.action(s,'next')
        with self.assertRaises(ReplayError):self.action(s,'next')
        self.assertEqual(ReplayService(self.root).get(s['id']),s)
    def test_new_random_round_validation_and_record_pagination(self):
        store=self.random_store()
        for count in [0,6,21,'5',True]:
            with self.assertRaises(ReplayError):self.service.create(store,None,mode='random',rounds=count,filters={})
        for i in range(3):self.service.create(store,None,title='test'+str(i),mode='random',rounds=5,filters={'scope':'leaders'})
        first=self.service.sessions(page=1,page_size=2);last=self.service.sessions(page=2,page_size=2)
        self.assertEqual(first['total'],3);self.assertEqual(first['pages'],2);self.assertEqual(len(last['rows']),1)
        self.assertFalse({s['id'] for s in first['rows']}&{s['id'] for s in last['rows']})
        self.assertEqual(first['rows'][0]['total_rounds'],5);self.assertEqual(first['rows'][0]['completed'],0)
    def test_random_ten_uses_filtered_pool_random_order_and_full_compounding(self):
        store=self.random_store()
        def draw(pool,count):
            self.assertEqual(len(pool),11);self.assertEqual(count,10)
            self.assertTrue(all(s['is_leader'] for s in pool))
            return list(reversed(pool[:10]))
        with patch('replay_engine.secrets.SystemRandom.sample',side_effect=draw):
            s=self.service.create(store,None,mode='random10',filters={'scope':'leaders','tag':'keep'})
        self.assertEqual(s['weight'],1);self.assertEqual(s['total_rounds'],10)
        self.assertEqual(s['signal']['id'],'random000009')
        self.assertNotIn('9876543',json.dumps(s))
        restored=ReplayService(self.root).get(s['id']);self.assertEqual(restored,s)
        seen=[]
        for i in range(10):
            seen.append(s['signal']['id'])
            with self.assertRaises(ReplayError):self.action(s,'skip')
            s=self.action(s,'buy');s=self.action(s,'sell')
            self.assertAlmostEqual(s['nav'],1.3**(i+1))
            self.assertEqual(s['has_next'],i<9)
            if i<9:s=self.action(s,'next')
        self.assertEqual(len(set(seen)),10);self.assertEqual(s['completed'],10)
        with self.assertRaises(ReplayError):self.action(s,'next')
        with self.assertRaises(ReplayError):self.action(s,'buy')
    def test_random_requires_ten_and_valid_filters_and_mode(self):
        with self.assertRaises(ReplayError):self.service.create(self.store,None,mode='random10',filters={})
        with self.assertRaises(ReplayError):self.service.create(self.store,None,mode='random10')
        with self.assertRaises(ReplayError):self.service.create(self.store,['e000001'],mode='unknown')
        s=self.service.create(self.random_store(),None,mode='random10',filters={'scope':'leaders'})
        s=self.action(s,'buy')
        for _ in range(59):s=self.action(s,'advance')
        self.assertEqual(s['exit']['reason'],'D60收盘强制结束');self.assertAlmostEqual(s['nav'],1)
    def test_old_manual_session_defaults_to_half_weight(self):
        s=self.create();path=self.root/s['id']/'state.json'
        state=json.loads(path.read_text(encoding='utf-8'));state.pop('mode');path.write_text(json.dumps(state),encoding='utf-8')
        s=self.service.get(s['id']);self.assertEqual(s['mode'],'manual');self.assertEqual(s['weight'],.5)
        s=self.action(self.action(s,'buy'),'sell');self.assertAlmostEqual(s['nav'],1.15)
    def test_http_actions_and_cross_origin_guard(self):
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url='http://127.0.0.1:'+str(server.server_port)
        def post(path,data,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            with urllib.request.urlopen(urllib.request.Request(url+path,data=json.dumps(data).encode(),headers=headers)) as r:return json.load(r)
        try:
            with patch.object(app,'REPLAY',self.service),patch.object(app.Handler,'active_store',return_value=self.store):
                s=post('/api/replay/create',dict(ids=['e000001']))
                s=post('/api/replay/action',dict(id=s['id'],action='buy',revision=s['revision']))
                self.assertEqual(s['day'],1)
                with urllib.request.urlopen(url+'/api/replay/state?id='+s['id']) as r:self.assertEqual(json.load(r)['day'],1)
                with self.assertRaises(urllib.error.HTTPError) as exc:post('/api/replay/action',dict(id=s['id'],action='advance',revision=s['revision']),'https://example.com')
                self.assertEqual(exc.exception.code,403)
                with patch.object(app.Handler,'active_store',return_value=self.random_store()):
                    random=post('/api/replay/create',dict(mode='random10',filters={'scope':'leaders','tag':'keep'}))
                    self.assertEqual(random['total_rounds'],10);self.assertEqual(random['weight'],1)
                    current=post('/api/replay/create',dict(mode='random',rounds=5,filters={'scope':'leaders'}))
                    self.assertEqual(current['stage'],'holding');self.assertEqual(current['total_rounds'],5)
                    current=post('/api/replay/action',dict(id=current['id'],action='sell',revision=current['revision']))
                    with urllib.request.urlopen(url+'/api/replay/tests?page=1') as r:self.assertGreaterEqual(json.load(r)['total'],3)
                    with urllib.request.urlopen(url+'/api/replay/round?id='+current['id']+'&round=1') as r:self.assertTrue(json.load(r)['read_only'])
                for path in ['/simulator/tests','/shell.css']:
                    with urllib.request.urlopen(url+path) as r:self.assertEqual(r.status,200)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
