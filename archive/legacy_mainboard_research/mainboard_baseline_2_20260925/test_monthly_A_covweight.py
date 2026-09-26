import unittest
import numpy as np
from monthly_A_covweight_sharpe import weights

class Covariance(unittest.TestCase):
    def test_equal_covariance_equal_weights(self):
        for kind in ('minvar','riskparity'):
            np.testing.assert_allclose(weights(np.eye(6),kind,.25),np.ones(6)/6,atol=1e-6)

    def test_bounds_and_budget(self):
        cov=np.diag([.1,.2,.3,1,2,3])
        for kind in ('minvar','riskparity'):
            w=weights(cov,kind,.75);self.assertAlmostEqual(w.sum(),1)
            self.assertGreaterEqual(w.min(),.05-1e-6);self.assertLessEqual(w.max(),.25+1e-6)

if __name__=='__main__':unittest.main()
