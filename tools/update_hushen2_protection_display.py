"""One-time, narrowly checked UI replacement for model-anchor terms."""
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'沪深实盘工作台/tracker/ui/index.html'
source=path.read_text(encoding='utf-8')
pairs=[
    ("function render(){const s=state;", "function protectionDifference(p,key){const delta=Number(p[key])-Number(p.average_price);const amount=(delta>=0?'+':'')+Math.abs(delta).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:6});const signed=delta<0?'-'+amount:amount;const rate=delta/Number(p.average_price)*100;return `${signed}元（${rate>=0?'+':''}${rate.toFixed(2)}%）`}\nfunction render(){const s=state;"),
    ('<th>止盈 / 止损</th>', '<th>相对成交均价差额 / 模型目标价</th>'),
    ('<span class="positive">${p.take.toFixed(2)}</span> / <span class="negative">${p.stop.toFixed(2)}</span>', '<span class="positive">止盈 ${protectionDifference(p,\'take\')}</span><br><small>目标价 ${p.take.toFixed(2)}</small><br><span class="negative">止损 ${protectionDifference(p,\'stop\')}</span><br><small>目标价 ${p.stop.toFixed(2)}</small>'),
    ('成交后仍需核对另一条卖单与剩余数量，避免旧单残留。', '国金止盈止损单成交后另一侧自动撤销；部分成交仍需核对剩余股数。目标价按模型原买入线与冻结ATR计算，以下差额相对实际成交均价。'),
    ("${card('卖出股数',p.quantity)}${card('止盈：股价 ≥',p.take.toFixed(2))}", "${card('卖出股数',p.quantity)}${card('实际成交均价（价差参照）',Number(p.average_price).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:6}))}${card('模型原买入线（目标价计算基准）',p.model_base_price.toFixed(2))}${card('止盈差额：相对实际成交均价',protectionDifference(p,'take'))}${card('止损差额：相对实际成交均价',protectionDifference(p,'stop'))}${p.protection_needs_review?'<p class=\"modalnote\">此前确认的价位与当前模型目标价不同，请在国金核对并修改后重新确认。</p>':''}${card('止盈：股价 ≥',p.take.toFixed(2))}"),
]
for old,new in pairs:
    if source.count(old)!=1:
        raise RuntimeError(f'Expected one UI occurrence: {old[:80]}')
    source=source.replace(old,new)
path.write_text(source,encoding='utf-8')
print('Updated protection display without account writes')
