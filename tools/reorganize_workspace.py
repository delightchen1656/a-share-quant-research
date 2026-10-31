"""One-shot, audited workspace relocation. Does not train or update market data."""
from pathlib import Path
import argparse, ast, hashlib, json, os, shutil, subprocess, urllib.request

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'project_memory/holdout_restricted/layout_20261031'
MOVES = [
    ('sh_sz_market_research/data_pipeline/data', 'K线数据/沪深'),
    ('evening_accumulation/data', 'K线数据/科创'),
    ('hushen_kline_viewer/gold_data', 'K线数据/黄金'),
    ('hushen_kline_viewer/sse_data', 'K线数据/指数/上证看盘'),
    ('data_updates', 'K线数据/更新备份与审计'),
    ('strategies/hushen', '沪深1研究'),
    ('strategies/hushen_2', '沪深2研究'),
    ('strategies/kechuang', '科创1研究'),
    ('沪深2_K线练习', '沪深2研究/K线练习'),
    ('沪深2_星轨软件', '沪深实盘工作台'),
    ('hushen_kline_viewer', 'K线看盘软件'),
    ('direction1_structure_research', '研究尝试/方向1_超跌反弹'),
    ('gold_trend_stock_trial', '研究尝试/gold_trend_stock_trial'),
    ('box_exit_research', 'archive/retired_research/box_exit_research'),
    ('box60_selection_research', 'archive/retired_research/box60_selection_research'),
    ('direction5_sector_transmission', 'archive/retired_research/direction5_sector_transmission'),
    ('leader_pattern_research', 'archive/retired_research/leader_pattern_research'),
    ('oversold_rebound_research', 'archive/retired_research/oversold_rebound_research'),
    ('weekly_stock_selection_research', 'archive/retired_research/weekly_stock_selection_research'),
    ('research_versions', 'archive/research_versions'),
    ('量化审查', 'project_memory/量化审查'),
    ('reports', 'archive/reports'),
    ('outputs', 'archive/outputs'),
    ('sh_sz_market_research', 'archive/legacy_layout/sh_sz_market_research'),
    ('evening_accumulation', 'archive/legacy_layout/evening_accumulation'),
    ('strategies', 'archive/legacy_layout/strategies'),
]
def save(name, data):
    AUDIT.mkdir(parents=True, exist_ok=True)
    (AUDIT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024), b''): h.update(b)
    return h.hexdigest()
def mapped(rel):
    for old,new in sorted(MOVES,key=lambda x:-len(x[0])):
        if rel==old or rel.startswith(old+'/'):return new+rel[len(old):]
    return rel
def entries():
    pending=[ROOT]
    while pending:
        base=pending.pop()
        with os.scandir(base) as stream:
            for entry in stream:
                p=Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in {'.git','quant_env','node_modules','__pycache__','.pytest_cache','desktop_browser'} and p!=AUDIT:pending.append(p)
                elif entry.is_file(follow_symlinks=False):yield p,entry.stat(follow_symlinks=False)
def prepare():
    assert not (AUDIT/'inventory.json').exists(), 'Preparation already saved'
    save('moves.json',[{'old':a,'new':b}for a,b in MOVES])
    status=subprocess.check_output(['git','status','--porcelain=v1','-uall'],cwd=ROOT)
    (AUDIT/'git_status_before.txt').write_bytes(status)
    rows=[]
    for p,s in entries():
        rel=p.relative_to(ROOT).as_posix()
        item=dict(old=rel,new=mapped(rel),size=s.st_size,mtime_ns=s.st_mtime_ns)
        # Source/configuration and account/model bytes are checked before and after.
        historical_backup = rel.startswith(('data_updates/', 'archive/')) or item['new'].startswith('archive/')
        sensitive = p.suffix.lower() in {'.py','.pyw','.sqlite3','.db','.joblib','.pkl'} or 'MANIFEST' in p.name.upper() or p.name.startswith('CURRENT') or p.name in {'RULE.json','utility.txt','pen025.txt','pen100.txt','audit.json','commit_manifest.json'} or '/tracker/data/' in rel or '/tracker/hushen1_data/' in rel
        if not historical_backup and sensitive:
            item['sha256']=sha(p)
        rows.append(item)
    save('inventory.json',rows)
    responses={}
    for route in ['api/health','api/stocks','api/history?code=600000','api/signals','api/gold/history','api/sse/history']:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8766/'+route,timeout=30) as r:responses[route]=json.load(r)
        except Exception as e:responses[route]={'capture_error':str(e)}
    save('viewer_before.json',responses)
    print('PREPARED',len(rows),'files',sum(x['size']for x in rows),'bytes',flush=True)

def replace_paths(text):
    # One pass prevents the shorter legacy-container rule remapping new paths.
    import re
    variants={}
    for old,new in MOVES:
        if '/' not in old:
            variants[old]=new
            continue
        for sep in ['/','\\','\\\\']:
            variants[old.replace('/',sep)]=new.replace('/',sep)
    choices='|'.join(re.escape(k)for k in sorted(variants,key=len,reverse=True))
    prefix=r'(?<![\w/\\])|(?<=quant/)|(?<=quant\\)|(?<=quant\\\\)'
    pattern='(?:'+prefix+')('+choices+r')(?=$|[^\w])'
    def substitute(m):
        old=m.group(1)
        if old in {'outputs','reports','strategies','research_versions'}:
            following=text[m.end():m.end()+1]
            if following not in {'/','\\'} and not re.search(r"/\s*['\"]$|Path\(['\"]$",text[max(0,m.start()-30):m.start()]):
                return old  # Preserve schema keys and semantic identifiers.
        return variants[old]
    return re.sub(pattern,substitute,text)

