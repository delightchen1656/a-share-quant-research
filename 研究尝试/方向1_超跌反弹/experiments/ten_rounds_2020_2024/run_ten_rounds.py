"""Registered sequential training search, then frozen-only 2024 evaluation."""
import hashlib,importlib.util,json,sys,traceback
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def config_hash(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def module(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
    protocol=read(HERE/'PROTOCOL.json');phash=sha(HERE/'PROTOCOL.json')
    prep=module('ten_prepare',HERE/'prepare.py');account=module('ten_account',HERE/'account.py')
    manifest=prep.INPUT/'RESEARCH_2020_2024_MANIFEST.json'
    assert sha(manifest)==protocol['data_manifest_sha256']
    def guard(event,values):
        if event=='open' and not isinstance(values[0],int) and 'holdout_restricted' in Path(values[0]).parts:raise PermissionError('No restricted input access')
    sys.addaudithook(guard)
    d,dates,ordinal,quotes,factors,actions,covered,suspended=prep.prepare('RESEARCH_2020_2024_MANIFEST.json','RESEARCH_QUERY_PLAN.json')
    features=sorted({c['filter']['feature'] for r in protocol['rounds'] for c in r['changes'] if 'filter' in c}|{c['priority'].rsplit('_',1)[0] for r in protocol['rounds'] for c in r['changes'] if 'priority' in c})
    save(HERE/'FEATURE_AUDIT.json',dict(features=features,nonfinite_counts={f:int((~np.isfinite(pd.to_numeric(d[f],errors='coerce'))).sum()) for f in features},feature_timing=protocol['feature_timing'],base_signal_count=len(d),signals_per_year={str(y):len(g) for y,g in d.groupby(d.date.str[:4])}))
    training=d.loc[d.date<='2023-12-31'].copy();results={};configs={};statistics={};attempts=[];rounds=[];all_frozen=False
    def apply_filters(frame,config):
        mask=pd.Series(True,index=frame.index)
        for f in config['filters']:
            z=pd.to_numeric(frame[f['feature']],errors='coerce');value=f['value']
            selected=(z>=value if f['op']=='>=' else z<=value if f['op']=='<=' else z<value)
            mask&=selected.fillna(False)
        return frame.loc[mask].copy()
    def run(cid,config,stage):
        if stage=='stability' and not all_frozen:raise RuntimeError('All ten selections must freeze before 2024')
        frame=apply_filters(training if stage=='training' else d,config)
        ids=set(zip(frame.code,frame.date));folder=HERE/(stage+'_runs')/cid;folder.mkdir(parents=True,exist_ok=True)
        save(folder/'CONFIG.json',dict(config=config,config_sha256=config_hash(config),protocol_sha256=phash))
        account.OUT=folder
        kwargs={k:v for k,v in config.items() if k!='filters'}
        try:
            result=account.run(frame,{'sample':ids},dates,ordinal,quotes,factors,actions,'sample',True,100000,quiet=True,coverage_pairs=covered,suspended_entries=suspended,end_date='2023-12-31' if stage=='training' else '2024-12-31',**kwargs)
        except Exception as exc:
            save(HERE/'BLOCKED.json',dict(stage=stage,candidate=cid,config=config,error=str(exc),traceback=traceback.format_exc(),parameters_changed=False))
            raise
        save(folder/'RESULT.json',result)
        return result
    def stats(result):
        rows=result['yearly'];assert [r['year'] for r in rows]==[2020,2021,2022,2023]
        rr=[r['return_pct'] for r in rows];dd=max(abs(r['max_drawdown']) for r in rows)
        return dict(score=float(np.mean(rr)-.5*dd),mean_annual_return=float(np.mean(rr)),worst_annual_return=min(rr),largest_annual_drawdown=dd,returns=rr,total_return=result['summary']['total_return'],full_drawdown=abs(result['summary']['max_drawdown']),terminal_equity=result['summary']['final_equity'])
    for cid,config in [('anchor_v3',protocol['anchor_v3']),('anchor_prior',protocol['initial_incumbent'])]:
        configs[cid]=config;results[cid]=run(cid,config,'training');statistics[cid]=stats(results[cid])
    fixed=statistics['anchor_v3']
    def eligibility(s):
        reasons=[];improved=sum(a>b for a,b in zip(s['returns'],fixed['returns']))
        if s['worst_annual_return']<fixed['worst_annual_return']-.02:reasons.append('worst_year_floor_failed')
        if improved<2:reasons.append('fewer_than_two_years_above_fixed_v3')
        return dict(eligible=not reasons,guard_reasons=reasons,improved_years_vs_v3=improved)
    for cid in statistics:statistics[cid].update(eligibility(statistics[cid]))
    incumbent='anchor_prior'
    for spec in protocol['rounds']:
        n=spec['number'];folder=HERE/f'round_{n:02d}';folder.mkdir(exist_ok=True)
        before=incumbent;candidate_configs={}
        for change in spec['changes']:
            config=json.loads(json.dumps(configs[before]));cid=f'R{n:02d}_{change["id"]}'
            for key,value in change.items():
                if key=='id':continue
                if key=='filter':config['filters'].append(value)
                else:config[key]=value
            candidate_configs[cid]=config;configs[cid]=config
        register=dict(round=n,question=spec['question'],protocol_sha256=phash,inherited_candidate=before,inherited_config_hash=config_hash(configs[before]),candidate_count=len(candidate_configs),candidates={cid:dict(config=c,sha256=config_hash(c)) for cid,c in candidate_configs.items()})
        save(folder/'CANDIDATES_FROZEN.json',register);candidate_hash=sha(folder/'CANDIDATES_FROZEN.json')
        (folder/'CANDIDATES_FROZEN.sha256').write_text(candidate_hash+'\n',encoding='ascii')
        eligible=[]
        for cid,config in candidate_configs.items():
            results[cid]=run(cid,config,'training');s=stats(results[cid]);s.update(eligibility(s));statistics[cid]=s
            promote=s['eligible'] and s['score']>statistics[before]['score']+1e-12
            if promote:eligible.append(cid)
            reasons=list(s['guard_reasons'])
            if s['score']<=statistics[before]['score']+1e-12:reasons.append('no_strict_score_gain_over_incumbent')
            attempts.append(dict(round=n,candidate=cid,question=spec['question'],config=config,config_sha256=config_hash(config),**s,promotable=promote,rejection_reasons=reasons))
        if eligible:incumbent=sorted(eligible,key=lambda c:(-statistics[c]['score'],statistics[c]['full_drawdown'],c))[0]
        record=dict(round=n,question=spec['question'],candidate_count=len(candidate_configs),inherited=before,selected=incumbent,promoted=incumbent!=before,candidate_register_sha256=candidate_hash,selected_config=configs[incumbent],selected_config_sha256=config_hash(configs[incumbent]),training_statistics=statistics[incumbent],attempts=[a for a in attempts if a['round']==n],stage='frozen_before_any_new_batch_2024_account_run')
        save(folder/'SELECTION_FROZEN.json',record);rounds.append(record)
        print(json.dumps(dict(round=n,candidates=len(candidate_configs),selected=incumbent,promoted=record['promoted'],score=statistics[incumbent]['score']),ensure_ascii=False),flush=True)
    highest=sorted(results,key=lambda c:(-statistics[c]['terminal_equity'],statistics[c]['full_drawdown'],c))[0]
    frozen=dict(protocol_sha256=phash,rounds=[dict(round=r['round'],selected=r['selected'],selection_sha256=sha(HERE/f'round_{r["round"]:02d}'/'SELECTION_FROZEN.json')) for r in rounds],final_candidate=incumbent,final_config=configs[incumbent],highest_training_return_candidate=highest,highest_training_return_config=configs[highest],highest_training_return_statistics=statistics[highest],anchors=['anchor_v3','anchor_prior'],training_end='2023-12-31',candidate_attempts=len(attempts),stage='all_ten_selections_frozen_before_2024',prior_2024_seen=True)
    save(HERE/'ALL_SELECTIONS_FROZEN.json',frozen);frozenhash=sha(HERE/'ALL_SELECTIONS_FROZEN.json');all_frozen=True
    save(HERE/'ALL_ATTEMPTS.json',attempts)
    pd.DataFrame([{k:v for k,v in a.items() if k not in ['config','returns','rejection_reasons','guard_reasons']}|{'config':json.dumps(a['config'],sort_keys=True),'returns':json.dumps(a['returns']),'rejection_reasons':';'.join(a['rejection_reasons'])} for a in attempts]).to_csv(HERE/'all_attempts.csv',index=False,encoding='utf-8-sig')
    stability={};unique_ids=sorted(set(['anchor_v3','anchor_prior',highest]+[r['selected'] for r in rounds]))
    for cid in unique_ids:
        stability[cid]=run(cid,configs[cid],'stability')
    assert sha(HERE/'ALL_SELECTIONS_FROZEN.json')==frozenhash
    for r in frozen['rounds']:assert sha(HERE/f'round_{r["round"]:02d}'/'SELECTION_FROZEN.json')==r['selection_sha256']
    save(HERE/'STABILITY.json',dict(all_selection_sha256=frozenhash,evaluated_candidates=unique_ids,results=stability,selection_uses_2024=False,prior_2024_seen=True))
    save(HERE/'TRAINING_SUMMARY.json',dict(results={cid:dict(summary=r['summary'],yearly=r['yearly'],statistics=statistics[cid],config=configs[cid]) for cid,r in results.items()}))
    save(HERE/'FINAL_CANDIDATE_FROZEN.json',dict(research_only=True,production_registration_changed=False,final_candidate=incumbent,config=configs[incumbent],config_sha256=config_hash(configs[incumbent]),selection_sha256=frozenhash,protocol_sha256=phash,account_sha256=sha(HERE/'account.py'),runner_sha256=sha(HERE/'run_ten_rounds.py'),prepare_sha256=sha(HERE/'prepare.py'),input_manifest_sha256=protocol['data_manifest_sha256']))
    print(json.dumps(dict(done=True,rounds=len(rounds),new_attempts=len(attempts),final=incumbent,highest_training_return=highest,unique_2024_runs=len(stability)),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
