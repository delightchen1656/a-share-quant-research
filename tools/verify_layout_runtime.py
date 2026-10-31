"""Post-relocation probes. Backtest output is isolated from existing results."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, sys, urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'project_memory/holdout_restricted/layout_20261031/validation'

def load(name,path):
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m

class ResultsRedirect:
    def __init__(self,base,out):self.base=base;self.out=out
    def __truediv__(self,value):
        value=str(value).replace('\\','/')
        if value=='results/latest/rankings_original.json':return self.base/value
        if value=='results' or value.startswith('results/'):
            return self.out/value
        return self.base/value

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['viewer','star','hushen','market']);a=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if a.mode=='viewer':
        before=json.loads((OUT.parent/'viewer_before.json').read_text(encoding='utf8'));checks={}
        for route,expected in before.items():
            with urllib.request.urlopen('http://127.0.0.1:8766/'+route,timeout=45)as r:actual=json.load(r)
            checks[route]=actual==expected
        (OUT/'viewer.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
        assert all(checks.values()),checks
        print('Viewer API byte-equivalent JSON:',len(checks),'routes')
    elif a.mode=='star':
        m=load('star_layout_validation',ROOT/'科创1研究/backtest/run.py')
        m.STAR=ResultsRedirect(ROOT/'科创1研究',OUT/'star')
        m.OUT=OUT/'star/results/latest';m.main()
    elif a.mode=='hushen':
        m=load('hushen_layout_validation',ROOT/'沪深1研究/backtest/run_range.py')
        m.HOME=ResultsRedirect(ROOT/'沪深1研究',OUT/'hushen')
        sys.argv=['run_range.py','--start','2026-10-26','--end','2026-10-30','--cash','100000']
        m.main()
    else:
        from workspace_paths import HUSHEN,KECHUANG,GOLD,UPDATES
        m=load('market_layout_validation',ROOT/'沪深实盘工作台/tracker/market.py')
        info=m.health(ROOT/'沪深实盘工作台/tracker/data')
        assert m.DATA==HUSHEN and KECHUANG.is_dir()and GOLD.is_dir()and UPDATES.is_dir()
        print(json.dumps(info,ensure_ascii=False,default=str)[:1800])

if __name__=='__main__':main()