def root_fixes(text, oldfile, newfile):
    """Resolve ONLY simple pathlib expressions; never execute source code."""
    tree=ast.parse(text);env={'__file__':str(oldfile),'Path':Path};edits=[]
    root_expr="next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())"
    def value(n):
        if isinstance(n,ast.Constant):return n.value
        if isinstance(n,ast.Name):return env[n.id]
        if isinstance(n,ast.BinOp) and isinstance(n.op,ast.Div):return value(n.left)/value(n.right)
        if isinstance(n,ast.Attribute) and n.attr in {'parent','parents'}:return getattr(value(n.value),n.attr)
        if isinstance(n,ast.Subscript):return value(n.value)[value(n.slice)]
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='Path':return Path(*[value(a)for a in n.args])
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='resolve' and not n.args:return value(n.func.value).resolve()
        raise ValueError()
    lines=text.splitlines(keepends=True);starts=[];offset=0
    for line in lines:starts.append(offset);offset+=len(line)
    def span(n):
        # AST columns use UTF8 bytes, not Unicode characters.
        a=starts[n.lineno-1]+len(lines[n.lineno-1].encode()[:n.col_offset].decode())
        b=starts[n.end_lineno-1]+len(lines[n.end_lineno-1].encode()[:n.end_col_offset].decode())
        return a,b
    for stmt in tree.body:
        if not isinstance(stmt,ast.Assign):continue
        try:v=value(stmt.value)
        except (ValueError,KeyError,TypeError,IndexError,AttributeError):continue
        for t in stmt.targets:
            if isinstance(t,ast.Name):env[t.id]=v
        if isinstance(v,Path) and v==ROOT and oldfile.parent!=newfile.parent:
            edits.append((*span(stmt.value),root_expr))
    for a,b,s in sorted(edits,reverse=True):text=text[:a]+s+text[b:]
    return text

def rewrite():
    rows=json.loads((AUDIT/'inventory.json').read_text(encoding='utf8'));changed=[]
    for row in rows:
        oldrel,newrel=row['old'],row['new'];p=ROOT/newrel
        if p.suffix.lower() not in {'.py','.pyw','.cmd','.ps1','.md','.txt'}:continue
        if newrel.startswith(('archive/','国金ptrade/','K线数据/','project_memory/')):continue
        if any(x in p.parts for x in ['inputs_pre2025','frozen_inputs','provenance','history','reference','training_source','model','data','results']):continue
        if p.name.startswith('supermind_') or '/runtime/' in newrel or p.name=='reorganize_workspace.py':continue
        if p.suffix=='.txt' and p.name not in {'使用说明.txt','README.txt','清理状态.txt'}:continue
        if not p.exists() or (getattr(p.stat(),'st_file_attributes',0)&1):continue
        raw=p.read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:continue
        result=text
        if p.suffix in {'.py','.pyw'}:
            try:result=root_fixes(result,ROOT/oldrel,p)
            except SyntaxError:continue
        result=replace_paths(result)
        for old,new in MOVES:
            if '/' not in old:result=result.replace(new.replace('/','\\\\'),new)
        if newrel.startswith('K线看盘软件/') and p.suffix=='.py':
            import re
            for name,dest in [('gold_data','黄金'),('sse_data','指数/上证看盘')]:
                result=re.sub(r"(HERE|Path\(__file__\)\.resolve\(\)\.parent)\s*/\s*(['\"])"+name+r"\2",
                              lambda m:m[1]+".parent/'K线数据/"+dest+"'",result)
        if newrel=='沪深2研究/K线练习/启动练习.pyw':result=result.replace("HERE.parent/'quant_env/","HERE.parents[1]/'quant_env/")
        if result!=text:
            backup=AUDIT/'originals'/oldrel;backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():shutil.copy2(p,backup)
            p.write_bytes((b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf')else b'')+result.encode('utf8'))
            changed.append(dict(old=oldrel,new=newrel,before=sha(backup),after=sha(p)))
    # Also recover records from a previous interrupted pass.
    changed=[]
    for backup in (AUDIT/'originals').rglob('*'):
        if not backup.is_file():continue
        old=backup.relative_to(AUDIT/'originals').as_posix();new=mapped(old);p=ROOT/new
        if p.is_file() and sha(backup)!=sha(p):changed.append(dict(old=old,new=new,before=sha(backup),after=sha(p)))
    save('path_edits.json',changed)
    print('PATH EDITS',len(changed),flush=True)

def verify():
    rows=json.loads((AUDIT/'inventory.json').read_text(encoding='utf8'))
    changed={r['new']for r in json.loads((AUDIT/'path_edits.json').read_text(encoding='utf8'))}
    current={p.relative_to(ROOT).as_posix():s for p,s in entries()}
    missing=[];differences=[];checked=0
    for r in rows:
        p=ROOT/r['new']
        if r['new'] not in current:missing.append(r['new']);continue
        if r['new']in changed:continue
        if current[r['new']].st_size!=r['size'] or ('sha256'in r and sha(p)!=r['sha256']):differences.append(r['new'])
        checked+=1
    save('asset_verification.json',dict(checked=checked,missing=missing,differences=differences))
    print('ASSETS',checked,'MISSING',len(missing),'DIFFERENCES',len(differences),flush=True)
    if missing or differences:print(missing[:10],differences[:20])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','rewrite','verify']);a=p.parse_args()
    globals()[a.phase]()
