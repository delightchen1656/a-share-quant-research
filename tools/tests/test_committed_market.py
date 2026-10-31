from pathlib import Path
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from committed_market import select_commit

class CommitSelectionTests(unittest.TestCase):
    def test_backfill_name_cannot_hide_current_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';updates=root/'updates'
            def save(p,value):
                p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf8')
            record=dict(status='ok',target='2024-12-31',updated_at='final',datasets={'hushen':{}},validation={'transactional_staging':True},committed_files=1)
            save(data/'metadata/refresh_20241231.json',record)
            save(updates/'z_historical_backfill/audit.json',dict(status='ok',target='2024-12-30'))
            save(updates/'20241231/audit.json',dict(record,updated_at='earlier'))
            save(updates/'20241231_post_backfill/audit.json',record)
            save(updates/'20241231_post_backfill/commit_manifest.json',dict(target=record['target'],files=[{}]))
            path,_,_=select_commit(data,updates)
            self.assertEqual(path.parent.name,'20241231_post_backfill')
            (updates/'unfinished/staging').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'暂存'):select_commit(data,updates)
    def test_never_falls_back_to_old_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data/metadata').mkdir(parents=True);(root/'updates').mkdir()
            (root/'data/metadata/refresh_20241231.json').write_text(json.dumps(dict(status='ok',target='2024-12-31')))
            with self.assertRaisesRegex(ValueError,'一致'):select_commit(root/'data',root/'updates')

if __name__=='__main__':unittest.main()
