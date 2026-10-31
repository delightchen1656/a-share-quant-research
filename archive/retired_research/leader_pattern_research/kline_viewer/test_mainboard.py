import unittest,json,tempfile,threading,urllib.request,urllib.error,datetime
from pathlib import Path
from unittest.mock import patch
import sys
import app
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import refresh_mainboard_viewer as refresh

class MainboardChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.store=app.Store()
    def test_scope_and_only_box_module(self):
        u=self.store.universe_info();self.assertEqual(u['total'],3194);self.assertEqual(u['leaders'],510)
        self.assertEqual(u['leaders_by_source'],dict(original=118,ths=405,both=13))
        self.assertEqual(set(self.store.lists),{'volume'})
        self.assertEqual(set(self.store.group_meta),{'volume'})
        self.assertTrue(all(__import__('re').fullmatch(app.MAIN_REGEX,r['code']) for r in u['stocks']))
        for code in ['300124','688223','689009','920001']:
            with self.assertRaises(KeyError):self.store.history(code)
    def test_box_signals_volume12_and_earliest_per_box(self):
        j=self.store.signals();self.assertEqual(j['group'],'volume');self.assertEqual(j['total'],1440)
        self.assertEqual(j['stocks'],1132);self.assertEqual(sum(r['is_leader'] for r in j['signals']),233)
        self.assertEqual(j['min_volume_multiple'],1.2)
        self.assertEqual(j['structure_version'],'base_volume_strong_bullish_one_box_v5_volume12')
        self.assertEqual([g['id'] for g in j['groups']],['volume'])
        self.assertEqual(len({r['box_id'] for r in j['signals']}),1440)
        self.assertTrue(all(r['date']==r['first_signal_date'] for r in j['signals']))
        for r in j['signals']:
            self.assertGreater(r['base_decline_volume_ratio'],1)
            self.assertGreaterEqual(r['volume_multiple'],1.2)
            self.assertGreaterEqual(r['body_range_ratio'],.6-1e-10)
            self.assertLessEqual(r['upper_shadow_ratio'],.2+1e-10)
    def test_leader_union_preserves_membership_and_sources(self):
        from leader_pool import load_pool,membership
        pool,manifest=load_pool();self.assertEqual(len(pool),687);self.assertEqual(manifest['mainboard_total'],510)
        self.assertTrue(pool.code.is_unique)
        lookup=pool.set_index('code').to_dict('index')
        flags={r['code']:r for r in self.store.universe_info()['stocks']}
        for code,original,ths in [('000400',True,False),('000002',False,True),('000636',True,True)]:
            self.assertTrue(flags[code]['is_leader'])
            self.assertEqual(flags[code]['is_original_leader'],original)
            self.assertEqual(flags[code]['is_ths_leader'],ths)
            self.assertEqual(flags[code]['leader_source'],membership(code,lookup)['leader_source'])
        self.assertFalse(membership('000001',lookup)['is_leader'])
        for code,r in flags.items():
            self.assertEqual(r['is_leader'],r['is_original_leader'] or r['is_ths_leader'])
    def test_full_history_independent_of_signal_and_box_phases(self):
        f=self.store.history('000001');self.assertTrue(f['full_history']);self.assertGreater(len(f['bars']),1000)
        self.assertEqual(f['bars'][0][0],f['actual_start']);self.assertEqual(f['bars'][-1][0],f['actual_end'])
        r=self.store.signals()['signals'][0];f=self.store.history(r['code'],'volume',r['id'])
        phases=[b[-1] for b in f['bars'] if b[-1]]
        self.assertEqual(phases,['decline']*20+['base']*15+['spike'])
        self.assertTrue(all(b[5]>0 for b in f['bars']))
        json.dumps(f,allow_nan=False)
    def test_downside_observation_matches_chart_prices_and_maturity(self):
        j=self.store.signals();self.assertEqual(j['observation_version'],'future60_nextopen_high_low_v1')
        self.assertEqual(j['return_basis'],'next_session_open')
        for r in j['signals']:
            self.assertEqual(r['trough_complete60'],r['peak_complete60'])
            self.assertEqual(r['trough_status60'],r['peak_status60'])
            if r['trough_complete60']:
                self.assertGreaterEqual(r['max_drop60'],0)
                self.assertAlmostEqual(r['max_drop60'],max(0,-r['trough_return60']))
            else:self.assertIsNone(r['max_drop60'])
        r=next(r for r in j['signals'] if r['peak_complete60'])
        f=self.store.history(r['code'],'volume',r['id'])
        future=[b for b in f['bars'] if r['date']<b[0]<=r['window_end_date60']]
        self.assertEqual(len(future),60)
        worst=min(future,key=lambda b:b[3])
        self.assertEqual(worst[0],r['trough_date60'])
        self.assertAlmostEqual(worst[3],r['trough_price60'])
        reference=next(b[1] for b in f['bars'] if b[0]==r['entry_date'])
        self.assertEqual(reference,r['entry_open'])
        self.assertEqual(r['entry_date'],future[0][0])
        self.assertAlmostEqual(r['peak_return60'],max(b[2] for b in future)/reference-1)
        self.assertAlmostEqual(r['max_drop60'],max(0,1-worst[3]/reference))
        self.assertEqual(f['event']['max_drop60'],r['max_drop60'])
        self.assertEqual(f['event']['entry_open'],r['entry_open'])
    def test_gap_labels_only_augment_existing_frozen_signals(self):
        baseline=self.store.signals();tagged=self.store.signals(include_gaps=True)
        self.assertEqual(tagged['gap_version'],'base_internal_full_gap_v1')
        self.assertEqual([r['id'] for r in baseline['signals']],[r['id'] for r in tagged['signals']])
        gaps=[r for r in tagged['signals'] if r['gap_count']]
        self.assertEqual(len(gaps),450);self.assertEqual(len({r['code'] for r in gaps}),414)
        self.assertEqual(sum(r['is_leader'] for r in gaps),66)
        for old,new in zip(baseline['signals'],tagged['signals']):
            self.assertEqual(old,{k:v for k,v in new.items() if not k.startswith('gap_')})
            self.assertEqual(new['gap_count'],new['gap_up_count']+new['gap_down_count'])
            for g in new['gap_details']:
                self.assertTrue(g['raw_confirmed'])
                self.assertGreater(g['date'],self.store.events[new['id']]['base_start'])
                self.assertLess(g['date'],new['date'])
                if g['fill_date']:self.assertLessEqual(g['fill_date'],new['date'])
    def test_http_defaults_box_and_removed_modules_unavailable(self):
        original=app.Handler.store;app.Handler.store=self.store
        server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(url+'/api/signals') as r:j=json.load(r)
            self.assertEqual(j['group'],'volume');self.assertEqual(len(j['groups']),1)
            for path in ['/api/signals?group=first','/api/signals?group=ma60','/api/history?code=000001&group=first']:
                with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(url+path)
                self.assertEqual(err.exception.code,404)
            with urllib.request.urlopen(url+'/') as r:html=r.read().decode('utf-8')
            self.assertNotIn('only-typical53',html);self.assertNotIn('id="pattern"',html)
        finally:server.shutdown();server.server_close();worker.join();app.Handler.store=original
    def test_current_generation_can_reload_atomically(self):
        original=json.loads(app.CURRENT.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'CURRENT.json';changed=dict(original,generation=original['generation']+'_test')
            p.write_text(json.dumps(changed),encoding='utf-8')
            old=app.Handler.store;app.Handler.store=self.store
            try:
                with patch.object(app,'CURRENT',p):new=app.Handler.active_store()
                self.assertEqual(new.generation,changed['generation']);self.assertEqual(set(new.lists),{'volume'})
            finally:app.Handler.store=old
    def test_refresh_waits_for_committed_quotes_and_preserves_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            area=Path(tmp);current=area/'CURRENT.json';current.write_text('{"cutoff":"2026-10-26"}',encoding='utf-8');before=current.read_bytes()
            with patch.object(refresh,'ROOT',area),patch.object(refresh,'AREA',area),patch.object(refresh,'CURRENT',current),patch.object(refresh,'STATUS',area/'status.json'),patch.object(refresh,'META',area/'meta'):
                result=refresh.once('2026-10-27');self.assertEqual(result['status'],'waiting_for_market_commit')
                self.assertEqual(current.read_bytes(),before)
                result=refresh.once('2026-10-01');self.assertEqual(result['status'],'non_trading_day')
                self.assertEqual(current.read_bytes(),before)

    def test_retry_is_two_hours_and_continues_overnight_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            area=Path(tmp);current=area/'CURRENT.json'
            current.write_text('{"status":"ok","cutoff":"2026-10-26"}',encoding='utf-8')
            late=datetime.datetime(2026,10,28,1,0,tzinfo=refresh.TZ)
            with patch.object(refresh,'AREA',area),patch.object(refresh,'STATUS',area/'status.json'),patch.object(refresh,'CURRENT',current),patch.object(refresh,'now',return_value=late),patch.object(refresh.time,'sleep') as sleep,patch.object(refresh,'once',side_effect=[RuntimeError('temporary failure'),{'status':'waiting_for_market_commit'},{'status':'updated'}]) as once:
                self.assertEqual(refresh.watch('2026-10-27')['status'],'updated')
                self.assertEqual(once.call_count,3)
                self.assertEqual(sleep.call_args_list,[__import__('unittest').mock.call(7200),__import__('unittest').mock.call(7200)])

    def test_restart_keeps_previous_due_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            area=Path(tmp);current=area/'CURRENT.json';status=area/'status.json'
            current.write_text('{"status":"ok","cutoff":"2026-10-26"}',encoding='utf-8')
            status.write_text(json.dumps({'status':'waiting_for_market_commit','target':'2026-10-27','checked_at':'2026-10-27T19:00:00+08:00'}),encoding='utf-8')
            at=datetime.datetime(2026,10,27,19,10,tzinfo=refresh.TZ)
            with patch.object(refresh,'AREA',area),patch.object(refresh,'STATUS',status),patch.object(refresh,'CURRENT',current),patch.object(refresh,'now',return_value=at),patch.object(refresh.time,'sleep') as sleep,patch.object(refresh,'once',return_value={'status':'updated'}):
                self.assertEqual(refresh.watch('2026-10-27')['status'],'updated')
                sleep.assert_called_once_with(6600)
                saved=json.loads(status.read_text(encoding='utf-8'))
                self.assertEqual(saved['next_check_at'],'2026-10-27T21:00:00+08:00')

if __name__=='__main__':unittest.main(verbosity=2)
