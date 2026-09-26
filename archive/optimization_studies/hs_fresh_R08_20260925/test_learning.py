import unittest
import numpy as np
import pandas as pd
from learning_models import INPUTS,normalize,training_mask,model

class LearningTests(unittest.TestCase):
    def test_execution_cadence_dispatch(self):
        from unittest.mock import patch
        from round06_learning import Study,CalendarStudy
        import round04
        cal=pd.bdate_range('2020-01-01','2020-06-30')
        original=round04.calendar_dates
        def capture(self,cfg,start,end,stress):
            return round04.calendar_dates(cal,start,end,'monthly')
        instance=Study.__new__(Study)
        with patch.object(CalendarStudy,'run',capture):
            a=instance.run({'cadence':'weekly'},cal[1],cal[-1])
            b=instance.run({'cadence':'weekly'},cal[8],cal[-1])
            c=instance.run({'cadence':'monthly'},cal[1],cal[-1])
        self.assertGreater(len(a),len(c)*3)
        self.assertEqual([d for d in a if d>cal[8]],b[1:])
        self.assertIs(round04.calendar_dates,original)

    def test_future_mutation_cannot_change_past_fit(self):
        rng=np.random.default_rng(42);cal=pd.bdate_range('2019-01-01',periods=300)
        f=pd.DataFrame([(d,d+pd.offsets.BDay(),d+pd.offsets.BDay(20),s) for d in cal for s in range(12)],columns=['signal_date','execute_date','label_end20','symbol'])
        for col in INPUTS:f[col]=rng.normal(size=len(f))
        f['target20']=rng.normal(size=len(f));fit=cal[220]
        changed=f.copy();future=changed.label_end20>=fit
        changed.loc[future,'target20']=999
        changed.loc[changed.signal_date>=fit,INPUTS]=-999
        mask=training_mask(f,fit,20,cal)
        self.assertTrue((f.loc[mask,'label_end20']<fit).all())
        self.assertTrue((f.loc[mask,'execute_date']<fit).all())
        past=f.signal_date<fit
        np.testing.assert_array_equal(normalize(f).loc[past],normalize(changed).loc[past])
        ys=[z.groupby('signal_date').target20.rank(pct=True)-.5 for z in (f,changed)]
        # Changing immature labels cannot change any eligible training target.
        np.testing.assert_array_equal(ys[0].loc[mask],ys[1].loc[mask])
        fits=[model('ridge').fit(normalize(z).loc[mask],y.loc[mask]) for z,y in zip((f,changed),ys)]
        np.testing.assert_array_equal(fits[0].coef_,fits[1].coef_)

if __name__=='__main__':unittest.main()
