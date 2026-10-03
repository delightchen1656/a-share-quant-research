"""Fixed rolling models, development-only selection and common calendar execution."""
import itertools
import research as r
from learning_models import PRED,MODELS
from round03 import calendar_dates
from round04 import Study as CalendarStudy

CONFIGS=[dict(id='M%02d'%(i+1),family=family,size='all',cadence=cadence,
    interval=5 if cadence=='weekly' else 20,count=count,buffer=count*buffer,
    exposure=.85,power=.5,minimum=1500)
    for i,(family,cadence,count,buffer) in enumerate(itertools.product(
        [k+str(h) for k,h in MODELS],('weekly','monthly'),(8,12),(1,2)))]

def rank(frame,cfg):
    q=frame.dropna(subset=[cfg['family']]).sort_values([cfg['family'],'symbol'],ascending=[False,True])
    return q.head(cfg['buffer'])[['symbol','downside']]

class Study(CalendarStudy):
    def run(self,cfg,start,end=None,stress=False):
        # Parent owns the unchanged execution ledger; change only its schedule helper.
        import round04
        original=round04.calendar_dates
        round04.calendar_dates=lambda cal,a,b,ignored:calendar_dates(cal,a,b,cfg['cadence'])
        try:return super().run(cfg,start,end,stress)
        finally:round04.calendar_dates=original

def install():
    r.FEATURES=PRED;r.MIN_SIGNAL_VOL=.001;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round06_learning';r.rank=rank;r.Study=Study

if __name__=='__main__':
    assert PRED.exists(),'Generate audited past-only model predictions first'
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='4 fixed quarterly rolling learners; predictive ranks not realized returns;85%exposure,weekly/monthly,8/12stocks,buffer1/2',
            training_protocol=str(r.HERE/'learning_models/protocol.json'),dev='24quarterly2020/21+0/5/10 starts,24months; freeze development winners before full test')
        save(path,obj)
    r.save=write;r.main()
