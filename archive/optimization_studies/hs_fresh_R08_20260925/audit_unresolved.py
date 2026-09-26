import json
import research as r

if __name__=='__main__':
    source=json.loads((r.HERE/'round02_broad_lowvol/summary.json').read_text(encoding='utf-8'))
    r.FEATURES=r.Path(source['feature_path'])
    configs=[c for c in source['winners'] if c['id'] in ('B42','B44')]
    study=r.Study(configs);results={}
    for c in configs:
        z,_,_=study.run(c,study.dev[0],r.END)
        results[c['id']]=dict(stats=z,unresolved=r.e.UNRESOLVED_ACTIONS)
    r.save(r.HERE/'round02_broad_lowvol/unresolved_audit.json',results)
    print(json.dumps(results),flush=True)
