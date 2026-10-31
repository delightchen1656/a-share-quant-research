import unittest
import numpy as np
import pandas as pd
from study40_two_pools import relabel,summary

class FortyTargetChecks(unittest.TestCase):
    def test_strict_target_and_incomplete_labels_not_negative(self):
        original=pd.DataFrame(dict(label_status=['complete','complete','complete','boundary_purged'],
            peak_gain60=[.40,.4001,.39,np.nan],y=[0,0,0,np.nan]))
        result=relabel(original)
        self.assertEqual(result.y.iloc[:3].tolist(),[0,1,0]);self.assertTrue(np.isnan(result.y.iloc[3]))
        self.assertEqual(original.y.iloc[1],0)
    def test_leader_is_subset_not_disjoint_and_no_keep_filter(self):
        table=pd.DataFrame(dict(label_status=['complete']*3,peak_gain60=[.8,.45,.2],is_leader=[True,True,False],
            code=['000001','000002','000003'],year=[2022]*3,gap_down_count=[1,0,0]))
        table=relabel(table);all_=summary(table);leaders=summary(table[table.is_leader])
        self.assertEqual(all_['complete'],3);self.assertEqual(leaders['complete'],2)
        self.assertEqual(leaders['positive_events'],2);self.assertEqual(all_['positive_events'],2)

if __name__=='__main__':unittest.main()
