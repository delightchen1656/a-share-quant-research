'use strict';
const $=id=>document.getElementById(id);
const state={signals:[],filtered:[],stocks:[],filteredStocks:[],selected:null,code:null,view:'stocks',chart:null,start:0,count:0,hover:-1,drag:null,mas:new Set([5,10,20,60]),request:0,group:'volume',direction:'raw',directionInfo:null,load:0,limit:150,generation:null,polling:false,stockMatchCounts:new Map()};
const colors={up:'#dc505c',down:'#15917c',grid:'#edf0f5',text:'#91a0b4',signal:'#6d8ce1',5:'#c18b2b',10:'#9567d2',20:'#4896b1',60:'#d36389'};
const canvas=$('chart'),ctx=canvas.getContext('2d');
let geometry=null,frame=0;
function pct(x){return x==null?'未到期 / 缺价':`${x>0?'+':''}${(x*100).toFixed(2)}%`;}
function price(x){return x==null?'—':Number(x).toFixed(2);}
function volume(x){if(x==null)return '—';return x>=10000?(x/10000).toFixed(2)+'万手':Math.round(x).toLocaleString('zh-CN')+'手';}
function tone(x){return x==null||x===0?'neutral':x>0?'up':'down';}
function dropPct(x){return x==null?'未到期 / 缺价':x===0?'0.00%':`-${(x*100).toFixed(2)}%`;}
function metric(id,text,val){$(id).textContent=text;$(id).className=val===undefined?'':tone(val);}
function requestDraw(){if(!frame)frame=requestAnimationFrame(()=>{frame=0;draw();});}
async function getJSON(url){const r=await fetch(url,{cache:'no-store'});const j=await r.json();if(!r.ok)throw Error(j.error||'读取失败');return j;}
function syncFilterURL(){const p=new URLSearchParams({direction:state.direction});if($('universe-scope').value==='leaders')p.set('scope','leaders');if($('year').value)p.set('year',$('year').value);if($('search').value.trim())p.set('q',$('search').value.trim());history.replaceState(null,'','/?'+p);}
function setDirection(value){state.direction=value;state.view=value==='raw'?'stocks':'signals';$('direction-select').value=value;$('view-stocks').classList.toggle('active',state.view==='stocks');$('view-signals').classList.toggle('active',state.view==='signals');syncFilterURL();filterSignals();if(value==='raw'){const next=state.filteredStocks.find(s=>s.code===state.code)||state.filteredStocks[0];if(next)loadHistory(next.code);return;}const next=state.filtered.find(s=>s.id===state.selected)||state.filtered[0];if(next)select(next.id);else{state.selected=null;state.chart=null;$('chart-status').textContent='当前方向与筛选下没有匹配信号';$('chart-status').classList.remove('hidden');}}
function modeUI(){const raw=state.direction==='raw';document.body.classList.toggle('raw-mode',raw);$('direction-select').value=state.direction;$('study-tag').textContent=raw?'原K线':state.direction==='2'?'方向1.2 · 5%触及筛选':'方向1.1 · 标准箱体';$('direction-note').textContent=raw?'浏览沪深主板全部已存储日K线，不叠加箱体或筛选标记。':state.direction==='2'?(state.directionInfo?.error||state.directionInfo?.description||'冻结模型筛选').replaceAll('方向2','方向1.2')+' '+(state.directionInfo?.pool_note||''):'标准箱体 · 横盘增量与1.2倍放量强阳线 · 同箱首信号';$('shape-legend').innerHTML=raw?'原始日K视图 · 前复权 · 横轴仅交易日':'<i class="yin-dot"></i>下跌段 <i class="base-dot"></i>横盘增量段 <i class="spike-dot"></i>放量阳线 <i class="signal-dot"></i>60日最高点 / D+60';}

