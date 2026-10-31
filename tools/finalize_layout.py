"""Finish relocation metadata without changing whitelist bytes or strategy rules."""
from pathlib import Path
import hashlib,json,shutil,ast,re
from reorganize_workspace import ROOT,AUDIT,replace_paths,sha

def main():
    edits=json.loads((AUDIT/'path_edits.json').read_text(encoding='utf8'))
    inventory=json.loads((AUDIT/'inventory.json').read_text(encoding='utf8'))
    originals={r['new']:r for r in inventory}
    def edit(p,text):
        raw=p.read_bytes()
        if text==raw.decode('utf-8-sig'):return
        rel=p.relative_to(ROOT).as_posix();old=originals.get(rel,{}).get('old',rel)
        dest=AUDIT/'originals'/old
        if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        p.write_text(text,encoding='utf8')
        edits.append(dict(old=old,new=rel,before=sha(dest),after=sha(p)))
    for p in (ROOT/'K线看盘软件').glob('*.py'):
        text=p.read_text(encoding='utf-8-sig')
        for base in ['HERE','ROOT']:
            for quote in ["'",'"']:
                for old,new in [('gold_data/','黄金/'),('sse_data/','指数/上证看盘/')]:
                    text=text.replace(base+'/'+quote+old,base+'.parent/'+quote+'K线数据/'+new)
        edit(p,text)
    # Resolve absolute filenames in original records at the read boundary.
    # Do not rewrite immutable whitelist or provenance JSON bytes.
    consumers=list((ROOT/'研究尝试/gold_trend_stock_trial').rglob('*.py'))+[ROOT/'K线看盘软件/prepare_data.py']
    for p in consumers:
        if 'inputs_pre2025' in p.parts:continue
        text=p.read_text(encoding='utf-8-sig');new=text
        for expr in ["f['path']","item['path']","old['manifest']","old['universe']","w['files'][0]['path']"]:
            for typ in ['pathlib.Path','Path']:
                new=new.replace(typ+'('+expr+')','resolve_recorded_path('+expr+')')
        if new!=text:
            tree=ast.parse(new);at=0
            for node in tree.body:
                if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str) or isinstance(node,ast.ImportFrom) and node.module=='__future__':at=node.end_lineno
                else:break
            lines=new.splitlines(keepends=True)
            lines.insert(at,"\nimport sys as _layout_sys\nfrom pathlib import Path as _LayoutPath\n_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())\n_layout_sys.path.insert(0,str(_layout_root/'tools'))\nfrom workspace_paths import resolve_recorded_path\n")
            edit(p,''.join(lines))
    # Runtime paths in current configs are updated; source whitelists remain immutable.
    direction=ROOT/'研究尝试/方向1_超跌反弹'
    for p in direction.rglob('*.json'):
        if any(part in p.parts for part in ['inputs_pre2025','provenance','holdout_restricted']):continue
        if p.name not in {'CONFIG.json','CURRENT_DISPLAY_CATALOG.json','CURRENT_DIRECTION.json','CURRENT_SIGNAL_SCOPE.json'}:continue
        old=sha(p);text=replace_paths(p.read_text(encoding='utf-8-sig'));edit(p,text)
        freeze=p.parent/'RUN_FREEZE.json'
        if p.name=='CONFIG.json' and old!=sha(p) and freeze.exists():
            f=json.loads(freeze.read_text(encoding='utf8'))
            assert f['config_sha256']==old,'Original freeze/config mismatch'
            f['config_sha256']=sha(p)
            f['layout_migration']={'original_config_sha256':old,'parameters_changed':False,'inputs_changed':False,'new_research_freeze':False}
            edit(freeze,json.dumps(f,ensure_ascii=False,indent=2))
    manifest=direction/'PACKAGE_MANIFEST.json'
    prior=json.loads(manifest.read_text(encoding='utf8'));changed={x['new']for x in edits}
    changes=[]
    for row in prior['files']:
        p=direction/row['path'];rel=p.relative_to(ROOT).as_posix()
        if rel in changed:
            old=row['sha256'];row['sha256']=sha(p)
            changes.append(dict(path=row['path'],before=old,after=row['sha256']))
    prior['layout_migration']={'path_only_changes':changes,'original_manifest_sha256':sha(manifest),'strategy_parameters_changed':False,'input_whitelists_changed':False}
    edit(manifest,json.dumps(prior,ensure_ascii=False,indent=2))
    (AUDIT/'path_edits.json').write_text(json.dumps(edits,ensure_ascii=False,indent=2),encoding='utf8')
    syntax=[]
    for folder in ['沪深1研究','沪深2研究','科创1研究','K线看盘软件','沪深实盘工作台','研究尝试','tools']:
        for p in (ROOT/folder).rglob('*.py'):
            if any(x in p.parts for x in ['inputs_pre2025','frozen_inputs','data','provenance','results','__pycache__']):continue
            try:ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
            except (SyntaxError,UnicodeError) as e:syntax.append(dict(path=str(p),error=str(e)))
    (AUDIT/'syntax.json').write_text(json.dumps(syntax,ensure_ascii=False,indent=2),encoding='utf8')
    print('SYNTAX FAILURES',len(syntax));print(syntax[:5])

if __name__=='__main__':main()
