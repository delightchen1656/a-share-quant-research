from pathlib import Path
import hashlib, json, zipfile, subprocess, sys, platform, collections, requests

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def archive(name, files):
    rows=[]
    with zipfile.ZipFile(OUT/name,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(files):
            rel=p.relative_to(ROOT).as_posix()
            b=p.read_bytes(); rows.append(dict(path=rel,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()))
            z.writestr(rel,b)
    with zipfile.ZipFile(OUT/name) as z:
        assert z.testzip() is None
        for row in rows: assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
    (OUT/(name+'.manifest.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,len(rows),(OUT/name).stat().st_size,flush=True)
    return dict(archive=name,files=len(rows),source_bytes=sum(x['bytes'] for x in rows),sha256=sha(OUT/name))

summary=[]
for name, folder in [('01_hushen_data.zip','sh_sz_market_research/data_pipeline/data'),('02_kechuang_data.zip','evening_accumulation/data')]:
    files=[p for p in (ROOT/folder).rglob('*') if p.is_file()]
    assert all(p.suffix in {'.json','.csv','.parquet'} for p in files)
    summary.append(archive(name,files))
base=ROOT/'data_updates/20261004'
files=[p for p in base.rglob('*') if p.is_file() and 'staged' not in p.relative_to(base).parts]
files += [ROOT/'tools'/n for n in ['行情库更新说明_20261004.md','行情库恢复说明_20261004.md','market_recovery_20261004.json','star_recovery_20261004.json','market_recovery_validation_20261004.json']]
summary.append(archive('03_data_provenance_and_backups.zip',files))
(OUT/'data_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
env=OUT/'environment';env.mkdir(exist_ok=True)
pkgs=json.loads(subprocess.check_output([sys.executable,'-m','pip','list','--format=json'],text=True))
(env/'requirements.lock.txt').write_text(''.join(f"{p['name']}=={p['version']}\n" for p in pkgs),encoding='utf-8')
(env/'original_requirements.txt').write_bytes((ROOT/'requirements.txt').read_bytes())
(env/'source_environment.json').write_text(json.dumps(dict(python=sys.version,platform=platform.platform(),architecture=platform.architecture(),packages=pkgs),ensure_ascii=False,indent=2),encoding='utf-8')
install=OUT/'installers';install.mkdir(exist_ok=True)
downloads=[('SuperMind_TYB_v8.18.1.9791.exe','https://download.10jqka.com.cn/index/download/id/709'),('python-3.10.11-amd64.exe','https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe')]
log=[]
for name,url in downloads:
    try:
        r=requests.get(url,stream=True,timeout=60);r.raise_for_status()
        p=install/name
        with p.open('wb') as f:
            for chunk in r.iter_content(1024*1024):f.write(chunk)
        with p.open('rb') as f: assert f.read(2)==b'MZ'
        log.append(dict(file=name,url=r.url,bytes=p.stat().st_size,sha256=sha(p),status='downloaded'))
        print('downloaded',name,p.stat().st_size,flush=True)
    except Exception as e:
        log.append(dict(file=name,url=url,status='failed',error=str(e)))
(install/'download_sources.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8')