function filterSignals(){
 const query=$('search').value.trim().toLowerCase(),year=$('year').value;
 const timeDirection=$('time-sort').value==='asc'?1:-1,outcomeSort=$('outcome-sort').value;
 const outcomeField=outcomeSort.startsWith('drop_')?'max_drop60':'peak_return60',outcomeOrder=outcomeSort.split('_')[1];
 const leadersOnly=$('universe-scope').value==='leaders';state.limit=150;
 state.filtered=state.signals.filter(s=>state.direction!=='raw'&&(state.direction==='1'||s.direction2)&&(!leadersOnly||s.is_leader)&&(!year||s.year===Number(year))&&(!query||`${s.code} ${s.name} ${s.date}`.toLowerCase().includes(query)));
 state.filtered.sort((a,b)=>{
  if(outcomeOrder){
   const aMissing=!Number.isFinite(a[outcomeField]),bMissing=!Number.isFinite(b[outcomeField]);
   if(aMissing!==bMissing)return aMissing?1:-1;
   if(!aMissing&&a[outcomeField]!==b[outcomeField])return (a[outcomeField]-b[outcomeField])*(outcomeOrder==='asc'?1:-1);
  }
  return timeDirection*a.date.localeCompare(b.date)||a.code.localeCompare(b.code)||a.id.localeCompare(b.id);
 });
 const matchingCodes=new Set(state.filtered.map(s=>s.code));
 state.filteredStocks=state.stocks.filter(s=>(!leadersOnly||s.is_leader)&&(!query||`${s.code} ${s.name}`.toLowerCase().includes(query))&&(state.direction!=='2'||matchingCodes.has(s.code)));
 state.stockMatchCounts=new Map();for(const s of state.filtered)state.stockMatchCounts.set(s.code,(state.stockMatchCounts.get(s.code)||0)+1);
 const stockDirection=$('stock-sort').value==='asc'?1:-1;
 state.filteredStocks.sort((a,b)=>state.direction==='raw'?a.code.localeCompare(b.code):stockDirection*((state.stockMatchCounts.get(a.code)||0)-(state.stockMatchCounts.get(b.code)||0))||a.code.localeCompare(b.code));
 $('count').textContent=state.view==='stocks'?`${state.filteredStocks.length} 只股票`:`${state.filtered.length} 次匹配`;
 $('total').textContent=state.direction==='raw'?`${state.filteredStocks.length} 只股票`:`${state.filteredStocks.length} 只 / ${state.filtered.length} 次`;
 $('signal-sorting').hidden=state.view!=='signals';
 $('stock-sorting').hidden=state.view!=='stocks'||state.direction==='raw';
 modeUI();
 renderList();updateNav();
 renderMatches();requestDraw();
}
function renderList(){
 const list=$('signal-list'),scroll=list.scrollTop;list.replaceChildren();
 $('list-title').textContent=state.view==='stocks'?'范围股票':'股票 / 信号日';$('list-value').textContent=state.direction==='raw'?'日K':state.view==='stocks'?'箱体次数 '+($('stock-sort').value==='asc'?'↑':'↓'):'60日最大涨 / 跌';
 const rows=state.view==='stocks'?state.filteredStocks:state.filtered;
 if(!rows.length){const empty=document.createElement('div');empty.className='empty-list';empty.textContent='没有匹配结果';list.append(empty);return;}
 const frag=document.createDocumentFragment();
 for(const s of rows.slice(0,state.limit)){
  const isStock=state.view==='stocks',on=isStock?s.code===state.code:s.id===state.selected;
  const item=document.createElement('div');item.className='signal-item'+(on?' selected':'');item.dataset.id=isStock?s.code:s.id;
  item.setAttribute('role','option');item.setAttribute('aria-selected',String(on));item.tabIndex=0;
  const left=document.createElement('div'),name=document.createElement('strong'),code=document.createElement('small'),date=document.createElement('time');
  name.textContent=s.name;if(s.is_leader){const star=document.createElement('span');star.className='leader-star';star.textContent='★ ';star.title=s.leader_source||'合并龙头';name.prepend(star);}code.textContent=s.code;left.append(name,code);
  if(s.is_leader&&s.leader_source){const source=document.createElement('span');source.className='leader-origin';source.textContent=s.leader_source;left.append(source);}
  if(!isStock){date.textContent=s.date;date.dateTime=s.date;left.append(date);}
  else{date.textContent=s.last?'行情至 '+s.last:'查看全部已存储日线';left.append(date);}
  if(state.group==='volume'&&!isStock){const desc=document.createElement('span');desc.className='volume-note';desc.textContent=`横盘量${s.base_decline_volume_ratio.toFixed(2)}倍 · 实体${(s.body_range_ratio*100).toFixed(0)}% · 上影${(s.upper_shadow_ratio*100).toFixed(0)}%`;left.append(desc);}
  if(!isStock){const tag=document.createElement('span');tag.className='direction-badge';tag.textContent=state.direction==='2'?'方向1.2 · '+(s.direction2_basis||'筛选'):'方向1.1 · 标准箱体';left.append(tag);}
  const ret=document.createElement('span');ret.className=isStock?'ret neutral':'signal-outcomes';
  if(isStock)ret.textContent=state.direction==='raw'?'日K':(state.stockMatchCounts.get(s.code)||0)+' 次';
  else{
   const gain=document.createElement('span');gain.className='ret '+tone(s.peak_return60);gain.textContent='涨 '+(s.peak_return60==null?s.peak_status60:pct(s.peak_return60));gain.title='信号后D1至D60最高价相对D1开盘价';
   const drop=document.createElement('span');drop.className='ret '+(s.max_drop60==null||s.max_drop60===0?'neutral':'down');drop.textContent='跌 '+(s.max_drop60==null?s.trough_status60:dropPct(s.max_drop60));drop.title='信号后D1至D60最低价相对D1开盘价；未跌破记0%';ret.append(gain,drop);
  }
  const action=()=>isStock?loadHistory(s.code):select(s.id);
  item.append(left,ret);item.addEventListener('click',action);item.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action();}});
  frag.append(item);
 }
 list.append(frag);list.scrollTop=scroll;
 if(rows.length>state.limit){const more=document.createElement('button');more.className='load-more';more.textContent=`再显示150条（已显示${Math.min(state.limit,rows.length)} / ${rows.length}）`;more.addEventListener('click',()=>{state.limit+=150;renderList();});list.append(more);}
}
function updateNav(){const rows=state.view==='stocks'?state.filteredStocks:state.filtered,i=rows.findIndex(s=>state.view==='stocks'?s.code===state.code:s.id===state.selected);$('previous').disabled=i<=0;$('next').disabled=i<0||i>=rows.length-1;}
function step(direction){const rows=state.view==='stocks'?state.filteredStocks:state.filtered,i=rows.findIndex(s=>state.view==='stocks'?s.code===state.code:s.id===state.selected),next=rows[i+direction];if(next)state.view==='stocks'?loadHistory(next.code):select(next.id);}
function renderMatches(){
 const area=$('stock-matches');area.replaceChildren();const rows=state.filtered.filter(s=>s.code===state.code);
 $('stock-matches-count').textContent=`本股匹配 ${rows.length} 次`;
 if(!rows.length){area.textContent='当前筛选下无此结构，仍可浏览全部K线';return;}
 for(const s of rows){const b=document.createElement('button');b.textContent=s.date;b.className=s.id===state.selected?'selected':'';b.addEventListener('click',()=>select(s.id));area.append(b);}
}
function switchView(view){state.view=view;$('view-stocks').classList.toggle('active',view==='stocks');$('view-signals').classList.toggle('active',view==='signals');filterSignals();}
async function select(id){
 const s=state.signals.find(s=>s.id===id);if(!s)return;
 await loadHistory(s.code,id);
}
async function loadHistory(code,eventId=''){
 const stock=state.stocks.find(s=>s.code===code);if(!stock)return;
 const s=eventId?state.signals.find(s=>s.id===eventId):null;
 state.code=code;state.selected=eventId||null;state.hover=-1;state.drag=null;const token=++state.request;
 renderList();updateNav();renderMatches();
 $('stock-name').textContent=(stock.is_leader?'★ ':'')+stock.name;$('stock-code').textContent=code;
 $('leader-source').textContent=stock.leader_source||'';$('leader-source').hidden=!stock.is_leader;
 $('box-tag').hidden=!s;
 if(s){$('box-tag').className='direction-badge';$('box-tag').textContent=state.direction==='2'?'方向1.2 · '+(s.direction2_basis||'筛选'):'方向1.1 · 标准箱体';$('box-tag').title='';}
 $('reference-info').hidden=!s;
 if(s)$('reference-info').textContent=s.entry_open!=null?`涨跌幅基准：信号次日开盘 ${s.entry_date} · 前复权 ${price(s.entry_open)} 元（原始开盘 ${price(s.entry_raw_open)} 元）。观察D+1至D+60，含次日当天高低点。`:`涨跌幅基准：信号次日开盘 · ${s.entry_status}，不顺延取价。`;
 if(s&&state.group==='volume'){
  $('signal-rule').textContent=`下跌${pct(s.decline_return)}后转为横盘 · 横盘整体增量 · 放量强阳线，上影占振幅${(s.upper_shadow_ratio*100).toFixed(1)}% · 同箱只留首个信号`;
  $('metric-close-label').textContent='横盘均量 / 下跌均量';$('metric-ma-label').textContent='信号量 / 横盘均量';$('metric-distance-label').textContent='实体占全天振幅';
  metric('signal-close',s.base_decline_volume_ratio.toFixed(2)+' 倍');metric('signal-ma',s.volume_multiple.toFixed(2)+' 倍');metric('signal-distance',(s.body_range_ratio*100).toFixed(1)+'%');
 }else{
  $('signal-rule').textContent='全部已存储日K线 · 点击本股匹配日期定位结构，或切换左侧“结构结果”';
  $('metric-close-label').textContent='最新收盘';$('metric-ma-label').textContent='最新MA60';$('metric-distance-label').textContent='偏离MA60';
 }
 metric('signal-date',s?s.date:'—');metric('signal-return',s?(s.peak_return60==null?s.peak_status60:pct(s.peak_return60)):'—',s?s.peak_return60:null);
 metric('signal-drop',s?(s.max_drop60==null?s.trough_status60:dropPct(s.max_drop60)):'—',s&&s.max_drop60!=null?-s.max_drop60:null);
 $('peak-info').hidden=!s;
 if(s)$('peak-info').textContent=s.peak_complete60&&s.trough_complete60?`60日最高价 ${price(s.peak_price60)} · ${s.peak_date60}（D+${s.peak_day60}）；最低价 ${price(s.trough_price60)} · ${s.trough_date60}（D+${s.trough_day60}）。涨跌均相对次日开盘，未跌破记0%；事后极值，不等同于账户收益或持有期间最大回撤。`:`${s.peak_status60}：已有${s.peak_observed_days60}个有效观察日，暂不显示完整60日最大涨跌幅。`;
 $('metric-date-label').textContent=s?'结构日期':'最新交易日';
 $('focus-signal').disabled=!s;
 $('chart-status').textContent='正在读取行情…';$('chart-status').classList.remove('hidden');
 try{
  const chart=await getJSON(`/api/history?code=${code}&group=${state.group}&event=${encodeURIComponent(eventId)}`);if(token!==state.request)return;
  state.chart=chart;state.count=Math.min(360,chart.bars.length);state.start=chart.bars.length-state.count;
  if(!s){const last=chart.bars.at(-1);metric('signal-date',last[0]);metric('signal-close',price(last[4]));metric('signal-ma',price(last[9]));metric('signal-distance',pct(last[9]?last[4]/last[9]-1:null),last[9]?last[4]/last[9]-1:null);}
  $('date-range').textContent=chart.requested_start+' — '+chart.requested_end;
  const notices=[`实际 ${chart.actual_start} — ${chart.actual_end}`];
  if(chart.future_incomplete)notices.push('后半年行情未齐');
  if(chart.history_incomplete)notices.push('前1年行情未齐');
  if(chart.omitted_sessions)notices.push(`停牌 / 缺价 ${chart.omitted_sessions} 日已略过`);
  if(chart.event.raw_adjusted_return_discrepancy)notices.push('形态期原始与复权涨跌存在差异');
  $('coverage').textContent=notices.join(' · ');
  $('chart-status').classList.add('hidden');if(s)focusSignal();else{syncPan();updateQuote();requestDraw();}
 }catch(err){if(token!==state.request)return;state.chart=null;$('chart-status').textContent=err.message;requestDraw();}
}

