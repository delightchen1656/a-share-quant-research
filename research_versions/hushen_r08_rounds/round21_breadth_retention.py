"""Bounded breadth/retention study, unchanged price signal and original engine."""
import hashlib,itertools
import research as r
import execution as original_engine
import round08_long_momentum as signals
from round09_affordability import Study

CHOICES=[(12,2,.85),(12,2,.95)]+list(itertools.product((16,20,24),(2,3),(.85,.95)))
CONFIGS=[dict(id='P%02d'%(i+1),family='carry_long',size='mid',cadence='bimonthly',interval=40,
    count=count,buffer=count*multiple,exposure=exposure,power=0,minimum=1500,affordable=True)
    for i,(count,multiple,exposure) in enumerate(CHOICES)]

def install():
    r.e=original_engine;r.FEATURES=signals.FEATURES;r.MIN_SIGNAL_VOL=.001;r.rank=signals.rank;r.CONFIGS=CONFIGS
    r.ROUND_NAME='round21_breadth_retention';r.Study=Study

if __name__=='__main__':
    install();save=r.save
    def write(path,obj):
        if path.name=='protocol.json':obj.update(method='14 predeclared:12known-control stocks2x85/95%;16/20/24stocks x2/3retention x85/95%;carry_long mid bimonthly equalweight;72candidatepool frommaxbuffer;original affordability,fees,limits,minadjustment1500;no cash timing',
            implementation_sha256=hashlib.sha256(r.Path(__file__).read_bytes()).hexdigest())
        save(path,obj)
    r.save=write;r.main()
