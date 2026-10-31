"""Join complete early-year responses with the prespecified basic-signal plan."""
from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
AREA=HERE/'inputs_pre2025'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest_path=AREA/'RESEARCH_2020_2024_MANIFEST.json'
    m=read(manifest_path);assert m['complete']
    early=read(AREA/'action_responses_2020/MANIFEST.json');assert early['complete'] and early['stocks']==947
    records=read(AREA/m['company_actions_file'])
    response={x['key']:x for x in m['responses']}
    for x in early['files']:
        p=AREA/x['path'];assert sha(p)==x['sha256'];obj=read(p)
        if x['key'] in records:assert records[x['key']]==obj['records']
        records[x['key']]=obj['records'];response[x['key']]=x
    dump(AREA/m['company_actions_file'],records)
    plan=AREA/'RESEARCH_QUERY_PLAN.json'
    dump(plan,dict(keys=sorted(response),scope='All pool stocks for 2020 plus all issuer-years containing any basic signal and following year for November/December signals; no outcomes used.'))
    m['responses']=list(response.values());m['coverage_issuer_years']=len(response)
    m['provider_records']=sum(len(x) for x in records.values());m['query_plan_file']=plan.name
    paths={x['path'] for x in m['files']}
    paths.update(['MANIFEST.json',plan.name,'action_responses_2020/MANIFEST.json'])
    paths.update(x['path'] for x in m['responses'])
    m['files']=[dict(path=x,sha256=sha(AREA/x)) for x in sorted(paths)]
    for x in m['responses']:assert sha(AREA/x['path'])==x['sha256']
    dump(manifest_path,m)
    print('Frozen',m['coverage_issuer_years'],'issuer-years;',m['provider_records'],'corporate-action records;',len(m['files']),'whitelisted files')
    print('Manifest SHA256',sha(manifest_path))
if __name__=='__main__':main()
