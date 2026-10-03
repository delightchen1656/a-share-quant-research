"""Bounded refinement of development-selected carry_trend mid-cap route."""
import itertools
import research as r
import round04 as base

if __name__=='__main__':
    base.install()
    r.ROUND_NAME='round05_adjustment_weights'
    r.CONFIGS=[dict(id='E%02d'%(i+1),family='carry_trend',size='mid',cadence=cadence,interval=20 if cadence=='monthly' else 40,
        count=count,buffer=count*buffer_multiple,exposure=.85,power=power,minimum=1500)
        for i,(cadence,count,buffer_multiple,power) in enumerate(itertools.product(('monthly','bimonthly'),(6,8,12),(1,2),(0.,.5,1.)))]
    original_save=r.save
    def save(path,obj):
        if path.name=='protocol.json':obj.update(method='Same carry_trend mid-cap proxy route, common monthly/odd-month dates,85%target. Count6/8/12;retentionbuffer1x/2x;inverse-downsidepower0/.5/1. No cash timing.',
            selection_basis='D44/D42 were round04 development winners; full results have now also been observed. This is repeated-history refinement,NOT fresh OOS.',dev='24 starts2020/21quarter+0/5/10sessions,24months. Existing screening and full target gates unchanged.')
        original_save(path,obj)
    r.save=save;r.main()
