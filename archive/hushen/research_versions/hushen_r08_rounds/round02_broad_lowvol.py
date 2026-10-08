"""Second bounded round: lower-vol eligibility and broader stock baskets."""
import itertools
import research as r

if __name__=='__main__':
    r.ROUND_NAME='round02_broad_lowvol'
    r.FEATURES=r.HERE/'features_historical_lowvol.parquet'
    r.MIN_SIGNAL_VOL=.001
    r.CONFIGS=[dict(id='B%02d'%(i+1),family=family,size=size,interval=interval,count=count,buffer=count*2,exposure=.85,power=.5,minimum=1500)
        for i,(family,size,count,interval) in enumerate(itertools.product(('defensive','pullback','barbell','turn_contraction'),('all','small','mid','large'),(12,20),(20,40)))]
    r.main()