function syncPan(){
 if(!state.chart)return;const all=state.chart.bars.length;
 state.count=Math.max(Math.min(30,all),Math.min(Math.round(state.count),all));
 state.start=Math.max(0,Math.min(Math.round(state.start),all-state.count));
 $('pan').max=String(all-state.count);$('pan').value=String(state.start);$('pan').disabled=state.count===all;
 $('visible-count').textContent=`${state.count} / ${all} 日`;
 $('zoom-in').disabled=state.count<=Math.min(30,all);$('zoom-out').disabled=state.count===all;
}
function reset(){if(!state.chart)return;state.count=state.chart.bars.length;state.start=0;state.hover=-1;syncPan();updateQuote();requestDraw();}
function recent(){if(!state.chart)return;state.count=Math.min(252,state.chart.bars.length);state.start=state.chart.bars.length-state.count;state.hover=-1;syncPan();updateQuote();requestDraw();}
function focusSignal(){
 if(!state.chart||!state.chart.event.signal_date)return;
 const i=state.chart.bars.findIndex(b=>b[0]===state.chart.event.signal_date);if(i<0)return;
 state.count=Math.min(360,state.chart.bars.length);state.start=i-240;state.hover=-1;syncPan();updateQuote();requestDraw();
}
function zoom(factor,anchor=.5){
 if(!state.chart)return;const all=state.chart.bars.length,old=state.count;
 const next=Math.max(Math.min(30,all),Math.min(all,Math.round(old*factor)));
 if(next===old)return;const focal=state.start+old*anchor;
 state.count=next;state.start=focal-next*anchor;state.hover=-1;syncPan();updateQuote();requestDraw();
}
function updateQuote(){
 const container=$('quote');container.replaceChildren();if(!state.chart)return;
 const bars=state.chart.bars;const signal=bars.findIndex(b=>b[0]===state.chart.event.signal_date);
 const i=state.hover>=0?state.hover:signal>=0?signal:bars.length-1;const b=bars[i];if(!b)return;
 const date=document.createElement('span');date.className='quote-date';date.textContent=b[0];container.append(date);
 for(const [label,value,change] of [['开',price(b[1])],['高',price(b[2])],['低',price(b[3])],['收',price(b[4])],['较前日',pct(b[10]),b[10]],['量',volume(b[5])]]){
  const s=document.createElement('span');s.textContent=label;const v=document.createElement('b');v.textContent=value;
  if(change!==undefined)v.className=tone(change);else if(label!=='量')v.className=b[4]>=b[1]?'up':'down';s.append(v);container.append(s);
 }
 for(const n of [5,10,20,60]){
  const el=document.querySelector(`[data-ma="${n}"]`).nextElementSibling;
  const idx={5:6,10:7,20:8,60:9}[n];el.textContent=`MA${n} ${price(b[idx])}`;
 }
}

