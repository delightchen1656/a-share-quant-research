"""Development-only refinement of long momentum; no audit-driven selection."""
import hashlib
import itertools
import monthly_A_signal_blend as x

CONFIGS=x.CONFIGS[:2]+[dict(id='L%02d'%(i+1),strict=True,signal='mom12_'+phase,blend=weight)
    for i,(phase,weight) in enumerate(itertools.product(('both','strong','weak'),(.03,.06,.09,.12)))]
OUT=x.HERE/'monthly_A_signal_refine_20260925'
original_score=x.blend_score

def score(q,strong,signal=None,weight=0.):
    if signal is None:return original_score(q,strong)
    feature,phase=signal.rsplit('_',1)
    if (phase=='strong' and not strong) or (phase=='weak' and strong):
        return original_score(q,strong)
    return original_score(q,strong,feature,weight)

def main():
    x.CONFIGS=CONFIGS;x.OUT=OUT;x.blend_score=score
    original_save=x.save
    def save(name,value):
        if name=='protocol.json':
            value['method']='Original regime/universe, fixed80%target,6stocks,monthly. Long momentum252-21rank blended at3/6/9/12%;allregimes or strongonly or weakonly. In inactive regime exact originalscore. Same gates and fees as initial study.'
            value['refinement_basis']='N04 development Sharpe1.228 but failed P10 and drawdown;all initial18 failed dev gate, none admitted to audit. This12combo refinement is based on development results, not unseen data or audit selection.'
        if name=='inputs.json':
            path=x.HERE/'monthly_A_signal_refine.py'
            value.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        original_save(name,value)
    x.save=save
    x.main()
    report=OUT/'REPORT.md'
    report.write_text(report.read_text(encoding='utf-8').replace('18组预先定义候选','12组开发阶段细调候选'),encoding='utf-8')

if __name__=='__main__':main()
