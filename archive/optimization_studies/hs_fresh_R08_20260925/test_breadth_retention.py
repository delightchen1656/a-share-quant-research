import unittest
from round21_breadth_retention import CONFIGS

class BreadthTests(unittest.TestCase):
    def test_predeclared_grid_and_controls(self):
        self.assertEqual(len(CONFIGS),14)
        self.assertEqual([(c['count'],c['buffer'],c['exposure']) for c in CONFIGS[:2]],[(12,24,.85),(12,24,.95)])
        self.assertEqual(max(c['buffer'] for c in CONFIGS),72)
        self.assertEqual(len({(c['count'],c['buffer'],c['exposure']) for c in CONFIGS}),14)
        self.assertTrue(all(c['affordable'] and c['minimum']==1500 and c['power']==0 for c in CONFIGS))

if __name__=='__main__':unittest.main()
