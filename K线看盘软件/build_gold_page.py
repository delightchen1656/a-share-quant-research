"""Build a standalone quote-only page from the existing canvas controls."""
from pathlib import Path
HERE=Path(__file__).resolve().parent;web=HERE/'web'
nav='<nav class="market-tabs" aria-label="市场分页"><a href="/">沪深主板</a><a href="/gold">伦敦金 · USD</a><a href="/sse">上证 · 牛熊</a></nav>'
stock=(web/'index.html').read_text(encoding='utf8')
if 'class="market-tabs"'not in stock:stock=stock.replace('<span class="mode">',nav+'<span class="mode">',1)
(web/'index.html').write_text(stock,encoding='utf8')
gold=stock.replace('<title>沪深主板 · K线与结构信号</title>','<title>伦敦金 · XAU/USD · 伦敦日线</title>').replace('src="/app.js"','src="/gold.js"').replace('<body>','<body class="gold-market">')
gold=gold.replace('<b>K</b>','<b>Au</b>').replace('<strong>沪深主板</strong>','<strong>伦敦金</strong>').replace('<span>K线与结构信号</span>','<span>XAU/USD</span>').replace('日K · 本地行情','日K · USD/盎司')
gold=gold.replace('搜索代码 / 股票名称','搜索品种').replace('<span class="basis">前复权</span>','<span class="basis">BID · USD/盎司</span>').replace('↑ ↓ 切换 · 仅沪深主板','红涨绿跌 · 伦敦时间')
gold=gold.replace('aria-label="搜索股票代码或名称"','aria-label="搜索黄金品种"').replace('aria-label="沪深主板股票与信号列表"','aria-label="黄金现货品种"').replace('aria-label="日K线与成交量图，仅显示有成交的交易日"','aria-label="伦敦金日K线，美元每盎司，红涨绿跌，无集中成交量"')
gold=gold.replace('★ 仅为名单快照标记','现货报价无集中成交量').replace('title="星标来自保留的合并龙头名单快照，并非历史当时归属"','')
about='<div class="gold-about"><strong>伦敦现货日线</strong><p>美元 / 金衡盎司<br>红涨 · 绿跌</p><p>伦敦00:00切日<br>GMT / BST自动切换</p><p>保留真实报价日期，含周日短时段；休市不补K线。</p><p>HistData BID报价，不是LBMA定盘价或期货。</p><p id="gold-freshness">正在核对数据时间…</p></div>'
gold=gold.replace('<footer>',about+'<footer>',1)
(web/'gold.html').write_text(gold,encoding='utf8')
gold=gold.replace('BID · USD/盎司','现货 · USD/盎司').replace('HistData BID报价，不是LBMA定盘价或期货。','历史：HistData BID；近期：Gold Price API现货参考价。每根K线标注来源，不是期货。近期源不提供周日短时段时不补造。')
(web/'gold.html').write_text(gold,encoding='utf8')
script=(web/'app.js').read_text(encoding='utf8')
start=script.rfind('(async()=>')
assert start>0
script=script[:start]+'''(async()=>{try{const d=await json('/api/gold/history');metadata=d.metadata;s.stocks=[{code:'XAUUSD',name:'伦敦金现货',is_leader:false}];s.signals=[];s.direction='raw';s.scope='all';$('direction').value='raw';$('snapshot').textContent=`报价截至 ${d.last} · 非实时`;const days=Math.max(0,Math.floor((Date.now()-Date.parse(metadata.last_quote_utc))/86400000));$('gold-freshness').textContent=`最近报价 ${metadata.last_quote_utc.replace('T',' ').replace('+00:00',' UTC')}。距今约${days}天，以源站已发布数据为准。`;await load('XAUUSD')}catch(e){status(e.message);$('snapshot').textContent='黄金数据未就绪'}})();\n'''
script=script.replace("'/api/history?code='","'/api/gold/history?code='")
script="function goldRangeCount(months){if(!s.bars.length)return 0;let d=new Date(s.bars[s.bars.length-1][0]+'T00:00:00Z');d.setUTCMonth(d.getUTCMonth()-months);let key=d.toISOString().slice(0,10),i=s.bars.findIndex(b=>b[0]>=key);return s.bars.length-Math.max(0,i)}\n"+script
script=script.replace('s.count=Math.min(250,s.bars.length)','s.count=goldRangeCount(12)').replace('s.count=Math.min(s.count,250)','s.count=Math.min(s.count,goldRangeCount(12))')
script=script.replace("b.dataset.range==='all'?s.bars.length:Math.min(Number(b.dataset.range),s.bars.length)","b.dataset.range==='all'?s.bars.length:goldRangeCount(b.dataset.range==='63'?3:12)")
script=script.replace("s.filtered.length+'只'","s.filtered.length+'个'")
script=script.replace("s.stocks.length+'只历史主板'","'1个现货品种'").replace("signalMode?'结构信号':'股票列表'","'市场品种'").replace("signalMode?'信号日 / 60日触及':'名称 / 代码'","'现货 / 币种'")
script=script.replace("`日线全历史 ${d.first} — ${d.last} · 仅展示有成交的交易日`","`${d.first} — ${d.last} · 伦敦00:00切日（GMT/BST） · BID报价`")
script=script.replace("`共${d.bars.length.toLocaleString()}根日K · 成交量：手 · 本地快照`","`共${d.bars.length.toLocaleString()}根日K · HistData · 真实报价日 · 不含未结束的伦敦当日`")
script=script.replace(",['成交量',hands(b[5]),''],['成交额',amount(b[6]),'']",'')
script=script.replace("['涨跌',percent(b[7]),tone]","['涨跌',percent(b[7]),tone],['来源',b[12]||'HistData BID','']")
script=script.replace('· BID报价','· 现货报价（来源见价格栏）').replace('根日K · HistData ·','根日K · 多源现货 ·')
script=script.replace("const days=Math.max(0,Math.floor((Date.now()-Date.parse(metadata.last_quote_utc))/86400000));$('gold-freshness').textContent=`最近报价 ${metadata.last_quote_utc.replace('T',' ').replace('+00:00',' UTC')}。距今约${days}天，以源站已发布数据为准。`;", "$('gold-freshness').textContent=metadata.latest_complete_date?`完整伦敦日线截至 ${metadata.latest_complete_date}；当前未结束日不计入。近期使用 Gold Price API，UTC日线仅在与伦敦午夜完全一致时接入。`:`最近报价 ${metadata.last_quote_utc}，以源站已发布数据为准。`;")
script=script.replace('bottom=Math.floor(h*.70)','bottom=Math.floor(h*.88)')
old="for(let j=0;j<=2;j++){let yy=vbottom-(vbottom-vtop)*j/2;line(left,yy,right,yy,C.grid);ctx.fillStyle=C.text;ctx.fillText(j===2?hands(maxvol):'',right+9,yy)}"
assert old in script;script=script.replace(old,'')
script=script.replace("ctx.fillStyle=C.text;ctx.fillText('成交量',left+3,vtop-13);",'')
old="ctx.fillStyle=color;let vh=(b[5]||0)/maxvol*(vbottom-vtop);ctx.fillRect(xx-bw/2,vbottom-vh,bw,Math.max(1,vh))"
assert old in script;script=script.replace(old,'')
(web/'gold.js').write_text(script,encoding='utf8')
css=(web/'styles.css').read_text(encoding='utf8')
marker='/* Independent gold quote page */'
if marker in css:css=css[:css.index(marker)]
css+='''\n/* Independent gold quote page */
.market-tabs{display:flex;gap:5px}.market-tabs a{padding:7px 12px;text-decoration:none;border-radius:6px;color:#526981;background:#f2f5fa;white-space:nowrap}.market-tabs a:hover{background:#e7eefb}.gold-market .brand>b{background:#ad8942;font-size:17px}.gold-market .direction-picker,.gold-market .scope,.gold-market .navigation,.gold-market #signal-controls{display:none!important}.gold-about{margin:20px 16px;color:#8190a4;font-size:12px;line-height:1.8}.gold-about strong{color:#9a7939}.gold-market .bottom-note{flex-wrap:wrap}.gold-market #gold-freshness{font-size:11px;color:#a28245}.gold-market .stock-row small{font-size:10px}@media(max-width:1000px){.mode{display:none}.market-tabs a{padding:6px;font-size:11px}}@media(max-width:680px){.brand span{display:none}.market-tabs{gap:2px}.market-tabs a{padding:4px;font-size:10px}.gold-about{margin:12px 8px;font-size:10px}.gold-market #snapshot{max-width:140px}.gold-market .date-jump{display:flex}}
'''
(web/'styles.css').write_text(css,encoding='utf8')
print('Built independent gold page and stock/gold navigation')
