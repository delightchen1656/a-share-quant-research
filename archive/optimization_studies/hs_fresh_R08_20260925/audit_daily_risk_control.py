"""Previously known full-period controls; not a new candidate selection exercise."""
import json
import numpy as np
import pandas as pd
import research as r
import round19_daily_risk as new

if __name__=='__main__':
    cfgs=[new.CONFIGS[1],new.CONFIGS[3]]
    references=[('round09_affordability','J24'),('round11_high_floor','R08')]
    new.install();study=new.Study(cfgs);results=[]
    for cfg,(folder,cid) in zip(cfgs,references):
        stats,curve,trades=study.run(cfg,study.dev[0],r.END)
        old=json.loads((r.HERE/folder/'summary.json').read_text(encoding='utf-8'))['full'][cid]
        for key in ('final_equity','annualized','sharpe','drawdown','mean_exposure','fees','orders'):
            np.testing.assert_allclose(stats[key],old[key],rtol=1e-12,atol=1e-8)
        assert stats['resize_signal_days']==0 and stats['resize_orders']==0
        old_curve=pd.DataFrame(json.loads((r.HERE/folder/(cid+'_curve.json')).read_text(encoding='utf-8')))
        np.testing.assert_allclose(curve.equity,old_curve.equity,rtol=1e-12,atol=1e-8)
        results.append(dict(id=cfg['id'],reference=folder+'/'+cid,exact_full_curve_and_metrics=True,stats=stats))
        print('CONTROL_MATCH',cfg['id'],cid,stats['sharpe'],flush=True)
    r.save(r.HERE/'daily_risk_control_audit.json',results)
