import unittest
import numpy as np
import pandas as pd
from uniform_atr import calculate


class UniformAtrTest(unittest.TestCase):
    def bars(self):
        close=np.linspace(10,17,100)
        return pd.DataFrame(dict(date=pd.bdate_range('2024-10-01',periods=100),open=close,high=close*1.012,
            low=close*.988,close=close,preclose=np.r_[close[0],close[:-1]],tradestatus=1))

    def test_both_causal_and_scale_invariant(self):
        bars=self.bars();full=calculate(bars)
        prefix=calculate(bars.iloc[:60])
        np.testing.assert_array_equal(full.iloc[:60][['relative','price']].to_numpy(),prefix[['relative','price']].to_numpy())
        scaled=bars.copy();scaled[['open','high','low','close','preclose']]*=3
        np.testing.assert_allclose(full[['relative','price']],calculate(scaled)[['relative','price']],rtol=0,atol=1e-14)

    def test_formulas_are_not_equivalent_in_trending_prices(self):
        values=calculate(self.bars())
        self.assertGreater(float((values.relative-values.price).abs().max()),.0001)
        self.assertTrue(values.dropna().relative.between(.015,.05).all())
        self.assertTrue(values.dropna().price.between(.015,.05).all())


if __name__=='__main__':unittest.main()