function line(x1,y1,x2,y2,color,width=1,dash=[]){ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dash);ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ctx.setLineDash([]);}
function text(t,x,y,color=colors.text,align='left',font='11px Arial'){ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='middle';ctx.font=font;ctx.fillText(t,x,y);}
function roundRect(x,y,w,h,r,fill){ctx.fillStyle=fill;ctx.beginPath();ctx.roundRect(x,y,w,h,r);ctx.fill();}
function draw(){
 const rect=canvas.getBoundingClientRect(),w=rect.width,h=rect.height,dpr=Math.min(window.devicePixelRatio||1,2);
 if(w<5||h<5)return;
 if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);
 if(!state.chart){geometry=null;return;}
 const all=state.chart.bars,bars=all.slice(state.start,state.start+state.count),left=8,right=w-70,top=29,bottom=Math.round(h*.71),volTop=bottom+31,volBottom=h-29;
 if(right-left<50||bars.length===0)return;
 const width=right-left,spacing=width/bars.length,x=i=>left+(i+.5)*spacing;
 let low=Math.min(...bars.map(b=>b[3])),high=Math.max(...bars.map(b=>b[2]));
 for(const n of state.mas){const k={5:6,10:7,20:8,60:9}[n];for(const b of bars)if(b[k]!=null){low=Math.min(low,b[k]);high=Math.max(high,b[k]);}}
 const pad=Math.max((high-low)*.08,high*.008,.01);low-=pad;high+=pad;
 const y=v=>bottom-(v-low)/(high-low)*(bottom-top);const maxVol=Math.max(...bars.map(b=>b[5]),1)*1.08;
 const vy=v=>volBottom-v/maxVol*(volBottom-volTop);
 geometry={left,right,top,bottom,volTop,volBottom,spacing,x,y,low,high,w,h};
 for(let j=0;j<=4;j++){const yy=top+j*(bottom-top)/4;line(left,yy,right,yy,colors.grid);text(price(high-j*(high-low)/4),right+10,yy);}
 line(left,volTop,right,volTop,colors.grid);line(left,volBottom,right,volBottom,colors.grid);
 text('成交量（手）',left+3,volTop-11,'#9aa6b7','left','10px "Microsoft YaHei"');text(volume(maxVol/1.08),right+10,volTop+8,'#9aa6b7','left','10px Arial');
 // Each shape owns its historical phases; no weekend/holiday slots are inserted.
 const phaseColors={decline:'#6a7c9e08',base:'#369f970e',spike:'#e1ac3918'};
 for(let i=0;i<bars.length;i++){const b=bars[i];if(b[11]){ctx.fillStyle=phaseColors[b[11]]||'#fff';ctx.fillRect(x(i)-spacing/2,top,spacing,bottom-top);}}
 if(state.chart.event.group==='volume'&&state.chart.event.event_id){
  const event=state.chart.event,indices=bars.map((b,i)=>b[11]==='base'||b[11]==='spike'?i:-1).filter(i=>i>=0);
  if(indices.length){const bx=Math.max(left,x(indices[0])-spacing/2),ex=Math.min(right,x(indices.at(-1))+spacing/2);
   line(bx,y(event.box_high),ex,y(event.box_high),'#64a5a1',1,[4,3]);line(bx,y(event.box_low),ex,y(event.box_low),'#64a5a1',1,[4,3]);
   line(bx,y(event.box_high),bx,y(event.box_low),'#64a5a1',.7,[4,3]);
  }
 }
 // Calendar labels use trading indices, so holidays and weekends take no width.
 const ticks=[];const jump=Math.max(1,Math.ceil(bars.length/Math.max(2,Math.floor(width/125))));
 for(let i=0;i<bars.length;i+=jump)ticks.push(i);if(ticks.length&&bars.length-1-ticks.at(-1)>jump*.6)ticks.push(bars.length-1);
 for(const i of ticks){const xx=x(i),labelX=Math.max(left+31,Math.min(xx,right-31));line(xx,top,xx,volBottom,'#f2f4f8');text(bars[i][0],labelX,volBottom+17,colors.text,'center','10px Arial');}
 const candleWidth=Math.max(1,Math.min(14,spacing*.62));
 ctx.save();ctx.beginPath();ctx.rect(left,top,width,bottom-top);ctx.clip();
 for(let i=0;i<bars.length;i++){
  const b=bars[i],xx=x(i),up=b[4]>=b[1],color=up?colors.up:colors.down;
  line(xx,y(b[2]),xx,y(b[3]),color,Math.max(.8,Math.min(1.2,spacing*.2)));
  const bodyTop=Math.min(y(b[1]),y(b[4])),bodyH=Math.max(1,Math.abs(y(b[1])-y(b[4])));
  if(up&&candleWidth>3&&!(state.group==='volume'&&b[11]==='spike')){ctx.fillStyle='#fff';ctx.fillRect(xx-candleWidth/2,bodyTop,candleWidth,bodyH);ctx.strokeStyle=color;ctx.lineWidth=1;ctx.strokeRect(xx-candleWidth/2,bodyTop,candleWidth,bodyH);}else{ctx.fillStyle=color;ctx.fillRect(xx-candleWidth/2,bodyTop,candleWidth,bodyH);}
 }
 for(const n of [5,10,20,60])if(state.mas.has(n)){
  const k={5:6,10:7,20:8,60:9}[n];ctx.strokeStyle=colors[n];ctx.lineWidth=n===60?1.6:1.1;ctx.beginPath();let active=false;
  bars.forEach((b,i)=>{if(b[k]==null){active=false;return;}if(!active){ctx.moveTo(x(i),y(b[k]));active=true;}else ctx.lineTo(x(i),y(b[k]));});ctx.stroke();
 }
 ctx.restore();
 for(let i=0;i<bars.length;i++){const b=bars[i];ctx.fillStyle=b[4]>=b[1]?colors.up:colors.down;const hh=Math.max(1,volBottom-vy(b[5]));ctx.fillRect(x(i)-candleWidth/2,volBottom-hh,candleWidth,hh);}
 if(state.chart.event.group==='volume'&&state.chart.event.event_id){
  for(const [phase,key,color,label] of [['decline','decline_mean_volume','#9aa8bb','下跌均量'],['base','base_mean_volume','#4a9b95','横盘均量']]){
   const ii=bars.map((b,i)=>b[11]===phase?i:-1).filter(i=>i>=0);
   if(ii.length){const bx=x(ii[0])-spacing/2,ex=x(ii.at(-1))+spacing/2,yy=vy(state.chart.event[key]/100);line(bx,yy,ex,yy,color,1.2,[3,2]);if(ex-bx>80)text(label,bx+3,yy-7,color,'left','9px "Microsoft YaHei"');}
  }
  const index=bars.findIndex(b=>b[11]==='spike');
  if(index>=0){const xx=x(index),vv=vy(bars[index][5]);ctx.strokeStyle='#d1a03b';ctx.lineWidth=1.8;ctx.strokeRect(xx-Math.max(candleWidth/2+2,3),vv-2,Math.max(candleWidth+4,6),volBottom-vv+3);text(state.chart.event.volume_multiple.toFixed(1)+'倍',xx,Math.max(volTop+10,vv-10),'#b58b2f','center','10px "Microsoft YaHei"');}
 }
 // All matched structures remain visible on the full history, not only a single event window.
 const matchingDates=new Set(state.filtered.filter(s=>s.code===state.code).map(s=>s.date));
 for(let i=0;i<bars.length;i++)if(matchingDates.has(bars[i][0])){
  const xx=x(i),yy=Math.max(top+3,y(bars[i][2])-7);ctx.fillStyle='#6d8ce1';ctx.beginPath();ctx.moveTo(xx-3,yy-5);ctx.lineTo(xx+3,yy-5);ctx.lineTo(xx,yy);ctx.closePath();ctx.fill();
 }
 const signal=bars.findIndex(b=>b[0]===state.chart.event.signal_date);
 if(signal>=0){
  const xx=x(signal);line(xx,top-4,xx,volBottom,colors.signal,1,[4,4]);
  const label='信号 '+state.chart.event.signal_date,labelW=116,bx=Math.max(left,Math.min(xx-labelW/2,right-labelW));
  roundRect(bx,4,labelW,21,4,'#eff3ff');text(label,bx+labelW/2,14,'#5e7bd3','center','10px "Microsoft YaHei"');
  ctx.beginPath();ctx.arc(xx,y(bars[signal][4]),3.2,0,2*Math.PI);ctx.fillStyle=colors.signal;ctx.fill();
 }
 const exit=bars.findIndex(b=>b[0]===state.chart.event.window_end_date60);
 if(exit>=0){const xx=x(exit);line(xx,top,xx,volBottom,'#d6ab59',1,[2,5]);text('D+60',xx,volTop-11,'#c29b54','center','10px Arial');}
 const peak=bars.findIndex(b=>b[0]===state.chart.event.peak_date60);
 if(peak>=0&&state.chart.event.peak_complete60){
  const xx=x(peak),yy=y(bars[peak][2]);ctx.beginPath();ctx.arc(xx,yy,4,0,Math.PI*2);ctx.fillStyle='#c49b39';ctx.fill();
  const lx=Math.max(left+50,Math.min(xx,right-50));text('最高 '+pct(state.chart.event.peak_return60),lx,Math.max(top+10,yy-14),'#b38b2e','center','10px "Microsoft YaHei"');
 }
 const reference=state.chart.event,refIndex=bars.findIndex(b=>b[0]===reference.entry_date);
 if(refIndex>=0&&reference.entry_open!=null){
  const yy=y(reference.entry_open),xx=x(refIndex);
  if(yy>=top&&yy<=bottom){line(xx,yy,right,yy,'#799ac1',.8,[3,4]);ctx.beginPath();ctx.fillStyle='#6589b7';ctx.arc(xx,yy,3,0,Math.PI*2);ctx.fill();text('次日开盘基准',Math.max(left+40,Math.min(xx+5,right-45)),yy+12,'#6589b7','left','9px "Microsoft YaHei"');}
 }
 if(state.hover>=state.start&&state.hover<state.start+bars.length){
  const i=state.hover-state.start,b=bars[i],xx=x(i),mouse=state.mouse;
  line(xx,top,xx,volBottom,'#7f8da5',.8,[3,3]);
  if(mouse&&mouse.y>=top&&mouse.y<=bottom){
   const yy=mouse.y,value=high-(yy-top)/(bottom-top)*(high-low);line(left,yy,right,yy,'#8e9db6',.7,[3,3]);
   roundRect(right+2,yy-10,65,20,3,'#687a94');text(price(value),right+34,yy,'#fff','center','11px Arial');
  }
  const boxW=85,bx=Math.max(left,Math.min(xx-boxW/2,right-boxW));roundRect(bx,volBottom+5,boxW,20,3,'#687a94');text(b[0],bx+boxW/2,volBottom+15,'#fff','center','10px Arial');
 }
}

