function goldRangeCount(months){if(!s.bars.length)return 0;let d=new Date(s.bars[s.bars.length-1][0]+'T00:00:00Z');d.setUTCMonth(d.getUTCMonth()-months);let key=d.toISOString().slice(0,10),i=s.bars.findIndex(b=>b[0]>=key);return s.bars.length-Math.max(0,i)}
'use strict';
const $=id=>document.getElementById(id),canvas=$('chart'),ctx=canvas.getContext('2d');
const C={up:'#d8515e',down:'#15917c',grid:'#edf1f7',text:'#95a2b8',5:'#bf963e',10:'#9270cb',20:'#368dad',60:'#d06791'};
const s={stocks:[],signals:[],direction:'raw',selected:null,filtered:[],scope:'all',code:null,bars:[],start:0,count:250,hover:-1,drag:null,limit:120,request:0,mas:new Set([5,10,20,60])};
let geom=null,raf=0,metadata=null;
function number(v,n=2){return v==null?'—':Number(v).toFixed(n)}
function percent(v){return v==null?'—':`${v>0?'+':''}${(v*100).toFixed(2)}%`}
function hands(v){return v==null?'—':v>=10000?number(v/10000)+'万手':number(v,0)+'手'}
function amount(v){return v==null?'—':v>=1e8?number(v/1e8)+'亿':number(v/1e4)+'万'}
function requestDraw(){if(!raf)raf=requestAnimationFrame(()=>{raf=0;draw()})}
async function json(url){let r=await fetch(url,{cache:'no-store'}),d=await r.json();if(!r.ok)throw Error(d.error||'读取失败');return d}
function status(text){$('status').textContent=text;$('status').classList.remove('hidden')}
function list(keep=false){
 if(!keep)s.limit=120;
 const q=$('search').value.trim().toLowerCase(),signalMode=s.direction!=='raw';
 s.filtered=(signalMode?s.signals.filter(x=>x.direction===s.direction):s.stocks).filter(x=>(s.scope==='all'||x.is_leader)&&(!q||x.code.includes(q)||x.name.toLowerCase().includes(q)));
 if(signalMode){
  const from=$('from-date').value,to=$('to-date').value;if(from)s.filtered=s.filtered.filter(x=>x.signal_date>=from);if(to)s.filtered=s.filtered.filter(x=>x.signal_date<=to);
  const counts=new Map();for(let x of s.filtered)counts.set(x.code,(counts.get(x.code)||0)+1);
  const mode=$('sort').value;
  s.filtered.sort((a,b)=>{let diff=0;if(mode.startsWith('time'))diff=a.signal_date.localeCompare(b.signal_date)*(mode.endsWith('desc')?-1:1);else if(mode==='count_desc')diff=counts.get(b.code)-counts.get(a.code);else{let field=mode.startsWith('up')?'max_up':'max_down';if(a[field]==null&&b[field]!=null)return 1;if(a[field]!=null&&b[field]==null)return -1;if(a[field]!=null&&b[field]!=null)diff=(a[field]-b[field])*(mode.endsWith('desc')?-1:1)}return diff||b.signal_date.localeCompare(a.signal_date)||a.code.localeCompare(b.code)});
 }
 $('stock-count').textContent='1个现货品种';$('list-title').textContent='市场品种';$('list-label').textContent='现货 / 币种';$('signal-controls').hidden=!signalMode;
 $('filtered-count').textContent=signalMode?`${s.filtered.length}次 · ${new Set(s.filtered.map(x=>x.code)).size}只`:s.filtered.length+'个';$('stock-list').replaceChildren();
 if(!s.filtered.length){let e=document.createElement('div');e.className='empty';e.textContent=signalMode?'没有匹配的结构信号':'没有匹配的主板股票';$('stock-list').append(e)}
 for(const stock of s.filtered.slice(0,s.limit)){
  const selected=signalMode?stock.id===s.selected?.id:stock.code===s.code;
  let b=document.createElement('button');b.type='button';b.className='stock-row'+(signalMode?' signal-row':'')+(selected?' selected':'');b.setAttribute('role','option');b.setAttribute('aria-selected',String(selected));b.dataset.code=stock.code;if(signalMode)b.dataset.signal=stock.id;
  let label=document.createElement('span');label.className='stock-label';if(stock.is_leader){let star=document.createElement('span');star.className='star';star.textContent='★';label.append(star)}label.append(document.createTextNode(stock.name));let code=document.createElement('small');code.textContent=stock.code;b.append(label,code);
  if(signalMode){let date=document.createElement('small');date.className='signal-date';date.textContent=stock.signal_date;let stats=document.createElement('span');stats.className='signal-stats';let up=document.createElement('span');up.className='up';up.textContent='最大涨幅 '+percent(stock.max_up);let down=document.createElement('span');down.className='down';down.textContent='最大跌幅 '+percent(stock.max_down);stats.append(up,down);b.append(date,stats)}
  b.addEventListener('click',()=>load(stock.code,signalMode?stock:null));$('stock-list').append(b)
 }
 if(s.filtered.length>s.limit){let b=document.createElement('button');b.className='more';b.textContent=`继续显示（剩余${s.filtered.length-s.limit}只）`;b.onclick=()=>{const scroll=$('stock-list').scrollTop;s.limit+=120;list(true);$('stock-list').scrollTop=scroll};$('stock-list').append(b)}
 nav();
}
function selectedIndex(){return s.filtered.findIndex(x=>s.direction==='raw'?x.code===s.code:x.id===s.selected?.id)}
function nav(){let i=selectedIndex();$('previous').disabled=i<=0;$('next').disabled=i<0||i>=s.filtered.length-1;$('previous').textContent=s.direction==='raw'?'↑ 上一只':'↑ 上一信号';$('next').textContent=s.direction==='raw'?'下一只 ↓':'下一信号 ↓'}
function switchStock(delta){let i=selectedIndex();if(i+delta>=0&&i+delta<s.filtered.length){s.limit=Math.max(s.limit,i+delta+1);const item=s.filtered[i+delta];load(item.code,s.direction==='raw'?null:item).then(()=>document.querySelector('.stock-row.selected')?.scrollIntoView({block:'nearest'}))}}
async function load(code,event=null){
 let token=++s.request;s.code=code;s.selected=event;s.hover=-1;s.drag=null;s.bars=[];list(true);detail();requestDraw();status('正在读取日线…');
 try{
  const d=await json('/api/gold/history?code='+encodeURIComponent(code));if(token!==s.request)return;
  s.bars=d.bars;s.count=goldRangeCount(12);s.start=Math.max(0,s.bars.length-s.count);
  $('name').textContent=(d.is_leader?'★ ':'')+d.name;$('code').textContent=code;$('subtitle').textContent=`${d.first} — ${d.last} · 伦敦00:00切日（GMT/BST） · 现货报价（来源见价格栏）`;
  $('coverage').textContent=`共${d.bars.length.toLocaleString()}根日K · 多源现货 · 真实报价日 · 不含未结束的伦敦当日`;
  $('jump-date').min=d.first;$('jump-date').max=d.last;$('jump-date').value='';
  const params=new URLSearchParams(location.search);let day=event?.signal_date||(!event&&params.get('code')===code?params.get('date'):null);if(day)jump(day);
  if(event){let i=s.bars.findIndex(b=>b[0]===event.signal_date);if(i>=0){s.count=Math.min(61,s.bars.length);s.start=i-30;clamp();s.hover=i}}
  const url=new URL(location.href);url.search='';url.searchParams.set('code',code);url.searchParams.set('direction',s.direction);url.searchParams.set('scope',s.scope);if(event)url.searchParams.set('signal',event.id);if(day)url.searchParams.set('date',day);history.replaceState(null,'',url.pathname+url.search);
  $('status').classList.add('hidden');setRangeActive(event?'':'250');quote();sync();requestDraw();
 }catch(e){if(token===s.request){status(e.message);$('name').textContent=s.stocks.find(x=>x.code===code)?.name||code;$('code').textContent=code}}
}
function detail(){const e=s.selected,box=$('signal-detail');box.hidden=!e;box.replaceChildren();if(!e)return;const parts=['方向1 · 超跌反弹 v3','信号 '+e.signal_date,'次日开盘 '+(e.entry_date||'边界待确认'),'60日最大涨幅 '+percent(e.max_up),'60日最大跌幅 '+percent(e.max_down),e.window_complete?'完整60日窗口':(!e.next_valid_open?'次日开盘不可确认或无成交':'60日窗口未完整或存在未知报价')];for(let text of parts){let span=document.createElement('span');span.textContent=text;box.append(span)}box.title='触及涨跌以信号次一正式交易日开盘为基准，D0—D+59前复权价格观察；未扣费、不保证成交。信号覆盖现有全期，近期不足60日的观察不参与涨跌排序。'}
function setRangeActive(value){document.querySelectorAll('[data-range]').forEach(b=>b.classList.toggle('active',b.dataset.range===String(value)))}
function clamp(){s.count=Math.max(Math.min(15,s.bars.length),Math.min(s.count,s.bars.length));s.start=Math.max(0,Math.min(s.start,s.bars.length-s.count))}
function sync(){if(!s.bars.length)return;clamp();$('pan').max=Math.max(0,s.bars.length-s.count);$('pan').value=s.start;$('visible-count').textContent=s.count+'根';$('date-range').textContent=`${s.bars[s.start][0]} — ${s.bars[s.start+s.count-1][0]}`}
function quote(){
 if(!s.bars.length)return;let b=s.bars[s.hover>=0?s.hover:s.bars.length-1],tone=b[7]>0?'up':b[7]<0?'down':'';
 const box=$('quote');box.replaceChildren();let date=document.createElement('strong');date.textContent=b[0];box.append(date);
 for(const [label,val,cls] of [['开',number(b[1]),''],['高',number(b[2]),''],['低',number(b[3]),''],['收',number(b[4]),tone],['涨跌',percent(b[7]),tone],['来源',b[12]||'HistData BID','']]){let e=document.createElement('span');e.textContent=label;let v=document.createElement('b');v.textContent=val;v.className=cls;e.append(v);box.append(e)}
 for(let n of [5,10,20,60])$('ma'+n).textContent=number(b[[5,10,20,60].indexOf(n)+8]);
}
function jump(date){if(!s.bars.length)return;let i=s.bars.findIndex(b=>b[0]>=date);if(i<0)i=s.bars.length-1;s.count=Math.min(s.count,goldRangeCount(12));s.start=Math.round(i-s.count/2);clamp();s.hover=i;quote();sync();requestDraw();setRangeActive('')}
function zoom(factor,pivot=.65){if(!s.bars.length)return;let old=s.count,next=Math.round(old*factor);s.count=Math.max(15,Math.min(s.bars.length,next));s.start=Math.round(s.start+(old-s.count)*pivot);s.hover=-1;setRangeActive('');sync();quote();requestDraw()}
function line(x1,y1,x2,y2,color,dash=[]){ctx.strokeStyle=color;ctx.lineWidth=1;ctx.setLineDash(dash);ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([])}
function draw(){
 let r=canvas.getBoundingClientRect(),w=r.width,h=r.height,ratio=Math.min(devicePixelRatio||1,2);if(w<20||h<20)return;
 if(canvas.width!==Math.round(w*ratio)||canvas.height!==Math.round(h*ratio)){canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio)}
 ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);if(!s.bars.length){geom=null;return}
 const bars=s.bars.slice(s.start,s.start+s.count),left=12,right=w-65,top=24,bottom=Math.floor(h*.88),vtop=bottom+33,vbottom=h-27,step=(right-left)/bars.length;
 let lows=bars.map(b=>b[3]),highs=bars.map(b=>b[2]);for(let n of s.mas){let k=[5,10,20,60].indexOf(n)+8;for(let b of bars)if(b[k]!=null){lows.push(b[k]);highs.push(b[k])}}
 let low=Math.min(...lows),high=Math.max(...highs),padding=Math.max((high-low)*.09,high*.001);low-=padding;high+=padding;
 const y=v=>bottom-(v-low)/(high-low)*(bottom-top),x=i=>left+(i+.5)*step,maxvol=Math.max(1,...bars.map(b=>b[5]||0));geom={left,right,top,bottom,vtop,vbottom,step,w,h};
 ctx.font='10px "Microsoft YaHei",sans-serif';ctx.textBaseline='middle';ctx.textAlign='left';
 for(let j=0;j<=4;j++){let v=low+(high-low)*j/4,yy=y(v);line(left,yy,right,yy,C.grid);ctx.fillStyle=C.text;ctx.fillText(number(v),right+9,yy)}
 
 
 let ticks=Math.max(2,Math.floor((right-left)/150));for(let j=0;j<=ticks;j++){let i=Math.min(bars.length-1,Math.round(j*(bars.length-1)/ticks)),xx=x(i);line(xx,top,xx,vbottom,C.grid);ctx.fillStyle=C.text;ctx.textAlign=j===0?'left':j===ticks?'right':'center';ctx.fillText(bars[i][0],xx,h-11)}ctx.textAlign='left';
 ctx.save();ctx.beginPath();ctx.rect(left,top-1,right-left,vbottom-top+2);ctx.clip();
 const bw=Math.max(.8,Math.min(13,step*.68));
 bars.forEach((b,i)=>{let xx=x(i),up=b[4]>=b[1],color=up?C.up:C.down;line(xx,y(b[3]),xx,y(b[2]),color);let yy=Math.min(y(b[1]),y(b[4])),bh=Math.max(1,Math.abs(y(b[1])-y(b[4])));ctx.fillStyle=up?'#fff':color;ctx.strokeStyle=color;ctx.lineWidth=1;if(step<2)line(xx,y(b[1]),xx,y(b[4]),color);else{ctx.fillRect(xx-bw/2,yy,bw,bh);ctx.strokeRect(xx-bw/2,yy,bw,bh)}});
 for(let n of s.mas){let k=[5,10,20,60].indexOf(n)+8;ctx.strokeStyle=C[n];ctx.lineWidth=1.15;ctx.beginPath();let active=false;bars.forEach((b,i)=>{if(b[k]==null){active=false;return}if(!active){ctx.moveTo(x(i),y(b[k]));active=true}else ctx.lineTo(x(i),y(b[k]))});ctx.stroke()}
 ctx.restore();
 if(s.direction!=='raw'){
  const signals=s.signals.filter(e=>e.direction===s.direction&&e.code===s.code),map=new Map(bars.map((b,i)=>[b[0],i]));
  for(const e of signals){if(!map.has(e.signal_date))continue;let i=map.get(e.signal_date),xx=x(i),active=e.id===s.selected?.id;line(xx,top,xx,vbottom,active?'#5478da':'#b8c8e8',[4,4]);ctx.fillStyle=active?'#466bc9':'#a2b5d6';ctx.beginPath();let yy=Math.max(top+14,y(bars[i][2])-15);ctx.moveTo(xx,yy+7);ctx.lineTo(xx-5,yy-2);ctx.lineTo(xx+5,yy-2);ctx.fill();if(active){ctx.fillText('信号',xx+7,yy);if(map.has(e.entry_date)){let j=map.get(e.entry_date);ctx.fillStyle='#b28b3d';ctx.fillText('次日开盘',Math.min(x(j)+5,right-55),Math.min(bottom-8,y(bars[j][1])+17))}}}
 }
 if(s.hover>=s.start&&s.hover<s.start+s.count){let i=s.hover-s.start,b=bars[i],xx=x(i),yy=y(b[4]);line(xx,top,xx,vbottom,'#a7b7d6',[4,3]);line(left,yy,right,yy,'#bdc9df',[4,3]);ctx.fillStyle='#7189af';ctx.fillRect(right+2,yy-9,61,18);ctx.fillStyle='#fff';ctx.fillText(number(b[4]),right+8,yy);ctx.fillStyle='#7189af';let tx=Math.max(left,Math.min(xx-36,right-74));ctx.fillRect(tx,h-23,76,19);ctx.fillStyle='#fff';ctx.textAlign='center';ctx.fillText(b[0],tx+38,h-13);ctx.textAlign='left'}
}
canvas.addEventListener('wheel',e=>{if(!geom||!s.bars.length)return;e.preventDefault();let rect=canvas.getBoundingClientRect(),pivot=Math.max(0,Math.min(1,(e.clientX-rect.left-geom.left)/(geom.right-geom.left)));zoom(e.deltaY<0?.82:1.22,pivot)},{passive:false});
canvas.addEventListener('pointerdown',e=>{if(!geom)return;canvas.focus({preventScroll:true});s.drag={x:e.clientX,start:s.start,step:geom.step};canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!geom||!s.bars.length)return;if(s.drag){s.start=s.drag.start-Math.round((e.clientX-s.drag.x)/s.drag.step);s.hover=-1;setRangeActive('');sync();requestDraw();return}let x=e.clientX-canvas.getBoundingClientRect().left;s.hover=Math.max(s.start,Math.min(s.start+s.count-1,s.start+Math.floor((x-geom.left)/geom.step)));quote();requestDraw()});
function release(e){if(s.drag){s.drag=null;if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId)}}
canvas.addEventListener('pointerup',release);canvas.addEventListener('pointercancel',release);canvas.addEventListener('pointerleave',()=>{if(!s.drag){s.hover=-1;quote();requestDraw()}});
canvas.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();s.start+=e.key==='ArrowLeft'?-Math.max(1,Math.floor(s.count*.1)):Math.max(1,Math.floor(s.count*.1));sync();requestDraw()}if(e.key==='+'||e.key==='=')zoom(.8);if(e.key==='-')zoom(1.25)});
$('search').addEventListener('input',()=>list());$('search').addEventListener('keydown',e=>{if(e.key==='Enter'&&s.filtered.length){const x=s.filtered[0];load(x.code,s.direction==='raw'?null:x)}});
$('scope-all').onclick=()=>scope('all');$('scope-leaders').onclick=()=>scope('leaders');
function scope(value){s.scope=value;$('scope-all').classList.toggle('active',value==='all');$('scope-leaders').classList.toggle('active',value==='leaders');list();if(selectedIndex()<0&&s.filtered[0]){const x=s.filtered[0];load(x.code,s.direction==='raw'?null:x)}}
$('direction').onchange=()=>{s.direction=$('direction').value;s.selected=null;list();detail();if(s.filtered.length){const x=s.direction==='raw'?(s.filtered.find(x=>x.code===s.code)||s.filtered[0]):s.filtered[0];load(x.code,s.direction==='raw'?null:x)}else requestDraw()};
for(let id of ['sort','from-date','to-date'])$(id).onchange=()=>list();
$('previous').onclick=()=>switchStock(-1);$('next').onclick=()=>switchStock(1);
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName))return;if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();switchStock(e.key==='ArrowUp'?-1:1)}});
document.querySelectorAll('[data-range]').forEach(b=>b.onclick=()=>{s.count=b.dataset.range==='all'?s.bars.length:goldRangeCount(b.dataset.range==='63'?3:12);s.start=s.bars.length-s.count;s.hover=-1;setRangeActive(b.dataset.range);sync();quote();requestDraw()});
$('zoom-in').onclick=()=>zoom(.8);$('zoom-out').onclick=()=>zoom(1.25);$('recent').onclick=()=>{s.start=s.bars.length-s.count;s.hover=-1;sync();quote();requestDraw()};$('pan').oninput=()=>{s.start=Number($('pan').value);s.hover=-1;sync();requestDraw()};$('jump').onclick=()=>{if($('jump-date').value)jump($('jump-date').value)};
document.querySelectorAll('[data-ma]').forEach(c=>c.onchange=()=>{let n=Number(c.dataset.ma);c.checked?s.mas.add(n):s.mas.delete(n);requestDraw()});
new ResizeObserver(requestDraw).observe($('chart-wrap'));
(async()=>{try{const d=await json('/api/gold/history');metadata=d.metadata;s.stocks=[{code:'XAUUSD',name:'伦敦金现货',is_leader:false}];s.signals=[];s.direction='raw';s.scope='all';$('direction').value='raw';$('snapshot').textContent=`报价截至 ${d.last} · 非实时`;$('gold-freshness').textContent=metadata.latest_complete_date?`完整伦敦日线截至 ${metadata.latest_complete_date}；当前未结束日不计入。近期使用 Gold Price API，UTC日线仅在与伦敦午夜完全一致时接入。`:`最近报价 ${metadata.last_quote_utc}，以源站已发布数据为准。`;await load('XAUUSD')}catch(e){status(e.message);$('snapshot').textContent='黄金数据未就绪'}})();
