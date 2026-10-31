import tempfile
import unittest
from pathlib import Path
from store import Ledger
from reset_account import reset_account


class ResetAccountTest(unittest.TestCase):
    def test_preserve_cash_clear_decisions_positions_and_confirmations_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'ledger.sqlite3')
            ledger.append('cash_adjust',dict(amount=-94320.04,note='示例'))
            ledger.append('accept',dict(signal_id='s1',symbol='600000.SH',name='示例',signal_date='2026-10-19',atr=.03,trigger=10.,quantity=100))
            ledger.confirm('2026-10-19',5679.96,5679.96)
            ledger.observe('before_reset','2026-10-19','review',5679.96,5679.96)
            (Path(tmp)/'finished_2026-10-19.json').write_text('{}')
            result=reset_account(tmp,5679.96)
            self.assertTrue(Path(result['backup']).exists())
            state=ledger.state()
            self.assertEqual(state['cash'],5679.96)
            self.assertEqual(state['realized'],0)
            self.assertEqual(state['free_slots'],5)
            self.assertFalse(state['orders'] or state['positions'] or state['decisions'])
            self.assertIsNone(ledger.confirmation('2026-10-19'))
            self.assertEqual(len(ledger.events()),1)
            with ledger.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM account_observations').fetchone()[0],0)
            self.assertFalse((Path(tmp)/'finished_2026-10-19.json').exists())
            ledger.restore(Path(result['backup']).name)
            self.assertEqual(len(ledger.events()),2)
            self.assertEqual(len(ledger.state()['orders']),1)

    def test_stale_cash_refuses_before_clearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'ledger.sqlite3')
            with self.assertRaises(ValueError):reset_account(tmp,5000)
            self.assertEqual(ledger.state()['cash'],100000)


if __name__=='__main__':unittest.main()