canvas.addEventListener('wheel',e=>{if(!geometry||!state.chart)return;e.preventDefault();const r=canvas.getBoundingClientRect();const a=Math.max(0,Math.min(1,(e.clientX-r.left-geometry.left)/(geometry.right-geometry.left)));zoom(e.deltaY<0?.8:1.25,a);},{passive:false});
canvas.addEventListener('pointerdown',e=>{if(!geometry||!state.chart)return;state.drag={x:e.clientX,start:state.start};canvas.setPointerCapture(e.pointerId);canvas.style.cursor='grabbing';});
canvas.addEventListener('pointermove',e=>{
 if(!geometry||!state.chart)return;const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 if(state.drag){state.start=state.drag.start-Math.round((e.clientX-state.drag.x)/geometry.spacing);state.hover=-1;syncPan();updateQuote();requestDraw();return;}
 const i=Math.max(0,Math.min(state.count-1,Math.floor((mx-geometry.left)/geometry.spacing)));
 state.hover=mx>=geometry.left&&mx<=geometry.right&&my>=geometry.top&&my<=geometry.volBottom?state.start+i:-1;state.mouse={x:mx,y:my};updateQuote();requestDraw();
});
canvas.addEventListener('pointerup',e=>{state.drag=null;canvas.style.cursor='crosshair';if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);});
canvas.addEventListener('pointercancel',()=>{state.drag=null;canvas.style.cursor='crosshair';});
canvas.addEventListener('pointerleave',()=>{if(state.drag)return;state.hover=-1;state.mouse=null;updateQuote();requestDraw();});
canvas.addEventListener('dblclick',reset);
canvas.addEventListener('keydown',e=>{
 if(!state.chart||!['ArrowLeft','ArrowRight'].includes(e.key))return;
 e.preventDefault();e.stopPropagation();
 const bars=state.chart.bars,signal=bars.findIndex(b=>b[0]===state.chart.event.signal_date);
 state.hover=Math.max(0,Math.min(bars.length-1,(state.hover>=0?state.hover:signal>=0?signal:state.start+state.count-1)+(e.key==='ArrowRight'?1:-1)));
 if(state.hover<state.start)state.start=state.hover;
 if(state.hover>=state.start+state.count)state.start=state.hover-state.count+1;
 state.mouse=null;syncPan();updateQuote();requestDraw();
});
$('search').addEventListener('input',()=>{syncFilterURL();filterSignals();});$('year').addEventListener('change',()=>{syncFilterURL();filterSignals();});
$('universe-scope').addEventListener('change',()=>{syncFilterURL();filterSignals();if($('universe-scope').value==='leaders'&&!state.stocks.find(s=>s.code===state.code)?.is_leader&&state.filteredStocks.length)loadHistory(state.filteredStocks[0].code);});
$('time-sort').addEventListener('change',()=>{$('outcome-sort').value='';$('signal-list').scrollTop=0;filterSignals();});
$('outcome-sort').addEventListener('change',()=>{$('signal-list').scrollTop=0;filterSignals();});
$('stock-sort').addEventListener('change',()=>{$('signal-list').scrollTop=0;filterSignals();});
$('direction-select').addEventListener('change',()=>setDirection($('direction-select').value));
$('view-stocks').addEventListener('click',()=>switchView('stocks'));$('view-signals').addEventListener('click',()=>switchView('signals'));
function goSimulator(){const p=new URLSearchParams({scope:$('universe-scope').value,direction:state.direction==='raw'?'1':state.direction,year:$('year').value,q:$('search').value});location.assign('/simulator?'+p.toString());}
$('manual-sim').addEventListener('click',goSimulator);$('sim-page-link').addEventListener('click',e=>{e.preventDefault();goSimulator();});
$('previous').addEventListener('click',()=>step(-1));$('next').addEventListener('click',()=>step(1));
$('reset').addEventListener('click',reset);$('zoom-in').addEventListener('click',()=>zoom(.75));$('zoom-out').addEventListener('click',()=>zoom(1/.75));
$('focus-signal').addEventListener('click',focusSignal);$('recent').addEventListener('click',recent);
$('pan').addEventListener('input',()=>{state.start=Number($('pan').value);state.hover=-1;requestDraw();updateQuote();});
document.querySelectorAll('[data-ma]').forEach(input=>input.addEventListener('change',()=>{const n=Number(input.dataset.ma);if(input.checked)state.mas.add(n);else state.mas.delete(n);requestDraw();}));
document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;if(e.key==='ArrowUp'){e.preventDefault();step(-1);}else if(e.key==='ArrowDown'){e.preventDefault();step(1);}else if(e.key==='Home'){e.preventDefault();reset();}});
new ResizeObserver(requestDraw).observe($('chart-wrap'));

