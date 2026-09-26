import unittest
import numpy as np
import pandas as pd
from supermind_performance import measure

class Metrics(unittest.TestCase):
    def test_known_values_and_missing_rf(self):
        q=pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02','2024-01-03']),equity=[110000.,99000.]))
        m=measure(q)
        self.assertIsNone(m['sharpe']);self.assertAlmostEqual(m['volatility'],.1*np.sqrt(250))
        self.assertAlmostEqual(m['annualized'],.99**125-1);self.assertAlmostEqual(m['drawdown'],-.1)
        known=measure(q,risk_free_annual=.02)
        self.assertAlmostEqual(known['sharpe'],(m['annualized']-.02)/m['volatility'])

    def test_first_day_loss_counts_as_drawdown(self):
        q=pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02']),equity=[99000.]))
        self.assertAlmostEqual(measure(q)['drawdown'],-.01)

    def test_duplicate_dates_rejected(self):
        q=pd.DataFrame(dict(date=pd.to_datetime(['2024-01-02']*2),equity=[100000.,101000.]))
        with self.assertRaises(ValueError):measure(q)

if __name__=='__main__':unittest.main()
