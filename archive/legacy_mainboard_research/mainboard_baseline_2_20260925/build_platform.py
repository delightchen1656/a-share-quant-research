"""Generate the frozen baseline2 platform strategy from the calibrated baseline1."""
from pathlib import Path
import json, ast

HERE=Path(__file__).resolve().parent
def main():
    config=json.loads((HERE/'frozen.json').read_text(encoding='utf-8'))
    name=config.get('variant',config.get('name'))
    src=HERE.parents[1]/'platform'/'supermind'/'supermind_mainboard_baseline_1.py'
    text=src.read_text(encoding='utf-8')
    text=text.replace('import numpy as np','import numpy as np\nimport pandas as pd',1)
    if 'family' in config:
        a,b,c=config['bull'];d,e,f=config['bear']
        text=text.replace('score = 0.25 * low_amount + 0.20 * near_high + 0.55 * dividend',f'score = {a} * low_amount + {b} * near_high + {c} * dividend')
        text=text.replace('score = 0.50 * below_high + 0.25 * below_ma + 0.25 * dividend',f'score = {d} * below_high + {e} * below_ma + {f} * dividend')
        text=text.replace('TARGET_COUNT = 20',f"TARGET_COUNT = {config['count']}")
        text=text.replace('BUFFER_COUNT = 40',f"BUFFER_COUNT = {config['buffer']}")
        text=text.replace('TARGET_EXPOSURE = 1.00',f"TARGET_EXPOSURE = {config['exposure']}")
        text=text.replace('BASELINE1','BASELINE2').replace('沪深基准1','沪深基准2 '+name)
        ast.parse(text)
        (HERE/'supermind_mainboard_baseline_2.py').write_text(text,encoding='utf-8')
        print(name,'platform generated')
        return
    conditions={'lowrisk_half':'risk <= .5','liquid_half':'liquid >= .5',
       'dividend_half':'qual >= .5','trend_half':'trend >= .5',
       'quality_lowrisk':'(qual >= .5) & (risk <= .5)',
       'quality_trend':'(qual >= .5) & (trend >= .5)',
       'reversal_lowrisk':'(trend <= .5) & (risk <= .5)',
       'liquid_quality':'(liquid >= .5) & (qual >= .5)',
       'dividend_only':'qual >= .7','lowrisk_only':'risk <= .3','trend_only':'trend >= .7'}
    insert='''    # Frozen baseline2 universe screen; rankings computed before filtering.
    risk = pd.Series([x[1]["downside"] for x in rows]).rank(pct=True).to_numpy()
    liquid = pd.Series([x[1]["amount20"] for x in rows]).rank(pct=True).to_numpy()
    qual = pd.Series([x[1]["dividend"] for x in rows]).rank(pct=True).to_numpy()
    trend = pd.Series([x[1]["near_high"] for x in rows]).rank(pct=True).to_numpy()
    allowed = CONDITION
    if np.sum(allowed) < TARGET_COUNT:
        return None
    SCORE_OVERRIDE
    score = np.where(allowed, score, -np.inf)
'''.replace('CONDITION',conditions[name]).replace('SCORE_OVERRIDE',{'dividend_only':'score = qual','lowrisk_only':'score = 1-risk','trend_only':'score = trend'}.get(name,'# Preserve regime score'))
    marker='    order = np.argsort(-score, kind="mergesort")'
    assert text.count(marker)==1
    text=text.replace(marker,insert+marker+'\n    order = [i for i in order if allowed[i]]')
    text=text.replace('BASELINE1','BASELINE2').replace('沪深基准1','沪深基准2 '+name)
    ast.parse(text)
    (HERE/'supermind_mainboard_baseline_2.py').write_text(text,encoding='utf-8')
    print(name,'platform generated')
if __name__=='__main__':main()