async function loadDataset(){
 const group='volume';
 const token=++state.load;state.request++;state.group=group;state.selected=null;state.chart=null;
 $('chart-status').textContent='正在读取形态信号…';$('chart-status').classList.remove('hidden');
 try{
  const data=await getJSON('/api/signals?include_directions=1&group='+encodeURIComponent(group));if(token!==state.load)return;state.signals=data.signals;state.directionInfo=data.directions;
  if(data.scope!=='SH_SZ_MAIN_BOARD_ONLY'||data.group!=='volume'||data.observation_version!=='future60_nextopen_high_low_v1'||data.return_basis!=='next_session_open'||data.structure_version!=='base_volume_strong_bullish_one_box_v5_volume12'||data.min_volume_multiple!==1.2)throw Error('请打开按次日开盘为基准的新版沪深主板查看器。');
  $('search').value='';
  $('year').replaceChildren();const all=document.createElement('option');all.value='';all.textContent='全部年份';$('year').append(all);
  modeUI();
  $('shape-legend').innerHTML='<i class="yin-dot"></i>下跌段 <i class="base-dot"></i>横盘增量段 <i class="spike-dot"></i>放量阳线 <i class="signal-dot"></i>60日最高点 / D+60';
  $('snapshot').textContent=`主板行情至 ${data.cutoff} · 全历史`;$('total').textContent=`${state.stocks.length} 只 / ${data.total} 次`;state.generation=data.generation;
  for(const year of data.years){const o=document.createElement('option');o.value=year;o.textContent=year+' 年';$('year').append(o);}
  filterSignals();
  const preferred=state.filtered.find(s=>s.code===state.code)||state.filtered.find(s=>s.id===data.default_id)||state.filtered[0];
  if(preferred&&state.direction!=='raw')await select(preferred.id);else await loadHistory(state.code||'002130');
 }catch(err){if(token!==state.load)return;$('chart-status').textContent='启动失败：'+err.message;$('snapshot').textContent='行情未载入';}
}
async function init(){
 try{const data=await getJSON('/api/universe');state.stocks=data.stocks;
  if(data.scope!=='SH_SZ_MAIN_BOARD_ONLY')throw Error('股票范围不是沪深主板，请打开最新版本。');
  const params=new URLSearchParams(location.search),requested=params.get('direction');state.direction=['2','1.2'].includes(requested)?'2':['1','1.1'].includes(requested)?'1':'raw';$('direction-select').value=state.direction;
  if(params.get('scope')==='leaders')$('universe-scope').value='leaders';
  await loadDataset();$('search').value=params.get('q')||'';$('year').value=params.get('year')||'';syncFilterURL();switchView(state.direction==='raw'?'stocks':'signals');const first=state.filtered.find(s=>s.id===state.selected)||state.filtered[0];if(first&&first.id!==state.selected)await select(first.id);await pollStatus();
 }catch(err){$('chart-status').textContent='无法加载全范围股票：'+err.message;}
}
async function pollStatus(){
 if(state.polling)return;state.polling=true;
 try{
  const status=await getJSON('/api/status');
  const stamp=status.matched_at?new Date(status.matched_at).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'}):'—';
  const waiting=status.refresh?.status==='waiting_for_market_commit';
  const failed=status.refresh?.status==='failed';
  $('update-info').textContent=`仅沪深主板 · 每日19:00检测 · 最近匹配 ${stamp}`+(waiting?' · 等待当日日线完成提交':failed?' · 本次刷新失败，保留最近已验证行情':'');
  if(state.generation&&status.generation!==state.generation){
   const saved={id:state.selected,code:state.code,search:$('search').value,year:$('year').value,timeSort:$('time-sort').value,outcomeSort:$('outcome-sort').value,stockSort:$('stock-sort').value,direction:state.direction};
   const u=await getJSON('/api/universe');state.stocks=u.stocks;await loadDataset();
   $('search').value=saved.search;$('year').value=saved.year;$('time-sort').value=saved.timeSort;$('outcome-sort').value=saved.outcomeSort;$('stock-sort').value=saved.stockSort;state.direction=saved.direction;filterSignals();
   if(state.direction!=='raw'&&saved.id&&state.signals.some(s=>s.id===saved.id))await select(saved.id);else if(state.stocks.some(s=>s.code===saved.code))await loadHistory(saved.code);
  }
 }catch(err){$('update-info').textContent='更新状态暂不可用，当前已加载行情仍可浏览。';}
 finally{state.polling=false;}
}
setInterval(pollStatus,60000);
init();
