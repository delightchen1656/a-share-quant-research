"""Compact presentation only; leave execution and account code untouched."""
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'沪深实盘工作台/tracker/ui/index.html'
text=path.read_text(encoding='utf-8')
pairs=[
    ('function card(label,value){','function card(label,value,copyValue=value){'),
    ('data-copy="${esc(value)}"','data-copy="${esc(copyValue)}"'),
    ("function render(){const s=state;", "function protectionTargetText(p,key){return Number(p[key]).toFixed(2)+' ('+protectionDifference(p,key).replace('元（','元)(').replace('）',')')}\nfunction render(){const s=state;"),
    ("${card('止盈差额：相对实际成交均价',protectionDifference(p,'take'))}${card('止损差额：相对实际成交均价',protectionDifference(p,'stop'))}",''),
    ("${card('止盈：股价 ≥',p.take.toFixed(2))}${card('止损：股价 ≤',p.stop.toFixed(2))}","${card('止盈 ≥',protectionTargetText(p,'take'),p.take.toFixed(2))}${card('止损 ≤',protectionTargetText(p,'stop'),p.stop.toFixed(2))}"),
    ("${card('委托类型','五档即时成交剩余撤销')}<label class=\"check\"><input type=\"checkbox\" required>已在国金设置相应",'<label class="check"><input type="checkbox" required>已在国金设置相应'),
    ("<span class=\"positive\">止盈 ${protectionDifference(p,'take')}</span><br><small>目标价 ${p.take.toFixed(2)}</small><br><span class=\"negative\">止损 ${protectionDifference(p,'stop')}</span><br><small>目标价 ${p.stop.toFixed(2)}</small>","<span class=\"positive\">止盈 ≥ ${protectionTargetText(p,'take')}</span><br><span class=\"negative\">止损 ≤ ${protectionTargetText(p,'stop')}</span>"),
]
for old,new in pairs:
    if text.count(old)!=1:raise RuntimeError(f'Expected one UI occurrence: {old[:80]}')
    text=text.replace(old,new)
path.write_text(text,encoding='utf-8')
